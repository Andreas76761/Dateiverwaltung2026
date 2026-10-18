"""Middleware: Authentifizierung, Lösch-Sperre, Audit-Log, Timing."""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import db
from .config import get_settings

log = logging.getLogger("fdv.http")


class NoDeleteMiddleware(BaseHTTPMiddleware):
    """Harte Sperre: HTTP DELETE ist in der gesamten API deaktiviert."""

    async def dispatch(self, request: Request, call_next):
        if request.method == "DELETE":
            return JSONResponse(
                {"detail": "Löschen ist in Future Dateiverwaltung grundsätzlich deaktiviert. Es werden keine Dateien oder Ordner gelöscht."},
                status_code=405,
            )
        return await call_next(request)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Wenn server.api_key gesetzt ist, benötigt jede /api-Anfrage den Header X-API-Key (oder ?key=)."""

    async def dispatch(self, request: Request, call_next):
        key = get_settings().api_key
        # Ausnahmen: Health-Check und die OAuth-Rückleitung der Cloud (abgesichert über den einmaligen state)
        if key and request.url.path.startswith("/api") and request.url.path not in ("/api/health", "/api/cloud/callback"):
            supplied = request.headers.get("x-api-key") or request.query_params.get("key")
            if supplied != key:
                return JSONResponse({"detail": "Ungültiger oder fehlender API-Key"}, status_code=401)
        return await call_next(request)


class AuditMiddleware(BaseHTTPMiddleware):
    """Protokolliert alle verändernden Anfragen (POST/PUT/PATCH) im Audit-Log und misst Laufzeiten."""

    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
        if request.method in ("POST", "PUT", "PATCH") and request.url.path.startswith("/api"):
            actor = "agent" if request.url.path.startswith("/api/agents") else "nutzer"
            try:
                db.audit(f"{request.method} {request.url.path}", {"status": response.status_code, "ms": round(ms)}, actor)
            except Exception:  # Audit darf nie die Anfrage scheitern lassen
                log.exception("Audit fehlgeschlagen")
        return response
