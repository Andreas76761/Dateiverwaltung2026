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

    ssl = {}
    if a.tls or (get_settings().raw.get("server") or {}).get("tls"):
        from . import tls
        p = tls.ensure()
        ssl = {"ssl_certfile": str(p["cert"]), "ssl_keyfile": str(p["key"])}
        print(f"HTTPS aktiv · CA-Fingerabdruck {tls.fingerprint()}", flush=True)
    uvicorn.run("app.main:app", host=a.host, port=a.port, log_config=None if a.log else uvicorn.config.LOGGING_CONFIG, **ssl)


if __name__ == "__main__":
    main()
