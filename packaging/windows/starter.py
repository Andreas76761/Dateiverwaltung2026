"""Starter für das Windows-Installationspaket (wird mit dem mitgelieferten pythonw.exe aufgerufen).

    starter.py               Server starten (falls er nicht schon läuft) und die Oberfläche im Browser öffnen
    starter.py --hintergrund nur den Server starten, ohne Browser
    starter.py --beenden     laufenden Server geordnet beenden
    starter.py --status      Status als Text (für Tests)

Einstellungen und Daten liegen im Benutzerprofil unter %LOCALAPPDATA%\\FutureDateiverwaltung – sie bleiben bei einem
Update und auch beim Deinstallieren erhalten (es wird nie etwas gelöscht).
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

INSTALL = Path(__file__).resolve().parent
BACKEND = INSTALL / "app" / "backend"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FutureDateiverwaltung"
CONFIG = HOME / "fdv.yaml"

FIRST_CONFIG = """# Future Dateiverwaltung – Einstellungen (angelegt beim ersten Start).
# Computer, Festplatten und Zielordner legst du im Einrichtungs-Assistenten der Oberfläche fest.
# Grundprinzip: Es wird nie etwas gelöscht oder verschoben. Geschrieben wird nur in den Zielordner,
# und erst nach deiner Freigabe.
server:
  port: 8800
  data_dir: {data}
llm:
  provider: rules
  mode: unklare
  send_content_to_cloud: false
analysis:
  ocr: true
  ocr_languages: deu+eng
  thumbnails: true
  thumbnails_mode: smart
target:
  root: {target}
  structure: "{{group}}/{{category}}/{{year}}"
  reports: true
computers: []
"""


def ensure_config() -> None:
    if CONFIG.exists():
        return
    HOME.mkdir(parents=True, exist_ok=True)
    onedrive = os.environ.get("OneDrive")
    target = Path(onedrive) / "Future-Dateiverwaltung" if onedrive and Path(onedrive).is_dir() else Path.home() / "Future-Dateiverwaltung"
    q = lambda p: json.dumps(str(p))  # YAML-sicher (Backslashes, Leerzeichen)
    CONFIG.write_text(FIRST_CONFIG.format(data=q(HOME / "daten"), target=q(target)), encoding="utf-8")


def settings() -> dict:
    import yaml
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    srv = raw.get("server") or {}
    data = Path(os.path.expanduser(str(srv.get("data_dir") or HOME / "daten")))
    if not data.is_absolute():
        data = INSTALL / "app" / data
    return {"port": int(srv.get("port", 8800)), "tls": bool(srv.get("tls")), "data": data}


def url(cfg: dict) -> str:
    return f"{'https' if cfg['tls'] else 'http'}://localhost:{cfg['port']}"


def _open(req: urllib.request.Request | str, timeout: float = 2.0):
    ctx = ssl._create_unverified_context()  # nur für localhost; das eigene Zertifikat prüft der Browser
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def running(cfg: dict) -> bool:
    try:
        with _open(url(cfg) + "/api/health") as r:
            return b"Future Dateiverwaltung" in r.read()
    except OSError:
        return False


def start_server(cfg: dict) -> subprocess.Popen:
    log = HOME / "fdv-server.log"
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    return subprocess.Popen([str(PYTHONW if PYTHONW.exists() else sys.executable), "-m", "app.run_server",
                             "--config", str(CONFIG), "--port", str(cfg["port"]), "--log", str(log)],
                            cwd=str(BACKEND), creationflags=flags if os.name == "nt" else 0, close_fds=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def message(text: str, error: bool = False) -> None:
    if os.name == "nt" and Path(sys.executable).name.lower() == "pythonw.exe":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Future Dateiverwaltung", 0x10 if error else 0x40)
    else:
        print(text)


def stop(cfg: dict) -> bool:
    state = cfg["data"] / "server.json"
    if not state.exists() or not running(cfg):
        return False
    info = json.loads(state.read_text(encoding="utf-8"))
    req = urllib.request.Request(url(cfg) + "/api/system/beenden", method="POST", data=b"",
                                 headers={"X-FDV-Shutdown": info.get("token", "")})
    try:
        _open(req, timeout=5).close()
    except OSError:
        return False
    for _ in range(60):
        if not running(cfg):
            return True
        time.sleep(0.5)
    return False


def main(argv: list[str]) -> int:
    ensure_config()
    cfg = settings()
    if "--status" in argv:
        print(json.dumps({"running": running(cfg), "url": url(cfg), "config": str(CONFIG), "data": str(cfg["data"])}))
        return 0
    if "--beenden" in argv:
        ok = stop(cfg)
        if "--still" not in argv:
            message("Future Dateiverwaltung wurde beendet." if ok else "Future Dateiverwaltung läuft gerade nicht.")
        return 0
    if not running(cfg):
        proc = start_server(cfg)
        for _ in range(240):  # erster Start kann dauern (Datenbank anlegen, Virenscanner prüft die Programmdateien)
            if running(cfg):
                break
            if proc.poll() is not None:
                message(f"Der Server konnte nicht starten.\n\nDetails stehen im Protokoll:\n{HOME / 'fdv-server.log'}", error=True)
                return 1
            time.sleep(0.5)
        else:
            message(f"Der Server antwortet nicht.\n\nProtokoll: {HOME / 'fdv-server.log'}", error=True)
            return 1
    if "--hintergrund" not in argv:
        webbrowser.open(url(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
