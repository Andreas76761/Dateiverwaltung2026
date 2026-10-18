"""Einrichtungs-Assistent: Computer, Festplatten, Cloud-Ordner und Zielordner in der Oberfläche festlegen
statt `config/fdv.yaml` von Hand zu bearbeiten.

- Erkennt auf diesem Computer Laufwerke, Benutzerordner und Cloud-Sync-Ordner.
- Prüft Pfade (vorhanden, lesbar, ungefähre Dateizahl, Systemordner, Zielordner in einer Quelle?).
- Schreibt die Konfiguration. Die vorherige Fassung bleibt als `fdv.yaml.<Zeitpunkt>.bak` erhalten.
  Beim Wechsel von den Demo-Daten auf echte Daten wird eine eigene, neue Datenbank verwendet –
  die Demo-Datenbank bleibt unberührt.
- Lädt die Einstellungen ohne Neustart neu.

Liest auf den Laufwerken nur Verzeichnisnamen und Metadaten. Es werden keine Nutzerdateien verändert.
"""
from __future__ import annotations

import copy
import os
import platform
import re
import shutil
import socket
import string
import time
from datetime import datetime
from pathlib import Path

import yaml

from .config import PROJECT_ROOT, get_settings

SYSTEM_DIRS_WIN = ["Windows", "Program Files", "Program Files (x86)", "ProgramData", "$Recycle.Bin", "Recovery",
                   "System Volume Information", "PerfLogs", "AppData"]
SYSTEM_DIRS_MAC = ["System", "Library", "private", "usr", "bin", "sbin", "opt", "cores", "dev", "Volumes"]
SYSTEM_DIRS_LINUX = ["proc", "sys", "dev", "run", "usr", "bin", "sbin", "lib", "lib64", "boot", "etc", "var", "snap", "tmp"]
CLOUD_HINTS = ("onedrive", "google drive", "googledrive", "my drive", "meine ablage", "dropbox", "icloud", "clouddocs",
               "nextcloud", "owncloud", "cloudstorage", "box sync", "pcloud", "megasync")


# ---------------------------------------------------------------- Erkennen

def _usage(p: str) -> tuple[int | None, int | None]:
    try:
        du = shutil.disk_usage(p)
        return du.total, du.free
    except OSError:
        return None, None


def _win_drive_type(root: str) -> str:
    try:
        import ctypes

        t = ctypes.windll.kernel32.GetDriveTypeW(root)  # type: ignore[attr-defined]
        return {2: "external", 3: "internal", 4: "network", 5: "cdrom"}.get(t, "internal")
    except Exception:
        return "internal"


def is_cloud_path(path: str) -> bool:
    low = path.lower().replace("\\", "/")
    return any(h in low for h in CLOUD_HINTS)


def detect() -> dict:
    """Vorschläge für diesen Computer: Laufwerke, Benutzerordner, Cloud-Ordner."""
    from .connectors import cloud

    system = platform.system()
    home = Path.home()
    drives = []
    if system == "Windows":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                kind = _win_drive_type(root)
                if kind == "cdrom":
                    continue
                total, free = _usage(root)
                drives.append({"path": root, "name": f"{letter}: " + ("System" if root.upper().startswith(os.environ.get("SystemDrive", "C:").upper()) else
                                                                     "USB/extern" if kind == "external" else "Netzlaufwerk" if kind == "network" else "Laufwerk"),
                               "kind": "external" if kind == "external" else "internal", "total": total, "free": free,
                               "system": root.upper().startswith(os.environ.get("SystemDrive", "C:").upper())})
    elif system == "Darwin":
        total, free = _usage("/")
        drives.append({"path": "/", "name": "Macintosh HD", "kind": "internal", "total": total, "free": free, "system": True})
        for v in sorted(Path("/Volumes").glob("*")):
            if v.is_dir() and not v.is_symlink():
                total, free = _usage(str(v))
                drives.append({"path": str(v), "name": v.name, "kind": "external", "total": total, "free": free, "system": False})
    else:
        seen = set()
        for p in ["/", str(home), *[str(x) for x in Path("/mnt").glob("*")], *[str(x) for x in Path("/media").glob("*/*")]]:
            if os.path.isdir(p) and p not in seen:
                seen.add(p)
                total, free = _usage(p)
                drives.append({"path": p, "name": "System" if p == "/" else Path(p).name or p,
                               "kind": "external" if p.startswith(("/media", "/mnt")) else "internal",
                               "total": total, "free": free, "system": p == "/"})
    folders = []
    for name, labels in (("Documents", "Dokumente"), ("Desktop", "Schreibtisch"), ("Pictures", "Bilder"), ("Downloads", "Downloads"),
                         ("Videos", "Videos"), ("Movies", "Filme"), ("Music", "Musik")):
        for cand in (home / name, home / labels):
            if cand.is_dir():
                folders.append({"path": str(cand), "name": labels, "kind": "internal"})
                break
    clouds = [{"path": c["path"], "name": f"{c['provider']} (Cloud)", "kind": "cloud", "provider": c["provider"]} for c in cloud.detect()]
    target_suggestions = [str(Path(c["path"]) / "Future-Dateiverwaltung") for c in clouds] or [str(home / "Future-Dateiverwaltung")]
    return {"computer": {"name": platform.node() or "Dieser Computer", "os": f"{platform.system()} {platform.release()}",
                         "user_home": str(home)},
            "drives": drives, "folders": folders, "clouds": clouds, "target_suggestions": target_suggestions,
            "server_url": server_url()}


