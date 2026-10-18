"""API: Cloud-Konten über Schnittstelle (OneDrive/Microsoft Graph, Google Drive) verbinden und testen."""
from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import db
from ..config import get_settings
from ..connectors import cloud_api

router = APIRouter(prefix="/api/cloud", tags=["Cloud-Schnittstellen"])


@router.get("/accounts")
def list_accounts():
    cfg = get_settings().raw.get("cloud_api") or {}
    out = []
    for a in cloud_api.accounts():
        st = cloud_api.status(a)
        r = db.one("SELECT COUNT(*) n, COALESCE(SUM(size),0) b, SUM(status='analysiert') an FROM files WHERE volume_id=? AND missing=0",
                   (a.volume_id,))
        v = db.one("SELECT last_scan FROM volumes WHERE id=?", (a.volume_id,))
        out.append({**st, "files": r["n"], "bytes": r["b"], "analyzed": r["an"] or 0, "last_scan": v["last_scan"] if v else None})
    return {"accounts": out, "redirect_uri": cloud_api.redirect_uri(),
            "download_content": bool(cfg.get("download_content")), "download_max_mb": cfg.get("download_max_mb", 25)}


class ConnectIn(BaseModel):
    write: bool = False   # zusätzlich Ordner anlegen + kopieren (für Schritt 4)


@router.post("/{acc_id}/connect")
def connect(acc_id: str, body: ConnectIn):
    try:
        return {"url": cloud_api.auth_url(cloud_api.account(acc_id), body.write)}
    except cloud_api.CloudError as exc:
        raise HTTPException(400, str(exc))


def _page(title: str, text: str, ok: bool) -> HTMLResponse:
    color = "#059669" if ok else "#dc2626"
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>{html.escape(title)}</title>
<body style="font-family:system-ui;background:#f4f6fa;display:grid;place-items:center;height:100vh;margin:0">
<div style="background:white;padding:32px 40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.08);max-width:520px">
<h2 style="color:{color};margin-top:0">{html.escape(title)}</h2><p>{html.escape(text)}</p>
<p style="color:#64748b">Dieses Fenster kann geschlossen werden.</p></div>
<script>setTimeout(()=>{{try{{window.opener&&window.opener.postMessage('fdv-cloud-connected','*');window.close()}}catch(e){{}}}},1500)</script>""")


@router.get("/callback", include_in_schema=False)
def callback(code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None):
    """Rückleitung nach der Anmeldung bei Microsoft/Google (ohne API-Key – abgesichert über den einmaligen state)."""
    if error or not code or not state:
        return _page("Anmeldung abgebrochen", error_description or error or "Kein Code erhalten", False)
    try:
        acc = cloud_api.finish_login(state, code, cloud_api.TRANSPORT)
    except cloud_api.CloudError as exc:
        return _page("Anmeldung fehlgeschlagen", str(exc), False)
    db.audit("cloud.connect", {"account": acc.id, "provider": acc.provider})
    return _page(f"{acc.name} verbunden", "Future Dateiverwaltung darf jetzt die Dateiliste lesen"
                 + (" sowie Ordner anlegen und Dateien kopieren (nie löschen oder verschieben)." if cloud_api.status(acc)["write"] else "."), True)


@router.post("/{acc_id}/disconnect")
def disconnect(acc_id: str):
    cloud_api.account(acc_id)
    cloud_api.save_token(acc_id, None)  # nur das lokal gespeicherte Token – in der Cloud wird nichts verändert
    db.audit("cloud.disconnect", {"account": acc_id})
    return {"ok": True}


@router.post("/{acc_id}/test")
def test(acc_id: str):
    """Verbindung prüfen: die ersten Dateien auflisten (nur lesen)."""
    acc = cloud_api.account(acc_id)
    try:
        items = []
        for e in cloud_api.provider(acc, cloud_api.TRANSPORT).list_files():
            items.append({"name": e["name"], "rel_path": e["rel_path"], "size": e["size"], "mtime": e["mtime"],
                          "hash": "SHA-256" if e.get("sha256") else ("Cloud-Prüfsumme" if e.get("remote_hash") else "–")})
            if len(items) >= 8:
                break
        return {"ok": True, "items": items}
    except cloud_api.CloudError as exc:
        return {"ok": False, "error": str(exc)}
