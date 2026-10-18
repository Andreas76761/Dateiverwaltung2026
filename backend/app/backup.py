"""Datensicherung der App: Datenbank (Freigaben, Labels, Zielpfade, Kopierprotokolle …), Einstellungen und Konfiguration.

- Konsistente Kopie im laufenden Betrieb (SQLite-Backup-Schnittstelle), danach Integritätsprüfung.
- Ablage als ZIP in `<data_dir>/backups` – automatisch täglich, zusätzlich vor Einrichtung und Wiederherstellung.
- Zusätzlich (Standard: wöchentlich) eine Kopie im Zielordner unter `_Sicherung` – liegt damit in der Cloud.
  Dort wird nie etwas überschrieben oder gelöscht.
- Aufgeräumt werden nur ältere *automatische* Sicherungen im eigenen Datenverzeichnis (Anzahl einstellbar).
- Nicht enthalten: Miniaturen/PDF-Cache (lassen sich neu erzeugen) und Cloud-Anmeldedaten (Sicherheit).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from . import db
from .config import get_settings

log = logging.getLogger("fdv.backup")
_lock = threading.Lock()
PREFIX = "fdv-backup-"
DEFAULTS = {"enabled": True, "interval_hours": 24, "keep": 14, "to_target": "wöchentlich"}  # to_target: täglich | wöchentlich | nie


def settings() -> dict:
    s = get_settings()
    return {**DEFAULTS, **(s.raw.get("backup") or {})}


def local_dir() -> Path:
    d = get_settings().data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def target_dir() -> Path:
    return Path(get_settings().target_root) / "_Sicherung"


def _stats(conn: sqlite3.Connection) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]
    try:
        return {"dateien": q("SELECT COUNT(*) FROM files"), "freigegeben": q("SELECT COUNT(*) FROM files WHERE review_status='freigegeben'"),
                "nutzer_labels": q("SELECT COUNT(*) FROM labels WHERE source='nutzer'"),
                "eigene_zielpfade": q("SELECT COUNT(*) FROM files WHERE final_path IS NOT NULL"),
                "kopien": q("SELECT COUNT(*) FROM copy_ops WHERE status='kopiert'")}
    except sqlite3.Error:
        return {}


def create(reason: str = "manuell", to_target: bool | None = None) -> dict:
    """Sicherung anlegen. -> Manifest inkl. Pfad(en)."""
    from .safety import safe_write

    s = get_settings()
    with _lock, tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "fdv.sqlite3"
        src = sqlite3.connect(str(s.db_path), timeout=60)
        dst = sqlite3.connect(str(snap))
        src.backup(dst)  # konsistent, auch während Jobs laufen
        src.close()
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        stats = _stats(dst)
        dst.close()
        if not ok:
            raise RuntimeError("Integritätsprüfung der Sicherung fehlgeschlagen")
        h = hashlib.sha256(snap.read_bytes()).hexdigest()
        now = datetime.now()
        manifest = {"app": "Future Dateiverwaltung", "erstellt": now.isoformat(timespec="seconds"), "grund": reason,
                    "sha256_datenbank": h, "geprüft": ok, "inhalt": stats, "konfiguration": str(s.source),
                    "rechner": __import__("platform").node()}
        name = f"{PREFIX}{now:%Y%m%d-%H%M%S}{'' if reason == 'automatisch' else '-' + _slug(reason)}.zip"
        out = local_dir() / name
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "fdv.sqlite3")
            for extra, arc in ((s.data_dir / "overrides.json", "overrides.json"), (s.source, "konfiguration.yaml")):
                if Path(extra).is_file():
                    z.write(extra, arc)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        manifest.update(datei=str(out), bytes=out.stat().st_size, ort="lokal")
        cfg = settings()
        if to_target is None:
            to_target = _target_due(cfg)
        if to_target and Path(s.target_root).parent.exists():
            try:
                cloud = safe_write(f"_Sicherung/{name}", out.read_bytes())
                manifest["cloud_datei"] = str(cloud)
            except Exception as exc:  # Cloud-Ordner nicht erreichbar → lokale Sicherung reicht
                manifest["cloud_fehler"] = str(exc)
        _rotate(int(cfg.get("keep", 14) or 0))
    db.audit("backup.erstellt", {"datei": name, "grund": reason, "cloud": bool(manifest.get("cloud_datei"))})
    return manifest


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")).strip("-")[:30]


def _target_due(cfg: dict) -> bool:
    mode = cfg.get("to_target", "wöchentlich")
    if mode == "nie":
        return False
    if mode == "täglich":
        return True
    d = target_dir()
    last = max((p.stat().st_mtime for p in d.glob(f"{PREFIX}*.zip")), default=0) if d.is_dir() else 0
    return datetime.now() - datetime.fromtimestamp(last) >= timedelta(days=7)


def _rotate(keep: int) -> None:
    """Nur automatische Sicherungen im eigenen Datenverzeichnis aufräumen – nie im Zielordner/der Cloud."""
    if keep <= 0:
        return
    autos = sorted(p for p in local_dir().glob(f"{PREFIX}*.zip") if p.stem.count("-") == 3)  # ohne Grund-Zusatz = automatisch
    for p in autos[:-keep]:
        p.unlink(missing_ok=True)


def _manifest(p: Path) -> dict:
    try:
        with zipfile.ZipFile(p) as z:
            m = json.loads(z.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        m = {"defekt": True}
    return {**m, "name": p.name, "datei": str(p), "bytes": p.stat().st_size}


def list_backups() -> list[dict]:
    out = [{**_manifest(p), "ort": "lokal"} for p in local_dir().glob(f"{PREFIX}*.zip")]
    if target_dir().is_dir():
        out += [{**_manifest(p), "ort": "Zielordner (Cloud)"} for p in target_dir().glob(f"{PREFIX}*.zip")]
    return sorted(out, key=lambda m: m.get("erstellt", ""), reverse=True)


def resolve(name: str, ort: str = "lokal") -> Path:
    """Nur Dateien aus den beiden Sicherungsordnern – kein beliebiger Pfad."""
    base = local_dir() if ort == "lokal" else target_dir()
    p = (base / Path(name).name)
    if not p.is_file() or not p.name.startswith(PREFIX) or p.suffix != ".zip":
        raise FileNotFoundError("Sicherung nicht gefunden")
    return p


def restore(name: str, ort: str = "lokal", with_settings: bool = True) -> dict:
    """Datenbank (und Einstellungen) aus einer Sicherung zurückholen. Vorher wird der aktuelle Stand gesichert."""
    from . import jobs
    from .api import system

    if jobs._running:
        raise RuntimeError("Während ein Job läuft, kann nicht wiederhergestellt werden")
    p = resolve(name, ort)
    before = create("vor Wiederherstellung", to_target=False)
    s = get_settings()
    with _lock, tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(p) as z:
        z.extract("fdv.sqlite3", tmp)
        snap = Path(tmp) / "fdv.sqlite3"
        m = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {}
        if m.get("sha256_datenbank") and hashlib.sha256(snap.read_bytes()).hexdigest() != m["sha256_datenbank"]:
            raise RuntimeError("Prüfsumme der Sicherung stimmt nicht – Datei beschädigt")
        src = sqlite3.connect(str(snap))
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Sicherung ist beschädigt (Integritätsprüfung)")
        live = sqlite3.connect(str(s.db_path), timeout=60)
        src.backup(live)  # überschreibt nur die eigene App-Datenbank
        live.close()
        src.close()
        if with_settings and "overrides.json" in z.namelist():
            (s.data_dir / "overrides.json").write_bytes(z.read("overrides.json"))
    db.init_db()  # ältere Sicherungen auf den aktuellen Stand der Tabellen bringen
    system.load_overrides()
    db.audit("backup.wiederhergestellt", {"datei": p.name, "vorher_gesichert": Path(before["datei"]).name})
    return {"ok": True, "wiederhergestellt": p.name, "stand": m.get("erstellt"), "vorher_gesichert": before["datei"]}


def last_auto() -> datetime | None:
    times = [datetime.fromtimestamp(p.stat().st_mtime) for p in local_dir().glob(f"{PREFIX}*.zip")]
    return max(times) if times else None


def maybe_auto() -> dict | None:
    """Vom Zeitplan aufgerufen: automatische Sicherung, wenn die letzte älter als das Intervall ist."""
    cfg = settings()
    if not cfg.get("enabled", True):
        return None
    last = last_auto()
    if last and datetime.now() - last < timedelta(hours=float(cfg.get("interval_hours", 24) or 24)):
        return None
    if not get_settings().db_path.exists():
        return None
    try:
        return create("automatisch")
    except Exception:
        log.exception("Automatische Sicherung fehlgeschlagen")
        return None
