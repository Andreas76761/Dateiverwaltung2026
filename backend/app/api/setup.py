"""API: Einrichtungs-Assistent und Datensicherung."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import backup, db, setup_wizard
from ..config import get_settings
from .system import _persist_overrides

router = APIRouter(prefix="/api", tags=["Einrichtung"])


@router.get("/setup")
def setup_status():
    """Aktuelle Einrichtung + Vorschläge für diesen Computer."""
    s = get_settings()
    return {**setup_wizard.current(), "detected": setup_wizard.detect(),
            "agent_key": s.api_key or None, "tools": _tools()}


def _tools() -> dict:
    from .. import platform_tools
    from ..skills import formats, ocr, video
    return {"libreoffice": bool(platform_tools.soffice()), "tesseract": ocr.available(), "ffmpeg": video.available(),
            "heic": formats.HEIF_OK, "audio_tags": formats.MUTAGEN_OK, "sevenzip": bool(formats._seven_zip())}


class BrowseIn(BaseModel):
    path: Optional[str] = None


@router.post("/setup/browse")
def setup_browse(body: BrowseIn):
    """Ordner auswählen: Unterordner eines Pfads (nur Namen)."""
    try:
        return setup_wizard.browse(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class CheckIn(BaseModel):
    paths: list[str]


@router.post("/setup/check")
def setup_check(body: CheckIn):
    return [setup_wizard.check_path(p, budget_s=min(2.5, 8 / max(len(body.paths), 1))) for p in body.paths[:20]]


class ApplyIn(BaseModel):
    computers: list[dict]
    target_root: str
    structure: Optional[str] = None
    new_database: bool = True


@router.post("/setup/apply")
def setup_apply(body: ApplyIn):
    """Einrichtung speichern. Vorher werden Datenbank und Konfiguration gesichert."""
    from .. import jobs
    if jobs._running:
        raise HTTPException(409, "Bitte warten, bis laufende Jobs fertig sind")
    clean, errors = setup_wizard.validate(body.model_dump())
    if errors:
        return {"ok": False, "errors": errors}
    try:
        backup.create("vor Einrichtung", to_target=False)
    except Exception as exc:  # Sicherung darf die Einrichtung nicht blockieren, wird aber gemeldet
        pre = str(exc)
    else:
        pre = None
    res = setup_wizard.apply(body.model_dump())
    res["sicherung_fehler"] = pre
    db.audit("einrichtung.gespeichert", {"computer": len(body.computers), "ziel": body.target_root}, actor="nutzer")
    return res


# ---------------------------------------------------------------- Datensicherung

@router.get("/backup")
def backup_list():
    last = backup.last_auto()
    return {"settings": backup.settings(), "items": backup.list_backups(), "local_dir": str(backup.local_dir()),
            "target_dir": str(backup.target_dir()), "last": last.isoformat(timespec="seconds") if last else None}


@router.post("/backup")
def backup_now():
    try:
        return backup.create("manuell", to_target=True)
    except Exception as exc:
        raise HTTPException(500, f"Sicherung fehlgeschlagen: {exc}")


class BackupSettings(BaseModel):
    enabled: Optional[bool] = None
    interval_hours: Optional[float] = None
    keep: Optional[int] = None
    to_target: Optional[str] = None


@router.post("/backup/settings")
def backup_settings(body: BackupSettings):
    upd = body.model_dump(exclude_none=True)
    if upd.get("to_target") not in (None, "täglich", "wöchentlich", "nie"):
        raise HTTPException(400, "to_target: täglich | wöchentlich | nie")
    if upd.get("keep") is not None and not 1 <= upd["keep"] <= 365:
        raise HTTPException(400, "keep: 1 … 365")
    get_settings().raw.setdefault("backup", {}).update(upd)
    _persist_overrides()
    return backup.settings()


class RestoreIn(BaseModel):
    name: str
    ort: str = "lokal"
    with_settings: bool = True


@router.post("/backup/restore")
def backup_restore(body: RestoreIn):
    try:
        return backup.restore(body.name, body.ort, body.with_settings)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.get("/backup/download/{name}")
def backup_download(name: str, ort: str = "lokal"):
    try:
        p = backup.resolve(name, ort)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(p, filename=p.name, media_type="application/zip")