def server_url() -> str:
    """Adresse, unter der Agenten auf anderen Computern diesen Server erreichen (LAN-IP)."""
    ip = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # sendet nichts – ermittelt nur die ausgehende Schnittstelle
            ip = s.getsockname()[0]
    except OSError:
        pass
    st = get_settings()
    scheme = "https" if (st.raw.get("server") or {}).get("tls") else "http"
    return f"{scheme}://{ip}:{st.port}"


def browse(path: str | None) -> dict:
    """Unterordner zum Auswählen (nur Namen, keine Dateiinhalte)."""
    if not path:
        d = detect()
        return {"path": "", "parent": None, "dirs": [{"name": x["name"], "path": x["path"]} for x in d["drives"] + d["folders"] + d["clouds"]]}
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ValueError(f"Ordner nicht gefunden: {path}")
    dirs = []
    try:
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith((".", "$")):
                        dirs.append({"name": e.name, "path": str(Path(e.path))})
                except OSError:
                    continue
    except PermissionError:
        raise ValueError("Kein Zugriff auf diesen Ordner")
    dirs.sort(key=lambda d: d["name"].lower())
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "parent": parent, "dirs": dirs[:500]}


def check_path(path: str, budget_s: float = 2.5) -> dict:
    """Pfad prüfen: vorhanden, lesbar, ungefähre Dateizahl/Größe (zeitbegrenzt), Hinweise."""
    p = Path(path).expanduser()
    res = {"path": str(p), "exists": p.is_dir(), "readable": False, "files": 0, "bytes": 0, "complete": True, "warnings": []}
    if not res["exists"]:
        res["warnings"].append("Ordner nicht gefunden")
        return res
    res["readable"] = os.access(p, os.R_OK)
    if not res["readable"]:
        res["warnings"].append("Kein Lesezugriff")
        return res
    t0 = time.monotonic()
    stack = [p]
    excl = set(get_settings().exclude_dirs) | set(SYSTEM_DIRS_WIN)
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if time.monotonic() - t0 > budget_s:
                        res["complete"] = False
                        stack = []
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in excl:
                                stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            res["files"] += 1
                            res["bytes"] += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    low = str(p).lower().replace("\\", "/").rstrip("/")
    if re.fullmatch(r"[a-z]:", low) or low in ("", "/"):
        res["warnings"].append("Ganzes Laufwerk: Systemordner (Windows, Programme, AppData …) werden automatisch ausgelassen")
    if any(low.endswith("/" + s.lower()) for s in SYSTEM_DIRS_WIN + SYSTEM_DIRS_MAC):
        res["warnings"].append("Systemordner – enthält meist keine eigenen Dateien")
    tgt = str(Path(get_settings().target_root)).lower().replace("\\", "/").rstrip("/")
    if tgt.startswith(low + "/") or tgt == low:
        res["warnings"].append("Der Zielordner liegt in diesem Ordner – er wird beim Einlesen automatisch übersprungen")
    if is_cloud_path(str(p)):
        res["cloud"] = True
    return res


# ---------------------------------------------------------------- Speichern

def slug(s: str) -> str:
    s = s.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "x"


def is_demo() -> bool:
    s = get_settings()
    return s.source.name == "fdv.example.yaml" or any(
        "/demo/" in str(v["path"]).replace("\\", "/") for c in s.computers for v in c["volumes"])


def current() -> dict:
    s = get_settings()
    return {"config_file": str(s.source), "demo": is_demo(), "target_root": s.target_root, "structure": s.target_structure,
            "computers": [{"id": c["id"], "name": c["name"], "os": c.get("os"), "mode": c["mode"],
                           "volumes": [{"id": v["id"], "name": v["name"], "path": v["path"], "kind": v.get("kind", "internal")}
                                       for v in c["volumes"]]} for c in s.computers],
            "api_key_set": bool(s.api_key)}


