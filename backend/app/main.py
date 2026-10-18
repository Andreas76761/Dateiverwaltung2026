"""Future Dateiverwaltung – FastAPI-Server (Backend + ausgeliefertes Frontend)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, jobs, scheduler
from .api import agents, auth as auth_api, automation, cloud, exports, files, pipeline, programs, setup, system
from .config import PROJECT_ROOT, get_settings
from .middleware import AuditMiddleware, AuthMiddleware, NoDeleteMiddleware, SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    from . import auth
    auth.init()
    system.load_overrides()
    stale = jobs.recover_stale()
    s = get_settings()
    _auto_resume(stale)
    scheduler.start()  # Zeitplan (Einlesen + Analyse); kopiert wird nie automatisch
    logging.getLogger("fdv").info("Konfiguration: %s | Ziel: %s | LLM: %s | Automatik: %s", s.source, s.target_root,
                                  s.llm["provider"], "an" if s.automation.get("enabled") else "aus")
    yield
    scheduler.stop()


def _auto_resume(stale: list[dict]) -> None:
    """Unterbrochene Analyse bzw. laufende Anthropic-Batches nach einem Neustart automatisch fortsetzen.
    Bereits analysierte Dateien werden übersprungen – es geht dort weiter, wo der Lauf aufgehört hat."""
    import json

    from .agents import analysis_agent
    from .llm import batch

    if not get_settings().analysis.get("auto_resume", True):
        return
    prev = next((j for j in stale if j["kind"] == "analyze"), None)
    if prev or (get_settings().llm["provider"] == "anthropic" and batch.pending()):
        params = json.loads(prev["params"]) if prev and prev.get("params") else {}
        params.update({"force": False, "fortgesetzt": True})  # nicht erneut alles, nur den Rest
        jobs.start("analyze", analysis_agent.run, params)
        logging.getLogger("fdv").info("Unterbrochene Analyse wird fortgesetzt")


app = FastAPI(title="Future Dateiverwaltung", version="1.0.0", lifespan=lifespan,
              description="Ansicht, Analyse, Eingruppierung und sichere Kopie aller Dateien über mehrere Computer.")

# Reihenfolge: zuletzt hinzugefügt = zuerst ausgeführt
app.add_middleware(AuditMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(NoDeleteMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

for r in (files.router, pipeline.router, system.router, agents.router, cloud.router, automation.router, exports.router, programs.router, setup.router, auth_api.router):
    app.include_router(r)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = FRONTEND_DIST / path
        if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")


def run():
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port)


if __name__ == "__main__":
    run()
