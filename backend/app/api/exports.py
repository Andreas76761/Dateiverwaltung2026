"""API: Exporte als Excel/CSV und Prüfbericht zum Kopiervorgang (PDF)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from .. import db, exports
from ..safety import SafetyError
from .files import SORTS, _filters

router = APIRouter(prefix="/api/export", tags=["Export"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _name(base: str, ext: str) -> str:
    return f"Future-Dateiverwaltung_{base}_{datetime.now():%Y-%m-%d_%H%M}.{ext}"


def _headers(filename: str) -> dict:
    ascii_name = filename.encode("ascii", "replace").decode().replace("?", "_")
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"}


def _send(sheets: list[exports.Sheet], base: str, fmt: str):
    if fmt == "csv":  # CSV kennt nur eine Tabelle → das Hauptblatt
        return StreamingResponse(exports.to_csv(sheets[0]), media_type="text/csv; charset=utf-8", headers=_headers(_name(base, "csv")))
    if fmt == "xlsx":
        return Response(exports.to_xlsx(sheets, base), media_type=XLSX, headers=_headers(_name(base, "xlsx")))
    raise HTTPException(400, "Format: xlsx | csv")


@router.get("/dateien.{fmt}")
def export_files(
    fmt: str, q: Optional[str] = None, computer: Optional[str] = None, volume: Optional[str] = None, group: Optional[str] = None,
    category: Optional[str] = None, label: Optional[str] = None, file_type: Optional[str] = None, ext: Optional[str] = None,
    review: Optional[str] = None, dup: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    folder: Optional[str] = None, status: Optional[str] = None, min_importance: Optional[int] = None,
    include_missing: bool = False, online: Optional[str] = None, similar: Optional[str] = None,
    sort: str = "importance", order: str = "desc",
):
    """Dateiliste mit denselben Filtern wie im Explorer (ohne Seitenbegrenzung)."""
    where, args = _filters(q, computer, volume, group, category, label, file_type, ext, review, dup, date_from, date_to,
                           folder, status, min_importance, include_missing, online, similar)
    order_sql = f"f.pinned DESC, {SORTS.get(sort, 'f.importance')} {'ASC' if order == 'asc' else 'DESC'}, f.id"
    return _send([exports.files_sheet(where, args, order_sql)], "Dateiliste", fmt)


@router.get("/kopie/{job_id}/pruefbericht.pdf")
def copy_report(job_id: int):
    job = exports.copy_job(job_id)
    if not job:
        raise HTTPException(404, "Kopiervorgang nicht gefunden")
    return Response(exports.report_pdf(job), media_type="application/pdf",
                    headers=_headers(f"Pruefbericht_Kopie_Lauf_{job_id}.pdf"))


@router.post("/kopie/{job_id}/pruefbericht-ablegen")
def copy_report_save(job_id: int):
    """Prüfbericht (PDF + Excel) im Zielordner unter „_Prüfberichte“ ablegen – überschreibt nie."""
    job = exports.copy_job(job_id)
    if not job:
        raise HTTPException(404, "Kopiervorgang nicht gefunden")
    try:
        return {"dateien": exports.save_report_to_target(job)}
    except (SafetyError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/kopie/{job_id}.{fmt}")
def copy_ops(job_id: int, fmt: str):
    if not exports.copy_job(job_id):
        raise HTTPException(404, "Kopiervorgang nicht gefunden")
    return _send([exports.copy_ops_sheet(job_id)], f"Kopierprotokoll_Lauf_{job_id}", fmt)


@router.get("/{kind}.{fmt}")
def export_kind(kind: str, fmt: str, include_duplicates: bool = Query(False)):
    if kind not in exports.EXPORTS:
        raise HTTPException(404, f"Unbekannter Export. Verfügbar: {', '.join(exports.EXPORTS)}, dateien, kopie/<lauf>")
    title, build = exports.EXPORTS[kind]
    db.audit("export", {"art": kind, "format": fmt})
    return _send(build(include_duplicates=include_duplicates), title.replace(" ", "_").replace("&", "und"), fmt)