def validate(body: dict) -> tuple[dict, list[str]]:
    """Eingaben bereinigen; -> (computers/target für die Konfiguration, Fehler)."""
    errors: list[str] = []
    comps, ids = [], set()
    for c in body.get("computers") or []:
        name = (c.get("name") or "").strip()
        if not name:
            errors.append("Ein Computer hat keinen Namen")
            continue
        cid = c.get("id") or slug(name)
        base, n = cid, 2
        while cid in ids:
            cid, n = f"{base}-{n}", n + 1
        ids.add(cid)
        mode = c.get("mode") if c.get("mode") in ("local", "agent") else "local"
        vols = []
        for v in c.get("volumes") or []:
            path = (v.get("path") or "").strip()
            if not path:
                continue
            vname = (v.get("name") or Path(path).name or path).strip()
            vid = v.get("id") or f"{cid}-{slug(vname)}"
            while vid in ids:
                vid += "-2"
            ids.add(vid)
            if mode == "local" and not Path(path).expanduser().is_dir():
                errors.append(f"{name}: Ordner nicht gefunden – {path}")
            kind = v.get("kind") or ("cloud" if is_cloud_path(path) else "internal")
            vols.append({"id": vid, "name": vname, "path": str(Path(path).expanduser()) if mode == "local" else path, "kind": kind})
        if not vols:
            errors.append(f"{name}: mindestens einen Ordner oder ein Laufwerk auswählen")
        entry = {"id": cid, "name": name, "os": c.get("os") or "", "mode": mode, "volumes": vols}
        comps.append(entry)
    if not comps:
        errors.append("Mindestens einen Computer anlegen")
    target = (body.get("target_root") or "").strip()
    if not target:
        errors.append("Zielordner fehlt")
    else:
        tp = Path(target).expanduser()
        parent = tp if tp.exists() else tp.parent
        if not parent.exists():
            errors.append(f"Zielordner: übergeordneter Ordner nicht gefunden – {parent}")
        elif not os.access(parent, os.W_OK):
            errors.append(f"Zielordner: kein Schreibrecht in {parent}")
        for c in comps:
            for v in c["volumes"]:
                if c["mode"] == "local" and str(tp).lower().rstrip("\\/") == v["path"].lower().rstrip("\\/"):
                    errors.append("Der Zielordner darf nicht selbst ein Quellordner sein")
    return {"computers": comps, "target_root": str(Path(target).expanduser()) if target else "",
            "structure": body.get("structure") or get_settings().target_structure}, errors


def apply(body: dict) -> dict:
    """Konfiguration schreiben (vorherige Fassung bleibt als .bak erhalten) und neu laden."""
    clean, errors = validate(body)
    if errors:
        return {"ok": False, "errors": errors}
    s = get_settings()
    was_demo = is_demo()
    raw = copy.deepcopy(s.raw)
    raw["computers"] = clean["computers"]
    raw.setdefault("target", {})
    raw["target"]["root"] = clean["target_root"]
    raw["target"]["structure"] = clean["structure"]
    scan = raw.setdefault("scan", {})
    excl = list(dict.fromkeys(list(scan.get("exclude_dirs") or []) + SYSTEM_DIRS_WIN + [".Trash", ".Trashes", "node_modules", ".git"]))
    scan["exclude_dirs"] = excl
    server = raw.setdefault("server", {})
    if was_demo and body.get("new_database", True):
        server["data_dir"] = str(s.data_dir.parent / "daten")  # echte Daten in eigener Datenbank – die Demo-Datenbank bleibt erhalten
    dest = Path(os.environ["FDV_CONFIG"]) if os.environ.get("FDV_CONFIG") else PROJECT_ROOT / "config" / "fdv.yaml"
    backup = None
    if dest.exists():
        backup = dest.with_name(f"{dest.name}.{datetime.now():%Y%m%d-%H%M%S}.bak")
        shutil.copy2(dest, backup)
    dest.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Future Dateiverwaltung – geschrieben vom Einrichtungs-Assistenten "
              f"({datetime.now():%d.%m.%Y %H:%M}). Vorherige Fassung: {backup.name if backup else '–'}\n")
    old_overrides = s.data_dir / "overrides.json"
    tmp = dest.with_suffix(".yaml.tmp")
    tmp.write_text(header + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, dest)
    get_settings.cache_clear()
    new_overrides = get_settings().data_dir / "overrides.json"
    if old_overrides.exists() and not new_overrides.exists():  # LLM-, Automatik- und Anzeige-Einstellungen mitnehmen
        shutil.copy2(old_overrides, new_overrides)
    reload(dest)
    return {"ok": True, "config_file": str(dest), "backup": str(backup) if backup else None, "data_dir": str(get_settings().data_dir),
            "new_database": was_demo and body.get("new_database", True)}


def reload(dest: Path | None = None) -> None:
    """Einstellungen neu laden (ohne Neustart) und Computer/Festplatten in die Datenbank übernehmen."""
    from . import db
    from .api import system

    if dest and not os.environ.get("FDV_CONFIG") and dest != PROJECT_ROOT / "config" / "fdv.yaml":
        os.environ["FDV_CONFIG"] = str(dest)
    get_settings.cache_clear()
    db.init_db()
    system.load_overrides()
