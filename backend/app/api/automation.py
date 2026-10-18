"""API: Automatik (Zeitplan für Einlesen + Analyse) und Änderungsprotokoll."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import db, scheduler
from ..config import get_settings
from .system import _persist_overrides

router = APIRouter(prefix="/api", tags=["Automatik"])


@router.get("/automation")
def automation_status():
    return scheduler.status()


class AutomationIn(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    interval_hours: Optional[float] = None
    time: Optional[str] = None
    weekday: Optional[int] = None
    analyze: Optional[bool] = None
    use_llm: Optional[bool] = None
    max_cost_usd: Optional[float] = None
    inventory: Optional[bool] = None


@router.post("/automation")
def automation_update(body: AutomationIn):
    cfg = get_settings().automation
    upd = body.model_dump(exclude_none=True)
    if upd.get("mode") not in (None, *scheduler.MODES):
        raise HTTPException(400, "mode: intervall | täglich | wöchentlich")
    if "time" in upd:
        try:
            h, m = (int(x) for x in upd["time"].split(":"))
            assert 0 <= h < 24 and 0 <= m < 60
        except (ValueError, AssertionError):
            raise HTTPException(400, "Uhrzeit im Format HH:MM")
        upd["time"] = f"{h:02d}:{m:02d}"
    if upd.get("interval_hours") is not None and not 0.25 <= upd["interval_hours"] <= 24 * 7:
        raise HTTPException(400, "Intervall zwischen 0,25 und 168 Stunden")
    if upd.get("weekday") is not None and not 0 <= upd["weekday"] <= 6:
        raise HTTPException(400, "Wochentag 0 (Mo) … 6 (So)")
    if upd.get("enabled") and not cfg.get("enabled"):
        upd["enabled_since"] = datetime.now().isoformat(timespec="seconds")  # erster Lauf erst zum nächsten Termin
    cfg.update(upd)
    _persist_overrides()
    db.audit("automatik.einstellungen", upd, actor="nutzer")
    return scheduler.status()


@router.post("/automation/run")
def automation_run_now():
    """Einen Durchgang sofort starten (Einlesen → Analyse → Inventar). Kopiert wird nicht."""
    if scheduler._current or scheduler.busy():
        raise HTTPException(409, "Es läuft bereits ein Job – bitte warten")
    threading.Thread(target=scheduler.run_cycle, args=("manuell",), name="automatik-manuell", daemon=True).start()
    return {"ok": True}


@router.get("/changes")
def changes(kind: Optional[str] = None, since: Optional[str] = None, q: Optional[str] = None,
            limit: int = Query(200, ge=1, le=2000)):
    """Änderungsprotokoll: neue, geänderte, nicht mehr gefundene und wieder aufgetauchte Dateien."""
    where, args = ["1=1"], []
    if kind:
        where.append("e.kind=?")
        args.append(kind)
    if since:
        where.append("e.ts>=?")
        args.append(since)
    if q:
        where.append("f.name LIKE ?")
        args.append(f"%{q}%")
    w = " AND ".join(where)
    items = db.query(f"""SELECT e.id, e.ts, e.kind, e.detail, f.id file_id, f.name, f.path, f.file_type, f.ext, f.size,
                         f.status, f.review_status, f.category, f.group_name, f.missing, c.name computer_name, v.name volume_name,
                         (SELECT COUNT(*) FROM thumbnails t WHERE t.file_id=f.id) thumbs
                         FROM file_events e JOIN files f ON f.id=e.file_id
                         JOIN computers c ON c.id=f.computer_id JOIN volumes v ON v.id=f.volume_id
                         WHERE {w} ORDER BY e.id DESC LIMIT ?""", [*args, limit])
    counts = db.query(f"SELECT e.kind k, COUNT(*) n FROM file_events e JOIN files f ON f.id=e.file_id WHERE {w} GROUP BY 1", args)
    return {"items": items, "counts": {r["k"]: r["n"] for r in counts},
            "recheck": db.one("SELECT COUNT(*) n FROM file_events WHERE kind='geändert' AND detail LIKE '%erneut prüfen%'")["n"]}
