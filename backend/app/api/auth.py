"""API: Anmeldung, Benutzerkonten, API-Key, HTTPS-Status."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import auth, tls
from ..config import get_settings
from .system import _persist_overrides

router = APIRouter(prefix="/api/auth", tags=["Anmeldung"])


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _user(request: Request) -> dict:
    return getattr(request.state, "user", None) or {}


def _admin(request: Request) -> None:
    if _user(request).get("role") != "admin":
        raise HTTPException(403, "Nur für Admins")


@router.get("/status")
def status(request: Request):
    """Öffentlich: Muss sich die Oberfläche anmelden? Darf hier das erste Konto angelegt werden?"""
    ip = _ip(request)
    user = auth.session_user(request.cookies.get(auth.COOKIE))
    exists = auth.users_exist()
    return {"mode": auth.mode(), "required": auth.required(ip), "user": user, "users_exist": exists,
            "can_bootstrap": not exists and ip in auth.LOOPBACK, "local": ip in auth.LOOPBACK, "https": request.url.scheme == "https"}


class LoginIn(BaseModel):
    username: str
    password: str
    remember: bool = False


def _set_cookie(resp: JSONResponse, request: Request, token: str, remember: bool) -> JSONResponse:
    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                    max_age=auth.REMEMBER_DAYS * 86400 if remember else None, path="/")
    return resp


@router.post("/login")
def login(body: LoginIn, request: Request):
    ip = _ip(request)
    if wait := auth.locked(ip, body.username):
        raise HTTPException(429, f"Zu viele Fehlversuche – bitte in {wait // 60 + 1} Minuten erneut versuchen")
    token = auth.login(body.username, body.password, ip, request.headers.get("user-agent", ""), body.remember)
    if not token:
        raise HTTPException(401, "Benutzername oder Passwort falsch")
    return _set_cookie(JSONResponse({"ok": True, "user": auth.session_user(token)}), request, token, body.remember)


@router.post("/logout")
def logout(request: Request):
    auth.logout(request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "admin"


@router.post("/bootstrap")
def bootstrap(body: UserIn, request: Request):
    """Erstes Admin-Konto – nur solange es noch keins gibt und nur auf diesem Computer (localhost)."""
    if auth.users_exist():
        raise HTTPException(409, "Es gibt bereits ein Konto – bitte anmelden")
    if _ip(request) not in auth.LOOPBACK:
        raise HTTPException(403, "Das erste Konto lässt sich nur direkt auf dem Server-Computer anlegen (http://localhost:8800)")
    try:
        auth.create_user(body.username, body.password, "admin")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    token = auth.login(body.username, body.password, _ip(request), request.headers.get("user-agent", ""))
    return _set_cookie(JSONResponse({"ok": True, "user": auth.session_user(token)}), request, token, False)


@router.get("/users")
def users(request: Request):
    _admin(request)
    return auth.list_users()


@router.post("/users")
def create_user(body: UserIn, request: Request):
    _admin(request)
    try:
        auth.create_user(body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return auth.list_users()


class UserPatch(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None


@router.post("/users/{username}")
def update_user(username: str, body: UserPatch, request: Request):
    """Rolle ändern, deaktivieren (statt löschen) oder Passwort zurücksetzen."""
    _admin(request)
    try:
        auth.update_user(username, body.role, body.active, body.password)
    except KeyError:
        raise HTTPException(404, "Konto nicht gefunden")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return auth.list_users()


class PasswordIn(BaseModel):
    old: str
    new: str


@router.post("/password")
def change_password(body: PasswordIn, request: Request):
    u = _user(request)
    stored = auth.db.one("SELECT pw_hash FROM users WHERE username=?", (u.get("username"),))
    if not stored or not auth.verify_password(body.old, stored["pw_hash"]):
        raise HTTPException(400, "Bisheriges Passwort stimmt nicht")
    try:
        auth.update_user(u["username"], password=body.new)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.get("/access")
def access(request: Request):
    """Zugang & Sicherheit für die Einstellungen (nur Admin): Modus, API-Key, HTTPS."""
    _admin(request)
    return {"mode": auth.mode(), "api_key": auth.api_key() or None, "tls": tls.info(), "users": auth.list_users()}


class ModeIn(BaseModel):
    mode: str


@router.post("/mode")
def set_mode(body: ModeIn, request: Request):
    _admin(request)
    if body.mode not in ("auto", "an", "aus"):
        raise HTTPException(400, "Modus: auto | an | aus")
    if body.mode == "an" and not auth.users_exist():
        raise HTTPException(400, "Zuerst ein Konto anlegen")
    get_settings().raw.setdefault("server", {})["auth"] = body.mode
    _persist_overrides()
    return {"mode": auth.mode()}


@router.post("/api-key")
def new_api_key(request: Request):
    """Neuen API-Key für Agenten erzeugen (der bisherige wird ungültig)."""
    _admin(request)
    if get_settings().api_key:
        raise HTTPException(409, "Der API-Key ist fest in fdv.yaml bzw. FDV_API_KEY gesetzt – dort ändern")
    return {"api_key": auth.rotate_api_key()}


@router.get("/ca.pem")
def ca_pem():
    """Öffentlich: CA-Zertifikat (kein Geheimnis). Agenten laden es und prüfen es gegen den Fingerabdruck aus der Oberfläche."""
    from fastapi.responses import Response
    p = tls.paths()["ca"]
    if not p.exists():
        raise HTTPException(404, "Kein HTTPS-Zertifikat")
    return Response(p.read_bytes(), media_type="application/x-pem-file")


@router.post("/tls")
def enable_tls(request: Request):
    """HTTPS vorbereiten: Zertifikat erzeugen und server.tls einschalten – wirkt nach dem Neustart des Servers."""
    _admin(request)
    tls.ensure()
    get_settings().raw.setdefault("server", {})["tls"] = True
    _persist_overrides()
    return tls.info()
