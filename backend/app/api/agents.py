"""API für Agenten auf weiteren Computern (Mehrrechner-Betrieb).

Ablauf je Computer (siehe app/agent_client.py):
 1. GET  /api/agents/{id}/config        – welche Festplatten soll ich lesen?
 2. POST /api/agents/ingest             – Datei-Einträge (inkl. Textauszug, Hash) in Batches
 3. POST /api/agents/{id}/thumbs/{fid}  – Miniaturen hochladen
 4. POST /api/agents/inventory          – Programme & LLMs
 5. GET  /api/agents/{id}/copy-tasks    – freigegebene Kopien abholen, lokal in den Cloud-Ordner kopieren
 6. POST /api/agents/copy-result        – Ergebnis zurückmelden
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import db
from ..agents import inventory_agent, scan_agent
from ..config import get_settings

router = APIRouter(prefix="/api/agents", tags=["Agenten"])


class Heartbeat(BaseModel):
    computer_id: str
    hostname: Optional[str] = None
    os: Optional[str] = None
    version: Optional[str] = None
    name: Optional[str] = None


@router.post("/heartbeat")
def heartbeat(hb: Heartbeat):
    with db.tx() as c:
        c.execute("""INSERT INTO computers(id, name, os, hostname, mode, last_seen, agent_version) VALUES (?,?,?,?, 'agent', ?, ?)
                     ON CONFLICT(id) DO UPDATE SET hostname=excluded.hostname, os=COALESCE(excluded.os, computers.os),
                     last_seen=excluded.last_seen, agent_version=excluded.agent_version""",
                  (hb.computer_id, hb.name or hb.computer_id, hb.os, hb.hostname, db.now(), hb.version))
    return {"ok": True}


@router.get("/{computer_id}/config")
def agent_config(computer_id: str):
    s = get_settings()
    comp = next((c for c in s.computers if c["id"] == computer_id), None)
    vols = comp["volumes"] if comp else db.query("SELECT id, name, path, kind FROM volumes WHERE computer_id=?", (computer_id,))
    return {"computer_id": computer_id, "volumes": vols, "exclude_dirs": sorted(s.exclude_dirs),
            "exclude_ext": sorted(s.exclude_ext), "structure": s.target_structure}


class VolumeIn(BaseModel):
    id: str
    name: str
    path: str
    kind: str = "internal"
    total_bytes: Optional[int] = None
    free_bytes: Optional[int] = None


class IngestIn(BaseModel):
    computer_id: str
    volume: VolumeIn
    entries: list[dict]
    final: bool = False
    scan_started: Optional[str] = None


@router.post("/ingest")
def ingest(body: IngestIn):
    v = body.volume
    with db.tx() as c:
        c.execute("""INSERT INTO volumes(id, computer_id, name, path, kind, total_bytes, free_bytes, last_scan) VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name, path=excluded.path, kind=excluded.kind,
                     total_bytes=excluded.total_bytes, free_bytes=excluded.free_bytes, last_scan=excluded.last_scan""",
                  (v.id, body.computer_id, v.name, v.path, v.kind, v.total_bytes, v.free_bytes, db.now()))
        ids = scan_agent.upsert_entries(c, body.computer_id, v.id, body.entries)
        if body.final and body.scan_started:
            c.execute("UPDATE files SET missing=1 WHERE volume_id=? AND scanned_at < ?", (v.id, body.scan_started))
        c.execute("UPDATE computers SET last_seen=? WHERE id=?", (db.now(), body.computer_id))
    if body.final:
        scan_agent.refresh_dup_groups()
    return {"ids": ids}


@router.post("/{computer_id}/thumbs/{file_id}")
async def upload_thumbs(computer_id: str, file_id: int, files: list[UploadFile] = File(...), labels: str = Form("[]")):
    f = db.one("SELECT computer_id FROM files WHERE id=?", (file_id,))
    if not f or f["computer_id"] != computer_id:
        raise HTTPException(404)
    out = get_settings().thumbs_dir / str(file_id)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    lbls = json.loads(labels or "[]")
    for i, up in enumerate(sorted(files, key=lambda u: u.filename or ""), 1):
        p = out / f"p{i:04d}.jpg"
        p.write_bytes(await up.read())
        rows.append((file_id, i, str(p), None, None, lbls[i - 1] if i - 1 < len(lbls) else None))
    with db.tx() as c:
        c.execute("DELETE FROM thumbnails WHERE file_id=?", (file_id,))  # nur Cache-Metadaten
        c.executemany("INSERT INTO thumbnails(file_id, page, path, width, height, label) VALUES (?,?,?,?,?,?)", rows)
    return {"ok": True, "pages": len(rows)}


class InventoryIn(BaseModel):
    computer_id: str
    items: list[dict]


@router.post("/inventory")
def inventory(body: InventoryIn):
    return {"gespeichert": inventory_agent.store(body.computer_id, body.items)}


@router.get("/{computer_id}/copy-tasks")
def copy_tasks(computer_id: str, limit: int = 200):
    return db.query("""SELECT o.id, o.file_id, o.src, o.dst, f.sha256 FROM copy_ops o JOIN files f ON f.id=o.file_id
                       WHERE o.computer_id=? AND o.status='geplant' AND o.message NOT LIKE 'Trockenlauf%' LIMIT ?""",
                    (computer_id, limit))


class CopyResult(BaseModel):
    op_id: int
    status: str
    dst: Optional[str] = None
    bytes: int = 0
    verified: bool = False
    message: str = ""


@router.post("/copy-result")
def copy_result(r: CopyResult):
    if r.status not in ("kopiert", "übersprungen", "fehler"):
        raise HTTPException(400)
    with db.tx() as c:
        c.execute("UPDATE copy_ops SET status=?, dst=COALESCE(?, dst), bytes=?, verified=?, message=?, done_at=? WHERE id=?",
                  (r.status, r.dst, r.bytes, int(r.verified), r.message, db.now(), r.op_id))
    return {"ok": True}
