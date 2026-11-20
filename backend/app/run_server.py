"""Server-Start für den Dienstbetrieb: Ausgaben in eine Protokolldatei umleiten (unter Windows läuft der
Dienst ohne Konsolenfenster), dann uvicorn starten.

    python -m app.run_server --port 8800 --log ~/fdv-server.log
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=int(os.environ.get("FDV_PORT", 8800)))
    ap.add_argument("--log", help="Protokolldatei (Standard: Konsole)")
    ap.add_argument("--config", help="Pfad zur fdv.yaml (sonst config/fdv.yaml)")
    ap.add_argument("--tls", action="store_true", help="HTTPS (auch per server.tls: true in fdv.yaml)")
    a = ap.parse_args(argv)
    if a.config:
        os.environ["FDV_CONFIG"] = str(Path(a.config).expanduser().resolve())
    if a.log:
        p = Path(a.log).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(p, "a", encoding="utf-8", buffering=1)
    import uvicorn

    from .config import get_settings

    _write_state(a.port, bool(a.tls or (get_settings().raw.get("server") or {}).get("tls")))

    ssl = {}
    if a.tls or (get_settings().raw.get("server") or {}).get("tls"):
        from . import tls
        p = tls.ensure()
        ssl = {"ssl_certfile": str(p["cert"]), "ssl_keyfile": str(p["key"])}
        print(f"HTTPS aktiv · CA-Fingerabdruck {tls.fingerprint()}", flush=True)
    uvicorn.run("app.main:app", host=a.host, port=a.port, log_config=None if a.log else uvicorn.config.LOGGING_CONFIG, **ssl)


def state_file() -> Path:
    from .config import get_settings
    return get_settings().data_dir / "server.json"


def _write_state(port: int, tls: bool) -> None:
    """PID, Port und einen Einmal-Schlüssel ablegen: Damit kann der Starter (Windows-Startmenü „beenden“) den Server
    geordnet beenden – nur von diesem Computer aus und nur mit dem Schlüssel aus der Datei."""
    import atexit
    import json
    import secrets

    token = secrets.token_urlsafe(24)
    os.environ["FDV_SHUTDOWN_TOKEN"] = token
    f = state_file()
    f.write_text(json.dumps({"pid": os.getpid(), "port": port, "tls": tls, "token": token}), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass

    def _cleanup():
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("pid") == os.getpid():
                f.unlink()
        except (OSError, ValueError):
            pass
    atexit.register(_cleanup)


if __name__ == "__main__":
    main()
