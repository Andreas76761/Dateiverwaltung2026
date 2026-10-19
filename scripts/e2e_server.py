"""Server für die Oberflächen-Tests (Playwright): Demo-Daten in einem eigenen, temporären Datenordner
einlesen und analysieren, dann die App starten.

    python scripts/e2e_server.py [--port 8899]

Schreibt nur in den temporären Ordner (Datenbank, Miniaturen, Zielordner) – nie in die Demo-Dateien.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    a = ap.parse_args()
    if not (ROOT / "demo").is_dir():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_demo.py")], check=True)
    work = Path(os.environ.get("FDV_E2E_DIR") or tempfile.mkdtemp(prefix="fdv-e2e-"))
    work.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config" / "fdv.example.yaml").read_text(encoding="utf-8"))
    cfg["server"]["data_dir"] = str(work / "data")
    cfg["target"]["root"] = str(work / "Ziel")
    cfg.setdefault("analysis", {})["ocr"] = False  # schneller; OCR prüfen die Backend-Tests
    (work / "fdv.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    os.environ["FDV_CONFIG"] = str(work / "fdv.yaml")
    os.chdir(ROOT / "backend")

    from app import db, jobs
    from app.agents import analysis_agent, organizer_agent, scan_agent

    db.init_db()

    class J(jobs.Job):
        def __init__(self):
            super().__init__(0, "e2e")

        def update(self, *x, **k):
            pass

    if not db.one("SELECT 1 FROM files WHERE status='analysiert'"):
        print("E2E: Demo-Daten einlesen und analysieren …", flush=True)
        scan_agent.run(J(), {})
        analysis_agent.run(J(), {})
        organizer_agent.run(J(), {})
    print(f"E2E: Server auf http://127.0.0.1:{a.port} (Daten: {work})", flush=True)
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
