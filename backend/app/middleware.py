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


PUBLIC = {"/api/health", "/api/cloud/callback", "/api/auth/status", "/api/auth/login", "/api/auth/bootstrap", "/api/auth/ca.pem"}
READER_POST_OK = {"/api/auth/logout", "/api/auth/password"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Zugang zur API: angemeldete Sitzung (Cookie) oder API-Key (Agenten/Skripte, Header X-API-Key bzw. ?key=).
    Ohne beides nur, wenn keine Anmeldung nötig ist (siehe auth.required). Leser dürfen nichts ändern.
    Schutz vor CSRF: ändernde Anfragen mit Sitzungs-Cookie brauchen den Header X-FDV-Request (setzt nur die eigene Oberfläche)."""

    async def dispatch(self, request: Request, call_next):
        from . import auth

        path = request.url.path
        if not path.startswith("/api") or path in PUBLIC:
            return await call_next(request)
        ip = request.client.host if request.client else ""
        user = auth.session_user(request.cookies.get(auth.COOKIE))
        changing = request.method not in ("GET", "HEAD", "OPTIONS")
        if user:
            if changing and not request.headers.get("x-fdv-request"):
                return JSONResponse({"detail": "Anfrage ohne Kennung der Oberfläche abgelehnt (CSRF-Schutz)"}, status_code=403)
            if changing and user["role"] == "leser" and path not in READER_POST_OK:
                return JSONResponse({"detail": "Nur Lesezugriff – für Änderungen ist ein Admin-Konto nötig"}, status_code=403)
        elif auth.key_valid(request.headers.get("x-api-key") or request.query_params.get("key")):
            user = {"username": "api-key", "role": "admin"}
        elif auth.required(ip):
            return JSONResponse({"detail": "Anmeldung erforderlich", "login": True}, status_code=401)
        else:
            user = {"username": "lokal", "role": "admin"}
        request.state.user = user
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Übliche Schutz-Header; bei HTTPS zusätzlich HSTS."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith("/api/cloud/callback"):
            h.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                                                    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
                                                    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if request.url.scheme == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """Protokolliert alle verändernden Anfragen (POST/PUT/PATCH) im Audit-Log und misst Laufzeiten."""

    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Response-Time-ms"] = f"{ms:.1f}"
        if request.method in ("POST", "PUT", "PATCH") and request.url.path.startswith("/api"):
            u = getattr(request.state, "user", None) or {}
            actor = "agent" if request.url.path.startswith("/api/agents") else u.get("username", "nutzer")
            try:
                db.audit(f"{request.method} {request.url.path}", {"status": response.status_code, "ms": round(ms)}, actor)
            except Exception:  # Audit darf nie die Anfrage scheitern lassen
                log.exception("Audit fehlgeschlagen")
        return response
