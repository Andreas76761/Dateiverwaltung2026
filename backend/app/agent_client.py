"""Future Dateiverwaltung – Agent für weitere Computer.

Auf jedem weiteren Computer ausführen (gleiche Codebasis, nur Python nötig):

    python -m app.agent_client --server http://ZENTRALER-PC:8800 --computer laptop \
        --key GEHEIM --target "C:/Users/andreas/OneDrive/Future-Dateiverwaltung" scan inventory copy

Befehle:
  scan       Festplatten lesen (read-only), Textauszüge/Hashes/Miniaturen an den Server senden
  inventory  installierte Programme, LLM-Tools und lokale Modelle melden
  copy       freigegebene Kopien vom Server abholen und lokal in den Cloud-Ordner kopieren
  watch      alle 10 Minuten: copy + Heartbeat (dauerhaft laufen lassen)
  service    Dauerbetrieb als Hintergrunddienst: Heartbeat + freigegebene Kopien alle 10 Minuten,
             Einlesen + Inventar nach Zeitplan (--interval) und auf Anforderung des Servers.
             Einrichten als Dienst (Windows-Aufgabenplanung, macOS launchd, Linux systemd):
             python -m app.service_install agent --server … --computer …

Statt der Optionen kann eine Konfigurationsdatei genutzt werden (legt der Dienst-Installer an):
    python -m app.agent_client --config ~/.fdv-agent.json service

Der Agent löscht, verschiebt oder überschreibt niemals Dateien.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

VERSION = "1.0.0"
BATCH = 200
HASH_MAX = 512 * 1024 * 1024


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


class Agent:
    def __init__(self, server: str, computer: str, key: str, target: str | None, thumbs: bool, download_online: bool = False):
        self.download_online = download_online
        self.service_mode = False
        self.server = server.rstrip("/")
        self.computer = computer
        self.http = httpx.Client(base_url=self.server, headers={"X-API-Key": key} if key else {}, timeout=120)
        self.target = Path(target).resolve() if target else None
        self.thumbs = thumbs
        self.state_file = Path.home() / ".fdv-agent-state.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def save_state(self):
        self.state_file.write_text(json.dumps(self.state))

    def heartbeat(self):
        self.http.post("/api/agents/heartbeat", json={
            "computer_id": self.computer, "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}", "version": VERSION}).raise_for_status()

    # ---------------- scan ----------------
    def walk(self, root: str, excl_dirs: set[str], excl_ext: set[str]):
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: print("  !", e)):
            dirnames[:] = [d for d in dirnames if d not in excl_dirs
                           and not (self.target and Path(dirpath, d).resolve() == self.target)]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in excl_ext:
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                yield p, os.path.relpath(p, root).replace("\\", "/"), fn, st

    def scan(self):
        from .connectors.cloudfiles import is_online_only, real_name
        from .safety import sha256_file
        from .skills import extract, thumbnails
        from .skills.filetype import detect

        cfg = self.http.get(f"/api/agents/{self.computer}/config").raise_for_status().json()
        excl_dirs, excl_ext = set(cfg["exclude_dirs"]), set(cfg["exclude_ext"])
        for vol in cfg["volumes"]:
            root = vol["path"]
            if not os.path.isdir(root):
                print(f"Überspringe {vol['name']}: {root} nicht vorhanden")
                continue
            print(f"Lese {vol['name']} ({root}) …")
            started = datetime.now(timezone.utc).isoformat(timespec="seconds")
            du = shutil.disk_usage(root)
            volume = {**vol, "total_bytes": du.total, "free_bytes": du.free}
            batch, pending_thumbs, n = [], {}, 0

            def flush(final=False):
                r = self.http.post("/api/agents/ingest", json={
                    "computer_id": self.computer, "volume": volume, "entries": batch,
                    "final": final, "scan_started": started}).raise_for_status().json()
                for rel, fid in r["ids"].items():
                    if rel in pending_thumbs:
                        self.upload_thumbs(fid, *pending_thumbs[rel])
                batch.clear()
                pending_thumbs.clear()

            for path, rel, raw_name, st in self.walk(root, excl_dirs, excl_ext):
                name, _ = real_name(raw_name)
                rel = rel[: len(rel) - len(raw_name)] + name
                online = is_online_only(st, raw_name)
                key = f"{vol['id']}|{rel}"
                sig = f"{st.st_size}|{int(st.st_mtime)}|{int(online)}"
                e = {"path": path, "rel_path": rel, "name": name, "size": st.st_size, "online_only": online,
                     "mtime": iso(st.st_mtime), "ctime": iso(getattr(st, "st_birthtime", st.st_ctime))}
                if online and not self.download_online:
                    pass  # Cloud-Platzhalter: nur Metadaten – Lesen würde den Download auslösen
                elif self.state.get(key, {}).get("sig") == sig:
                    e["sha256"] = self.state[key].get("sha")
                else:
                    ext = detect(name)[0]
                    try:
                        e["sha256"] = sha256_file(path) if st.st_size <= HASH_MAX else None
                        e["text_excerpt"], e["page_count"] = extract.extract_text(path, ext)
                    except Exception as exc:
                        print("  ! Extraktion", path, exc)
                    if self.thumbs and thumbnails.supports(ext):
                        pending_thumbs[rel] = (path, ext)
                    self.state[key] = {"sig": sig, "sha": e.get("sha256")}
                batch.append(e)
                n += 1
                if len(batch) >= BATCH:
                    flush()
                    self.save_state()
                    print(f"  {n} Dateien")
            flush(final=True)
            self.save_state()
            print(f"  fertig: {n} Dateien")

    def upload_thumbs(self, file_id: int, path: str, ext: str):
        from .skills import thumbnails

        with tempfile.TemporaryDirectory() as tmp:
            try:
                pages = thumbnails.render_to(path, ext, Path(tmp))
            except Exception as exc:
                print("  ! Miniatur", path, exc)
                return
            if pages:
                files = [("files", (Path(p["path"]).name, open(p["path"], "rb"), "image/jpeg")) for p in pages]
                labels = json.dumps([p.get("label") for p in pages])
                try:
                    self.http.post(f"/api/agents/{self.computer}/thumbs/{file_id}", files=files,
                                   data={"labels": labels}).raise_for_status()
                finally:
                    for _, (_, fh, _) in files:
                        fh.close()

    # ---------------- inventory ----------------
    def inventory(self):
        from .agents.inventory_agent import (cli_tools, hardware, linux_programs, local_models, mac_programs, python_ai_packages,
                                             windows_programs, _kind_for)

        system = platform.system()
        try:
            progs = windows_programs() if system == "Windows" else mac_programs() if system == "Darwin" else linux_programs()
        except Exception:
            progs = []
        for p in progs:
            p.setdefault("kind", _kind_for(p.get("name") or ""))
        items = [p for p in progs + cli_tools() + python_ai_packages() + local_models() + hardware() if p.get("name")]
        r = self.http.post("/api/agents/inventory", json={"computer_id": self.computer, "items": items}).raise_for_status()
        print("Inventar:", r.json())

    # ---------------- copy ----------------
    def copy(self):
        from .safety import SafetyError, safe_copy

        if not self.target:
            if self.service_mode:
                return  # ohne Cloud-Ordner keine Kopien – Dienst läuft trotzdem weiter
            sys.exit("--target (lokaler Cloud-Ordner) fehlt")
        tasks = self.http.get(f"/api/agents/{self.computer}/copy-tasks").raise_for_status().json()
        print(f"{len(tasks)} Kopieraufgaben")
        for t in tasks:
            try:
                r = safe_copy(t["src"], t["dst"], t.get("sha256"), root=self.target)
                body = {"op_id": t["id"], **{k: r[k] for k in ("status", "dst", "bytes", "verified", "message")}}
            except (SafetyError, OSError) as exc:
                body = {"op_id": t["id"], "status": "fehler", "message": str(exc)}
            self.http.post("/api/agents/copy-result", json=body).raise_for_status()
            print(" ", body["status"], t["src"])


    # ---------------- Dauerbetrieb ----------------
    def scan_due(self, interval_h: float) -> str | None:
        """-> Grund für einen Scan oder None. Server-Anforderung hat Vorrang vor dem eigenen Zeitplan."""
        cfg = self.http.get(f"/api/agents/{self.computer}/config").raise_for_status().json()
        last = self.state.get("last_scan_started")
        req = cfg.get("scan_requested_at")
        if req and (not last or req > last):
            return "angefordert vom Server"
        if interval_h and (not last or datetime.now(timezone.utc) - datetime.fromisoformat(last) >= timedelta(hours=interval_h)):
            return "Zeitplan" if last else "erster Lauf"
        return None

    def service(self, interval_h: float = 24, poll_min: float = 10, once: bool = False):
        """Läuft dauerhaft: Fehler (Server nicht erreichbar, Netzwerk weg) werden protokolliert, dann geht es weiter."""
        self.service_mode = True
        log = logging.getLogger("fdv.agent")
        log.info("Dienst gestartet: Server %s, Computer %s, Einlesen alle %s h", self.server, self.computer, interval_h or "–")
        while True:
            try:
                self.heartbeat()
                why = self.scan_due(interval_h)
                if why:
                    log.info("Einlesen (%s) …", why)
                    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    self.scan()
                    self.inventory()
                    self.state["last_scan_started"] = started
                    self.save_state()
                    log.info("Einlesen fertig")
                self.copy()  # nur Aufgaben, die nach manueller Prüfung freigegeben wurden
            except (httpx.HTTPError, OSError) as exc:
                log.warning("Server nicht erreichbar oder Fehler: %s – neuer Versuch in %s min", exc, poll_min)
            except Exception:
                log.exception("Unerwarteter Fehler – Dienst läuft weiter")
            if once:
                return
            time.sleep(max(poll_min, 0.1) * 60)


def load_config_file(path: str) -> dict:
    p = Path(path).expanduser()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    ap = argparse.ArgumentParser(description="Future Dateiverwaltung – Agent")
    ap.add_argument("--config", help="JSON mit server, computer, key, target, interval_hours (z. B. vom Dienst-Installer)")
    ap.add_argument("--server")
    ap.add_argument("--computer", help="Computer-ID aus der zentralen Konfiguration")
    ap.add_argument("--interval", type=float, default=None, help="service: alle N Stunden einlesen (0 = nur auf Anforderung)")
    ap.add_argument("--once", action="store_true", help="service: nur einen Durchgang (zum Testen)")
    ap.add_argument("--log", help="Protokolldatei (Standard: ~/.fdv-agent.log im Dienstbetrieb)")
    ap.add_argument("--key", default=os.environ.get("FDV_API_KEY", ""))
    ap.add_argument("--target", help="Lokaler Cloud-Sync-Ordner für Schritt 4")
    ap.add_argument("--no-thumbs", action="store_true")
    ap.add_argument("--download-online-only", action="store_true",
                    help="Auch Cloud-Platzhalter (nur online) lesen – löst den Download aus!")
    ap.add_argument("commands", nargs="+", choices=["scan", "inventory", "copy", "watch", "service"])
    a = ap.parse_args()
    cfg = load_config_file(a.config) if a.config else {}
    server, computer = a.server or cfg.get("server"), a.computer or cfg.get("computer")
    if not server or not computer:
        ap.error("--server und --computer angeben (oder --config)")
    key = a.key or cfg.get("key", "")
    target = a.target or cfg.get("target")
    if "service" in a.commands:
        logfile = a.log or cfg.get("log") or str(Path.home() / ".fdv-agent.log")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                            handlers=[logging.FileHandler(logfile, encoding="utf-8"), logging.StreamHandler()])
    agent = Agent(server, computer, key, target, not (a.no_thumbs or cfg.get("no_thumbs")),
                  a.download_online_only or bool(cfg.get("download_online_only")))
    if "service" in a.commands:
        interval = a.interval if a.interval is not None else float(cfg.get("interval_hours", 24))
        agent.service(interval, float(cfg.get("poll_minutes", 10)), once=a.once)
        return
    agent.heartbeat()
    for cmd in a.commands:
        if cmd == "watch":
            while True:
                agent.heartbeat()
                agent.copy()
                time.sleep(600)
        getattr(agent, cmd)()


if __name__ == "__main__":
    main()
