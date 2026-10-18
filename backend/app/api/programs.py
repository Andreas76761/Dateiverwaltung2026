"""API: Programme & LLMs organisieren – Vergleich über alle Computer, Speicherbedarf, Empfehlungen."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from ..agents import software_org

router = APIRouter(prefix="/api/programs", tags=["Programme & LLMs"])


@router.get("/compare")
def compare(kind: Optional[str] = None, q: Optional[str] = None):
    """Matrix: welches Programm / Modell liegt auf welchem Computer – mit Versionen und Größe."""
    return software_org.compare(kind, q)


@router.get("/storage")
def storage():
    return software_org.storage()


@router.get("/recommendations")
def recommendations():
    recs = software_org.recommendations()
    open_ = [r for r in recs if r["status"] == "offen"]
    return {"items": recs, "offen": len(open_), "einsparung": sum(r["saving"] for r in open_)}


class RecStatus(BaseModel):
    status: str                 # offen | erledigt | ignoriert
    note: Optional[str] = None


@router.post("/recommendations/{key}")
def set_recommendation(key: str, body: RecStatus):
    """Empfehlung abhaken oder ignorieren – die App selbst ändert an den Programmen nichts."""
    if body.status not in ("offen", "erledigt", "ignoriert"):
        raise HTTPException(400, "status: offen | erledigt | ignoriert")
    with db.tx() as c:
        c.execute("""INSERT INTO program_recs(key, status, note, updated_at) VALUES (?,?,?,?)
                     ON CONFLICT(key) DO UPDATE SET status=excluded.status, note=excluded.note, updated_at=excluded.updated_at""",
                  (key, body.status, body.note, db.now()))
    return {"ok": True}
