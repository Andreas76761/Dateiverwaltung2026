"""Anmeldung: Benutzerkonten, Sitzungen, Rollen, API-Key für Agenten.

Modus (`server.auth` in fdv.yaml):
- auto (Standard): Ohne Benutzerkonto ist die Oberfläche nur auf diesem Computer (localhost) offen – aus dem Netz
  kommt niemand hinein. Sobald ein Konto existiert, gilt die Anmeldung für alle, auch auf diesem Computer.
- an:  immer anmelden. Das erste Konto lässt sich nur auf diesem Computer anlegen.
- aus: keine Anmeldung (nur für reine Testumgebungen).

Rollen: admin (alles) · leser (nur ansehen – keine Freigaben, keine Kopien, keine Einstellungen).
Agenten und Skripte melden sich mit dem API-Key an (Header X-API-Key).

Passwörter: scrypt mit eigenem Salz je Konto. Sitzungen: zufälliges Token im HttpOnly-Cookie (SameSite=Strict,
bei HTTPS zusätzlich Secure); gespeichert wird nur der Hash. Nach 5 Fehlversuchen 10 Minuten Sperre.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from . import db
from .config import get_settings

COOKIE = "fdv_session"
ROLES = ("admin", "leser")
SESSION_HOURS = 12
REMEMBER_DAYS = 30
MAX_FAILS, LOCK_S = 5, 600
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}  # testclient = Starlette-Testclient (kein echter Netzzugriff)
_fails: dict[str, list[float]] = {}
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'admin',
  active INTEGER DEFAULT 1, created_at TEXT, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT, expires_at TEXT,
  ip TEXT, user_agent TEXT);
"""


def init() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def mode() -> str:
    m = str((get_settings().raw.get("server") or {}).get("auth", "auto")).lower()
    return m if m in ("auto", "an", "aus") else "auto"


# ---------------------------------------------------------------- Passwörter

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(h)))
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def check_password_policy(pw: str) -> str | None:
    if len(pw) < 10:
        return "Passwort: mindestens 10 Zeichen"
    if pw.lower() in ("passwort123", "password123", "1234567890", "qwertzuiop"):
        return "Passwort zu einfach"
    return None


# ---------------------------------------------------------------- Konten

def users_exist() -> bool:
    return bool(db.one("SELECT 1 FROM users WHERE active=1"))


def create_user(username: str, password: str, role: str = "admin") -> None:
    username = username.strip().lower()
    if not username or not username.replace(".", "").replace("-", "").replace("_", "").isalnum():
        raise ValueError("Benutzername: Buchstaben, Ziffern, Punkt, Binde- und Unterstrich")
    if role not in ROLES:
        raise ValueError("Rolle: admin | leser")
    if err := check_password_policy(password):
        raise ValueError(err)
    with db.tx() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise ValueError("Benutzername existiert bereits")
        c.execute("INSERT INTO users(username, pw_hash, role, active, created_at) VALUES (?,?,?,1,?)",
                  (username, hash_password(password), role, db.now()))


def update_user(username: str, role: str | None = None, active: bool | None = None, password: str | None = None) -> None:
    u = db.one("SELECT * FROM users WHERE username=?", (username,))
    if not u:
        raise KeyError(username)
    if role is not None and role not in ROLES:
        raise ValueError("Rolle: admin | leser")
    # mindestens ein aktiver Admin muss bleiben
    if (role == "leser" or active is False) and u["role"] == "admin":
        others = db.one("SELECT COUNT(*) n FROM users WHERE role='admin' AND active=1 AND username!=?", (username,))["n"]
        if not others:
            raise ValueError("Mindestens ein aktiver Admin muss bleiben")
    if password is not None and (err := check_password_policy(password)):
        raise ValueError(err)
    with db.tx() as c:
        if role is not None:
            c.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        if active is not None:
            c.execute("UPDATE users SET active=? WHERE username=?", (int(active), username))
        if password is not None:
            c.execute("UPDATE users SET pw_hash=? WHERE username=?", (hash_password(password), username))
        if active is False or password is not None:
            c.execute("DELETE FROM sessions WHERE username=?", (username,))  # nur Sitzungen – erzwingt neue Anmeldung


def list_users() -> list[dict]:
    return db.query("SELECT username, role, active, created_at, last_login FROM users ORDER BY username")


# ---------------------------------------------------------------- Anmeldung

def _throttle_key(ip: str, username: str) -> str:
    return f"{ip}|{username.lower()}"


def locked(ip: str, username: str) -> int:
    with _lock:
        now = time.time()
        k = _throttle_key(ip, username)
        _fails[k] = [t for t in _fails.get(k, []) if now - t < LOCK_S]
        if len(_fails[k]) >= MAX_FAILS:
            return int(LOCK_S - (now - _fails[k][0]))
    return 0


def login(username: str, password: str, ip: str, user_agent: str = "", remember: bool = False) -> str | None:
    """-> Sitzungs-Token oder None."""
    username = username.strip().lower()
    u = db.one("SELECT * FROM users WHERE username=? AND active=1", (username,))
    ok = verify_password(password, u["pw_hash"]) if u else verify_password(password, "scrypt$16384$8$1$00$00")  # gleiche Laufzeit
    if not (u and ok):
        with _lock:
            _fails.setdefault(_throttle_key(ip, username), []).append(time.time())
        db.audit("anmeldung.fehlgeschlagen", {"benutzer": username, "ip": ip}, actor=username or "?")
        return None
    with _lock:
        _fails.pop(_throttle_key(ip, username), None)
    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + (timedelta(days=REMEMBER_DAYS) if remember else timedelta(hours=SESSION_HOURS))
    with db.tx() as c:
        c.execute("INSERT INTO sessions(token_hash, username, created_at, expires_at, ip, user_agent) VALUES (?,?,?,?,?,?)",
                  (_h(token), username, db.now(), exp.isoformat(timespec="seconds"), ip, user_agent[:200]))
        c.execute("UPDATE users SET last_login=? WHERE username=?", (db.now(), username))
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now(),))  # abgelaufene Sitzungen (nur Anmeldedaten)
    db.audit("anmeldung", {"benutzer": username, "ip": ip}, actor=username)
    return token


def logout(token: str | None) -> None:
    if token:
        with db.tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_h(token),))


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    s = db.one("""SELECT u.username, u.role FROM sessions s JOIN users u ON u.username=s.username
                  WHERE s.token_hash=? AND s.expires_at > ? AND u.active=1""", (_h(token), db.now()))
    return s


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- API-Key (Agenten, Skripte)

def _secrets_file():
    return get_settings().data_dir / "secrets.json"


def api_key() -> str:
    """Aus Umgebung/fdv.yaml oder – vom Assistenten erzeugt – aus <data_dir>/secrets.json (nur für den Benutzer lesbar)."""
    s = get_settings()
    if s.api_key:
        return s.api_key
    f = _secrets_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("api_key", "")
        except ValueError:
            return ""
    return ""


def rotate_api_key() -> str:
    key = "fdv_" + secrets.token_urlsafe(30)
    f = _secrets_file()
    data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    data["api_key"] = key
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, f)
    db.audit("api_key.neu", {}, actor="nutzer")
    return key


def key_valid(supplied: str | None) -> bool:
    k = api_key()
    return bool(k and supplied and hmac.compare_digest(supplied, k))


# ---------------------------------------------------------------- Entscheidung je Anfrage

def required(client_host: str) -> bool:
    m = mode()
    if m == "aus":
        return False
    if m == "an" or users_exist():
        return True
    return client_host not in LOOPBACK  # auto, noch kein Konto: nur dieser Computer
