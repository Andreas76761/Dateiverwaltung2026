"""Cloud-Anbindung über die Schnittstellen von Microsoft Graph (OneDrive privat/Business, SharePoint)
und Google Drive – zusätzlich zu den Sync-Ordnern.

Vorteile gegenüber dem Sync-Ordner:
- Einlesen ALLER Cloud-Dateien, auch solcher, die nicht synchronisiert sind – ohne Download.
- Prüfsummen der Cloud (SHA-256 / SHA-1 / MD5) → Duplikate über lokal + Cloud hinweg.
- Deckblatt-Miniatur direkt von der Cloud (ohne die Datei herunterzuladen).
- Schritt 4 als SERVERSEITIGE Kopie innerhalb der Cloud – nichts wird heruntergeladen oder hochgeladen.

Sicherheit (wie im Rest der App): Der HTTP-Client `SafeHTTP` erlaubt technisch nur
GET (lesen), das Anlegen von Ordnern und das Kopieren von Dateien. DELETE, PATCH, PUT sowie jedes
andere POST (Verschieben, Umbenennen, Überschreiben, Papierkorb) werden vor dem Senden abgewiesen.
Kopien nutzen "conflictBehavior=rename" bzw. prüfen vorhandene Namen – es wird nie überschrieben.

Anmeldung: OAuth 2.0 Authorization Code + PKCE mit Rückleitung an den lokalen Server
(…/api/cloud/callback). Die App-Registrierung (Client-ID) legt der Nutzer selbst an – siehe docs/CLOUD-API.md.
Tokens liegen nur lokal in data/cloud_tokens.json (Dateirechte 600).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, urlencode

import httpx

from ..config import get_settings

GRAPH = "https://graph.microsoft.com/v1.0"
DRIVE = "https://www.googleapis.com/drive/v3"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"

SCOPES = {
    "onedrive": {"read": ["offline_access", "User.Read", "Files.Read.All"],
                 "write": ["offline_access", "User.Read", "Files.ReadWrite.All"]},
    "gdrive": {"read": ["https://www.googleapis.com/auth/drive.readonly"],
               "write": ["https://www.googleapis.com/auth/drive"]},
}
# Google-eigene Formate haben keine Endung → für Typ-Erkennung und Export
GOOGLE_NATIVE = {
    "application/vnd.google-apps.document": (".gdoc", "application/pdf"),
    "application/vnd.google-apps.spreadsheet": (".gsheet", "application/pdf"),
    "application/vnd.google-apps.presentation": (".gslides", "application/pdf"),
    "application/vnd.google-apps.drawing": (".gdraw", "image/png"),
}


class CloudError(Exception):
    pass


class CloudSafetyError(CloudError):
    """Ein Aufruf hätte etwas gelöscht, verschoben oder überschrieben – wird nie gesendet."""


class NotConnected(CloudError):
    pass


# ---------------------------------------------------------------- Konten & Tokens

@dataclass
class Account:
    id: str
    provider: str                 # onedrive | gdrive
    name: str
    client_id: str = ""
    client_secret: str = ""       # nur Google ("Desktop-App"-Client); bei Microsoft leer (öffentlicher Client)
    tenant: str = "common"        # Microsoft: consumers | organizations | common | <Tenant-ID>
    root: str = "/"               # nur diesen Ordner im Konto einlesen
    target_folder: str = "Future-Dateiverwaltung"
    max_items: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def volume_id(self) -> str:
        return f"api-{self.id}"


def accounts() -> list[Account]:
    out = []
    for a in (get_settings().raw.get("cloud_api") or {}).get("accounts", []) or []:
        known = {k: v for k, v in a.items() if k in Account.__dataclass_fields__}
        out.append(Account(**{**known, "extra": {k: v for k, v in a.items() if k not in known}}))
    return out


def account(acc_id: str) -> Account:
    for a in accounts():
        if a.id == acc_id:
            return a
    raise CloudError(f"Unbekanntes Cloud-Konto: {acc_id}")


def redirect_uri() -> str:
    s = get_settings()
    return (s.raw.get("cloud_api") or {}).get("redirect_uri") or f"http://localhost:{s.port}/api/cloud/callback"


_tok_lock = threading.Lock()


def _token_file() -> Path:
    return get_settings().data_dir / "cloud_tokens.json"


def load_tokens() -> dict:
    p = _token_file()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_token(acc_id: str, tok: dict | None) -> None:
    with _tok_lock:
        data = load_tokens()
        if tok is None:
            data.pop(acc_id, None)
        else:
            data[acc_id] = tok
        p = _token_file()
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


# ---------------------------------------------------------------- OAuth (Authorization Code + PKCE)

_pending: dict[str, dict] = {}   # state → {account, verifier, write, ts}


def auth_url(acc: Account, write: bool = False) -> str:
    if not acc.client_id:
        raise CloudError(f"Für {acc.name} fehlt die client_id (App-Registrierung, siehe docs/CLOUD-API.md)")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    _pending[state] = {"account": acc.id, "verifier": verifier, "write": write, "ts": time.time()}
    scopes = SCOPES[acc.provider]["write" if write else "read"]
    common = {"client_id": acc.client_id, "response_type": "code", "redirect_uri": redirect_uri(), "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256", "scope": " ".join(scopes)}
    if acc.provider == "onedrive":
        return f"https://login.microsoftonline.com/{acc.tenant}/oauth2/v2.0/authorize?{urlencode({**common, 'response_mode': 'query'})}"
    return f"{GOOGLE_AUTH}?{urlencode({**common, 'access_type': 'offline', 'prompt': 'consent'})}"


def _token_endpoint(acc: Account) -> str:
    return (f"https://login.microsoftonline.com/{acc.tenant}/oauth2/v2.0/token" if acc.provider == "onedrive" else GOOGLE_TOKEN)


def _token_request(acc: Account, data: dict, transport=None) -> dict:
    data = {**data, "client_id": acc.client_id}
    if acc.client_secret:
        data["client_secret"] = acc.client_secret
    with httpx.Client(transport=transport, timeout=30) as c:
        r = c.post(_token_endpoint(acc), data=data)
    if r.status_code != 200:
        raise CloudError(f"Anmeldung fehlgeschlagen ({r.status_code}): {r.text[:300]}")
    tok = r.json()
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    return tok


def finish_login(state: str, code: str, transport=None) -> Account:
    p = _pending.pop(state, None)
    if not p or time.time() - p["ts"] > 900:
        raise CloudError("Anmeldung abgelaufen oder ungültig – bitte erneut verbinden")
    acc = account(p["account"])
    tok = _token_request(acc, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
                                "code_verifier": p["verifier"]}, transport)
    tok["write"] = bool(p["write"])
    tok["connected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_token(acc.id, tok)
    return acc


def access_token(acc: Account, transport=None) -> str:
    tok = load_tokens().get(acc.id)
    if not tok:
        raise NotConnected(f"{acc.name} ist nicht verbunden")
    if time.time() >= tok.get("expires_at", 0):
        if not tok.get("refresh_token"):
            raise NotConnected(f"{acc.name}: Anmeldung abgelaufen – bitte neu verbinden")
        new = _token_request(acc, {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}, transport)
        new.setdefault("refresh_token", tok["refresh_token"])
        new["write"], new["connected_at"] = tok.get("write", False), tok.get("connected_at")
        save_token(acc.id, new)
        tok = new
    return tok["access_token"]


def status(acc: Account) -> dict:
    tok = load_tokens().get(acc.id)
    return {"id": acc.id, "provider": acc.provider, "name": acc.name, "root": acc.root, "target_folder": acc.target_folder,
            "configured": bool(acc.client_id), "connected": bool(tok), "write": bool(tok and tok.get("write")),
            "connected_at": tok.get("connected_at") if tok else None, "volume_id": acc.volume_id}


# ---------------------------------------------------------------- Sicherer HTTP-Client

# Erlaubte schreibende Aufrufe – alles andere wird abgewiesen
_ALLOWED_POST = {
    "onedrive": [re.compile(r"/me/drive/items/[^/]+/copy$"),         # Datei kopieren (neues Objekt)
                 re.compile(r"/me/drive/items/[^/]+/children$")],     # Ordner anlegen
    "gdrive": [re.compile(r"/drive/v3/files/[^/]+/copy$"),           # Datei kopieren
               re.compile(r"/drive/v3/files$")],                      # Ordner anlegen (nur mimeType Ordner)
}


class SafeHTTP:
    """httpx-Client, der nur Lesen, Ordner-Anlegen und Kopieren zulässt."""

    def __init__(self, acc: Account, transport=None):
        self.acc = acc
        self.transport = transport
        self.client = httpx.Client(transport=transport, timeout=60, follow_redirects=True)

    def _headers(self, url: str) -> dict:
        # Monitor-URLs von Graph-Kopien sind vorab signiert und brauchen keinen Token
        if "/monitor/" in url or "api/v2.0/monitor" in url:
            return {}
        return {"Authorization": f"Bearer {access_token(self.acc, self.transport)}"}

    def get(self, url: str, **kw) -> httpx.Response:
        for attempt in range(5):
            r = self.client.get(url, headers=self._headers(url), **kw)
            if r.status_code in (429, 503) and attempt < 4:  # Drosselung durch die Cloud
                time.sleep(min(int(r.headers.get("retry-after", 2 ** attempt)), 30))
                continue
            return r
        return r

    def post(self, url: str, json_body: dict, params: dict | None = None) -> httpx.Response:
        path = httpx.URL(url).path
        if not any(rx.search(path) for rx in _ALLOWED_POST[self.acc.provider]):
            raise CloudSafetyError(f"Nicht erlaubter Schreibzugriff verweigert: POST {path}")
        if self.acc.provider == "gdrive" and path.endswith("/files") and json_body.get("mimeType") != FOLDER_MIME:
            raise CloudSafetyError("Google Drive: Es dürfen nur Ordner angelegt werden")
        if self.acc.provider == "onedrive" and path.endswith("/children") and "folder" not in json_body:
            raise CloudSafetyError("OneDrive: Es dürfen nur Ordner angelegt werden")
        if "conflictBehavior" in json.dumps(json_body) and "replace" in json.dumps(json_body):
            raise CloudSafetyError("Überschreiben ist nicht erlaubt")
        return self.client.post(url, json=json_body, params=params, headers=self._headers(url))

    def __getattr__(self, name):
        if name in ("delete", "patch", "put", "request", "send", "stream"):
            raise CloudSafetyError(f"{name.upper()} ist in Future Dateiverwaltung gesperrt")
        raise AttributeError(name)

    def close(self):
        self.client.close()


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return s


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code == 401:
        raise NotConnected("Anmeldung abgelaufen – bitte das Cloud-Konto neu verbinden")
    if r.status_code >= 400:
        raise CloudError(f"{what}: HTTP {r.status_code} {r.text[:200]}")
    return r.json() if r.content else {}


# ---------------------------------------------------------------- Provider

class Provider:
    def __init__(self, acc: Account, transport=None):
        self.acc = acc
        self.http = SafeHTTP(acc, transport)

    def root_prefix(self) -> str:
        return self.acc.root.strip("/")

    def _in_root(self, rel: str) -> str | None:
        """rel relativ zum Konto → relativ zu acc.root (None = außerhalb)."""
        pre = self.root_prefix()
        if not pre:
            return rel
        if rel == pre or rel.startswith(pre + "/"):
            return rel[len(pre) + 1:]
        return None

    def _excluded(self, rel: str) -> bool:
        tf = self.acc.target_folder.strip("/")
        return bool(tf) and (rel == tf or rel.startswith(tf + "/"))  # eigene Kopien nicht erneut einlesen


class OneDrive(Provider):
    """Microsoft Graph – OneDrive privat, OneDrive for Business, SharePoint-Bibliotheken des Nutzers."""

    def list_files(self) -> Iterator[dict]:
        url = f"{GRAPH}/me/drive/root/delta"
        params = {"$select": "id,name,size,file,folder,parentReference,fileSystemInfo,lastModifiedDateTime,"
                             "createdDateTime,deleted,webUrl,root,package"}
        folders: dict[str, tuple[str, str | None]] = {}  # id → (name, parent_id)
        items: list[dict] = []
        root_id = None
        while url:
            d = _check(self.http.get(url, params=params), "OneDrive-Liste")
            params = None
            for it in d.get("value", []):
                if it.get("deleted"):
                    continue
                if "root" in it:  # Graph-Facette ist ein leeres Objekt {}
                    root_id = it["id"]
                    continue
                parent = (it.get("parentReference") or {}).get("id")
                if "folder" in it or "package" in it:
                    folders[it["id"]] = (it["name"], parent)
                elif "file" in it:
                    items.append(it)
            url = d.get("@odata.nextLink")

        def path_of(pid: str | None) -> str:
            parts = []
            while pid and pid != root_id and pid in folders:
                name, pid = folders[pid]
                parts.append(name)
            return "/".join(reversed(parts))

        for n, it in enumerate(items):
            parent_path = path_of((it.get("parentReference") or {}).get("id"))
            rel = f"{parent_path}/{it['name']}".strip("/")
            rel_root = self._in_root(rel)
            if rel_root is None or self._excluded(rel):
                continue
            hashes = (it.get("file") or {}).get("hashes") or {}
            fsi = it.get("fileSystemInfo") or {}
            yield {"rel_path": rel_root, "name": it["name"], "size": it.get("size") or 0,
                   "mtime": _iso(fsi.get("lastModifiedDateTime") or it.get("lastModifiedDateTime")),
                   "ctime": _iso(fsi.get("createdDateTime") or it.get("createdDateTime")),
                   "remote_id": it["id"], "web_url": it.get("webUrl"),
                   "sha256": (hashes.get("sha256Hash") or "").lower() or None,
                   "remote_hash": hashes.get("quickXorHash") or hashes.get("sha1Hash")}
            if self.acc.max_items and n + 1 >= self.acc.max_items:
                break

    def thumbnail(self, remote_id: str) -> bytes | None:
        r = self.http.get(f"{GRAPH}/me/drive/items/{remote_id}/thumbnails/0/large/content")
        return r.content if r.status_code == 200 and r.content else None

    def download(self, remote_id: str, dest: Path, max_bytes: int) -> Path:
        r = self.http.get(f"{GRAPH}/me/drive/items/{remote_id}/content")
        _check_size(r, max_bytes)
        dest.write_bytes(r.content)
        return dest

    def _item_by_path(self, rel: str) -> dict | None:
        r = self.http.get(f"{GRAPH}/me/drive/root:/{quote(rel)}")
        return None if r.status_code == 404 else _check(r, "OneDrive-Ordner")

    def ensure_folder(self, rel: str) -> str:
        """Ordnerpfad (relativ zum Konto) anlegen, soweit nicht vorhanden. -> Ordner-ID"""
        parent_id = _check(self.http.get(f"{GRAPH}/me/drive/root"), "OneDrive-Stamm")["id"]
        built = ""
        for part in [p for p in rel.split("/") if p]:
            built = f"{built}/{part}".strip("/")
            found = self._item_by_path(built)
            if not found:
                r = self.http.post(f"{GRAPH}/me/drive/items/{parent_id}/children",
                                   {"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
                found = self._item_by_path(built) if r.status_code == 409 else _check(r, "Ordner anlegen")
            parent_id = found["id"]
        return parent_id

    def copy_into(self, remote_id: str, folder_id: str, name: str, sha256: str | None, remote_hash: str | None) -> dict:
        kids = _check(self.http.get(f"{GRAPH}/me/drive/items/{folder_id}/children",
                                    params={"$select": "name,file", "$top": "999"}), "Zielordner")
        for k in kids.get("value", []):
            h = ((k.get("file") or {}).get("hashes") or {})
            if k["name"].lower() == name.lower() and ((sha256 and h.get("sha256Hash", "").lower() == sha256)
                                                      or (remote_hash and remote_hash in (h.get("quickXorHash"), h.get("sha1Hash")))):
                return {"status": "übersprungen", "message": "Identische Datei existiert bereits im Ziel"}
        drive_id = _check(self.http.get(f"{GRAPH}/me/drive", params={"$select": "id"}), "Laufwerk")["id"]
        r = self.http.post(f"{GRAPH}/me/drive/items/{remote_id}/copy",
                           {"parentReference": {"driveId": drive_id, "id": folder_id}, "name": name},
                           params={"@microsoft.graph.conflictBehavior": "rename"})  # Namenskonflikt → "Name 1", nie ersetzen
        if r.status_code not in (200, 201, 202):
            _check(r, "Kopieren")
        monitor = r.headers.get("location")
        for _ in range(30):  # Graph kopiert asynchron – kurz auf den Abschluss warten
            if not monitor:
                break
            m = self.http.get(monitor)
            st = (m.json() if m.content else {}).get("status")
            if st == "completed":
                return {"status": "kopiert", "message": "serverseitig in OneDrive kopiert"}
            if st == "failed":
                return {"status": "fehler", "message": "OneDrive meldet Fehler beim Kopieren"}
            time.sleep(1)
        return {"status": "kopiert", "message": "serverseitige Kopie in OneDrive angestoßen"}


class GoogleDrive(Provider):
    """Google Drive API v3 – „Meine Ablage“ (freigegebene Ablagen optional über root)."""

    FIELDS = "nextPageToken, files(id,name,mimeType,parents,size,modifiedTime,createdTime,md5Checksum,sha256Checksum,webViewLink)"

    def list_files(self) -> Iterator[dict]:
        root_id = _check(self.http.get(f"{DRIVE}/files/root", params={"fields": "id"}), "Drive-Stamm")["id"]
        folders: dict[str, tuple[str, str | None]] = {}
        files: list[dict] = []
        token = None
        while True:
            params = {"q": "trashed = false", "fields": self.FIELDS, "pageSize": "1000", "spaces": "drive"}
            if token:
                params["pageToken"] = token
            d = _check(self.http.get(f"{DRIVE}/files", params=params), "Drive-Liste")
            for f in d.get("files", []):
                parent = (f.get("parents") or [None])[0]
                if f["mimeType"] == FOLDER_MIME:
                    folders[f["id"]] = (f["name"], parent)
                elif f["mimeType"] != "application/vnd.google-apps.shortcut":
                    files.append(f)
            token = d.get("nextPageToken")
            if not token:
                break

        def path_of(pid: str | None) -> str | None:
            parts = []
            while pid and pid != root_id:
                if pid not in folders:
                    return None  # nicht in „Meine Ablage“ (z. B. „Für mich freigegeben“)
                name, pid = folders[pid]
                parts.append(name)
            return "/".join(reversed(parts))

        for n, f in enumerate(files):
            parent_path = path_of((f.get("parents") or [None])[0])
            if parent_path is None:
                continue
            native = GOOGLE_NATIVE.get(f["mimeType"])
            name = f["name"] + (native[0] if native and not f["name"].endswith(native[0]) else "")
            rel = f"{parent_path}/{name}".strip("/")
            rel_root = self._in_root(rel)
            if rel_root is None or self._excluded(rel):
                continue
            yield {"rel_path": rel_root, "name": name, "size": int(f.get("size") or 0),
                   "mtime": _iso(f.get("modifiedTime")), "ctime": _iso(f.get("createdTime")),
                   "remote_id": f["id"], "web_url": f.get("webViewLink"),
                   "sha256": f.get("sha256Checksum") or None, "remote_hash": f.get("md5Checksum")}
            if self.acc.max_items and n + 1 >= self.acc.max_items:
                break

    def thumbnail(self, remote_id: str) -> bytes | None:
        meta = _check(self.http.get(f"{DRIVE}/files/{remote_id}", params={"fields": "thumbnailLink"}), "Miniatur")
        link = meta.get("thumbnailLink")
        if not link:
            return None
        r = self.http.get(re.sub(r"=s\d+$", "=s900", link))  # größere Variante anfordern
        return r.content if r.status_code == 200 and r.content else None

    def download(self, remote_id: str, dest: Path, max_bytes: int) -> Path:
        meta = _check(self.http.get(f"{DRIVE}/files/{remote_id}", params={"fields": "mimeType,size"}), "Datei")
        native = GOOGLE_NATIVE.get(meta.get("mimeType", ""))
        if native:  # Google-Dokumente als PDF/PNG exportieren
            r = self.http.get(f"{DRIVE}/files/{remote_id}/export", params={"mimeType": native[1]})
            dest = dest.with_suffix(".pdf" if native[1] == "application/pdf" else ".png")
        else:
            r = self.http.get(f"{DRIVE}/files/{remote_id}", params={"alt": "media"})
        _check_size(r, max_bytes)
        dest.write_bytes(r.content)
        return dest

    def _child_folder(self, parent: str, name: str) -> str | None:
        q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and '{parent}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
        d = _check(self.http.get(f"{DRIVE}/files", params={"q": q, "fields": "files(id)"}), "Drive-Ordner")
        return d["files"][0]["id"] if d.get("files") else None

    def ensure_folder(self, rel: str) -> str:
        parent = _check(self.http.get(f"{DRIVE}/files/root", params={"fields": "id"}), "Drive-Stamm")["id"]
        for part in [p for p in rel.split("/") if p]:
            found = self._child_folder(parent, part)
            if not found:
                found = _check(self.http.post(f"{DRIVE}/files", {"name": part, "mimeType": FOLDER_MIME, "parents": [parent]},
                                              params={"fields": "id"}), "Ordner anlegen")["id"]
            parent = found
        return parent

    def copy_into(self, remote_id: str, folder_id: str, name: str, sha256: str | None, remote_hash: str | None) -> dict:
        for virt, _ in GOOGLE_NATIVE.values():  # interne Endung (.gdoc …) gehört nicht zum Namen in Drive
            if name.endswith(virt):
                name = name[: -len(virt)]
        q = f"'{folder_id}' in parents and trashed = false"
        d = _check(self.http.get(f"{DRIVE}/files", params={"q": q, "fields": "files(name,md5Checksum,sha256Checksum)", "pageSize": "1000"}),
                   "Zielordner")
        for k in d.get("files", []):
            if k["name"].lower() == name.lower() and ((sha256 and k.get("sha256Checksum") == sha256)
                                                      or (remote_hash and k.get("md5Checksum") == remote_hash)):
                return {"status": "übersprungen", "message": "Identische Datei existiert bereits im Ziel"}
        existing = {k["name"].lower() for k in d.get("files", [])}
        final, i = name, 2
        stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
        while final.lower() in existing:  # Drive erlaubt gleiche Namen – trotzdem eindeutig benennen
            final = f"{stem} ({i}).{ext}" if dot else f"{name} ({i})"
            i += 1
        r = self.http.post(f"{DRIVE}/files/{remote_id}/copy", {"name": final, "parents": [folder_id]}, params={"fields": "id"})
        _check(r, "Kopieren")
        return {"status": "kopiert", "message": "serverseitig in Google Drive kopiert"}


def _check_size(r: httpx.Response, max_bytes: int) -> None:
    if r.status_code >= 400:
        raise CloudError(f"Download: HTTP {r.status_code}")
    if max_bytes and len(r.content) > max_bytes:
        raise CloudError("Datei größer als erlaubt (cloud_api.download_max_mb)")


def provider(acc: Account, transport=None) -> Provider:
    return OneDrive(acc, transport) if acc.provider == "onedrive" else GoogleDrive(acc, transport)


# Test-Hook: nachgebildete Cloud (httpx.MockTransport) statt echter Server
TRANSPORT = None


def provider_for_volume(volume_id: str) -> Provider | None:
    for a in accounts():
        if a.volume_id == volume_id:
            return provider(a, TRANSPORT)
    return None


@contextmanager
def downloaded(f: dict) -> Iterator[tuple[str, str] | None]:
    """Datei für die Inhaltsanalyse vorübergehend herunterladen (nur wenn cloud_api.download_content an ist).
    -> (lokaler Temp-Pfad, Endung) oder None. Die Temp-Datei wird danach entfernt (eigenes Temp-Verzeichnis)."""
    cfg = get_settings().raw.get("cloud_api") or {}
    p = provider_for_volume(f["volume_id"])
    if not p or not cfg.get("download_content") or not f.get("remote_id"):
        yield None
        return
    max_bytes = int(float(cfg.get("download_max_mb", 25)) * 1024 * 1024)
    if f.get("size") and f["size"] > max_bytes:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="fdv-cloud-") as tmp:
        try:
            path = p.download(f["remote_id"], Path(tmp) / f"datei{f.get('ext') or ''}", max_bytes)
        except CloudError:
            yield None
            return
        yield str(path), path.suffix.lower()
