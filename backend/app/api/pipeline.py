"""API: Pipeline-Schritte 1–4, Jobs, Vorschlag, Freigabe, Kopie, Statistik."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs
from ..agents import analysis_agent, copy_agent, inventory_agent, organizer_agent, scan_agent, similarity_agent
from ..config import get_settings
from ..llm import costs
from ..safety import sanitize_rel
from ..skills import thumbcache

router = APIRouter(prefix="/api", tags=["Pipeline"])


class ScanIn(BaseModel):
    volume_ids: list[str] = []


class AnalyzeIn(BaseModel):
    force: bool = False
    file_ids: list[int] = []
    confirmed: bool = False             # Kosten bestätigt (bei Cloud-LLM Pflicht)
    mode: Optional[str] = None          # alle | unklare
    batch: Optional[bool] = None        # Anthropic Message Batches
    max_cost_usd: Optional[float] = None


class CopyIn(BaseModel):
    include_duplicates: bool = False
    download_online_only: bool = False  # Nur-online-Dateien herunterladen und kopieren
    skip_older_versions: bool = False   # bei erkannten Versionen nur die neueste kopieren
    dry_run: bool = False
    file_ids: list[int] = []


@router.post("/pipeline/scan")
def start_scan(body: ScanIn):
    return {"job_id": jobs.start("scan", scan_agent.run, body.model_dump())}


def _estimate(body: "AnalyzeIn") -> dict:
    from ..llm import costs

    files, followers, in_batch = analysis_agent.select_files(body.model_dump())
    est = costs.estimate(files, mode=body.mode, batch=body.batch)
    est["duplikate_ohne_kosten"] = len(followers)
    est["in_laufenden_batches"] = len(in_batch)
    if body.max_cost_usd is not None:
        est["limit_usd"] = body.max_cost_usd
    return est


@router.post("/llm/estimate")
def llm_estimate(body: AnalyzeIn):
    """Kostenschätzung für einen Analyse-Lauf mit dem Cloud-LLM (vor dem Start)."""
    return _estimate(body)


@router.post("/pipeline/analyze")
def start_analyze(body: AnalyzeIn):
    s = get_settings()
    if s.llm["provider"] == "anthropic" and not body.confirmed:
        est = _estimate(body)
        if est["an_llm"] and est["kosten_usd"] >= float(s.llm.get("confirm_above_usd", 0) or 0):
            raise HTTPException(409, {"message": "Bitte Kosten bestätigen", "estimate": est})
    params = {k: v for k, v in body.model_dump().items() if v is not None}
    return {"job_id": jobs.start("analyze", analysis_agent.run, params)}


@router.post("/pipeline/propose")
def start_propose():
    return {"job_id": jobs.start("propose", organizer_agent.run, {})}


@router.post("/pipeline/copy")
def start_copy(body: CopyIn):
    n = db.one("SELECT COUNT(*) n FROM files WHERE review_status='freigegeben' AND missing=0")["n"]
    if not n:
        raise HTTPException(400, "Keine freigegebenen Dateien. Bitte zuerst im Vorschlag manuell prüfen und freigeben.")
    return {"job_id": jobs.start("copy", copy_agent.run, body.model_dump())}


class SimilarIn(BaseModel):
    force: bool = False                 # alle Fingerabdrücke neu berechnen


@router.post("/pipeline/similar")
def start_similar(body: SimilarIn):
    """Ähnliche Dateien suchen (läuft auch automatisch am Ende jeder Analyse)."""
    return {"job_id": jobs.start("similar", similarity_agent.run, body.model_dump())}


@router.post("/pipeline/inventory")
def start_inventory():
    return {"job_id": jobs.start("inventory", inventory_agent.run, {})}


def _job(r: dict) -> dict:
    for k in ("params", "stats"):
        r[k] = json.loads(r[k]) if r.get(k) else {}
    return r


@router.get("/jobs")
def list_jobs(kind: Optional[str] = None, limit: int = 30):
    if kind:
        rows = db.query("SELECT * FROM jobs WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))
    else:
        rows = db.query("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
    return [_job(r) for r in rows]


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    r = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not r:
        raise HTTPException(404)
    return _job(r)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    jobs.cancel(job_id)
    return {"ok": True}


# ---------------- Statistik / Dashboard ----------------

@router.get("/stats")
def stats():
    return db.cached("stats", _stats)


def _stats():
    w = "missing=0"
    t = db.one(f"""SELECT COUNT(*) files, COALESCE(SUM(size),0) bytes, SUM(status='analysiert') analyzed,
                   SUM(status='fehler') errors, SUM(dup_count>1 AND is_primary=0) dup_files,
                   COALESCE(SUM(CASE WHEN dup_count>1 AND is_primary=0 THEN size END),0) dup_bytes,
                   SUM(review_status='freigegeben') approved, SUM(review_status='abgelehnt') rejected,
                   SUM(ocr_text IS NOT NULL) ocr, COUNT(DISTINCT dup_group) dup_groups,
                   SUM(online_only) online_only, COALESCE(SUM(CASE WHEN online_only=1 THEN size END),0) online_bytes,
                   COUNT(DISTINCT sim_group) sim_groups, SUM(sim_group IS NOT NULL) sim_files,
                   SUM(sim_kind='Versionen' AND sim_best=0) older_versions,
                   COALESCE(SUM(CASE WHEN sim_kind='Versionen' AND sim_best=0 THEN size END),0) older_bytes
                   FROM files WHERE {w}""")
    return {
        "totals": t,
        "thumbnails": db.one("SELECT COUNT(*) n FROM thumbnails")["n"],
        "labels": db.one("SELECT COUNT(DISTINCT label) n FROM labels")["n"],
        "by_group": db.query(f"SELECT COALESCE(group_name,'(nicht analysiert)') k, COUNT(*) n, SUM(size) bytes FROM files WHERE {w} GROUP BY 1 ORDER BY n DESC"),
        "by_category": db.query(f"SELECT category k, group_name grp, COUNT(*) n, SUM(size) bytes, ROUND(AVG(importance)) imp FROM files WHERE {w} AND category IS NOT NULL GROUP BY 1,2 ORDER BY n DESC"),
        "by_type": db.query(f"SELECT file_type k, COUNT(*) n, SUM(size) bytes FROM files WHERE {w} GROUP BY 1 ORDER BY n DESC"),
        "by_year": db.query(f"SELECT substr(mtime,1,4) k, COUNT(*) n, SUM(size) bytes FROM files WHERE {w} GROUP BY 1 ORDER BY 1"),
        "by_computer": db.query(
            f"""SELECT c.id, c.name, c.os, c.mode, c.last_seen, COUNT(f.id) n, COALESCE(SUM(f.size),0) bytes,
                SUM(f.status='analysiert') analyzed FROM computers c LEFT JOIN files f ON f.computer_id=c.id AND f.{w}
                GROUP BY c.id ORDER BY c.name"""),
        "by_volume": db.query(
            f"""SELECT v.id, v.name, v.kind, v.computer_id, v.path, v.total_bytes, v.free_bytes, v.last_scan,
                COUNT(f.id) n, COALESCE(SUM(f.size),0) bytes FROM volumes v LEFT JOIN files f ON f.volume_id=v.id AND f.{w}
                GROUP BY v.id ORDER BY v.computer_id, v.name"""),
        "similar": db.query(f"SELECT sim_kind k, COUNT(DISTINCT sim_group) groups, COUNT(*) n FROM files WHERE {w} AND sim_group IS NOT NULL GROUP BY 1"),
        "importance": db.query(f"SELECT (importance/10)*10 k, COUNT(*) n FROM files WHERE {w} AND status='analysiert' GROUP BY 1 ORDER BY 1"),
        "top_important": db.query(f"SELECT id, name, category, group_name, importance, computer_id FROM files WHERE {w} AND is_primary=1 ORDER BY importance DESC LIMIT 8"),
        "copies": db.one("SELECT COUNT(*) ops, SUM(status='kopiert') copied, SUM(status='übersprungen') skipped, SUM(status='fehler') errors, SUM(status='geplant') planned, COALESCE(SUM(bytes),0) bytes FROM copy_ops"),
        "target_root": get_settings().target_root,
        "llm_provider": get_settings().llm["provider"],
        "cache": thumbcache.usage(),
        "llm_kosten": costs.totals(),
    }


# ---------------- Schritt 3: Vorschlag ----------------

@router.get("/proposal/tree")
def proposal_tree(include_duplicates: bool = False, status: Optional[str] = None):
    return db.cached(f"ptree:{include_duplicates}:{status}",
                     lambda: organizer_agent.build_tree(only_primary=not include_duplicates, status=status))


@router.get("/proposal/files")
def proposal_files(folder: str = "", include_duplicates: bool = False, recursive: bool = False, limit: int = 500):
    folder = folder.strip("/")
    p = "COALESCE(f.final_path, f.suggested_path)"
    where = ["f.missing=0", "f.suggested_path IS NOT NULL"]
    args: list = []
    if not include_duplicates:
        where.append("f.is_primary=1")
    if folder:
        where.append(f"{p} LIKE ?")
        args.append(folder + "/%")
        if not recursive:
            where.append(f"instr(substr({p}, ?), '/')=0")
            args.append(len(folder) + 2)
    elif not recursive:
        where.append(f"instr({p}, '/')=0")
    rows = db.query(
        f"""SELECT f.id, f.name, f.path, f.computer_id, c.name computer_name, v.name volume_name, f.file_type, f.size, f.mtime,
            f.category, f.group_name, f.importance, f.confidence, f.suggested_path, f.final_path, {p} target, f.review_status,
            f.dup_count, f.is_primary, f.summary, f.sim_kind, f.sim_count, f.sim_best,
            (SELECT COUNT(*) FROM thumbnails t WHERE t.file_id=f.id) thumbs,
            (SELECT group_concat(label, '|') FROM labels l WHERE l.file_id=f.id) labels
            FROM files f JOIN computers c ON c.id=f.computer_id JOIN volumes v ON v.id=f.volume_id
            WHERE {' AND '.join(where)} ORDER BY f.importance DESC LIMIT ?""", [*args, limit])
    for r in rows:
        r["labels"] = sorted(set(r["labels"].split("|"))) if r["labels"] else []
    return rows


class ReviewIn(BaseModel):
    action: str                      # freigeben | ablehnen | zurücksetzen
    file_ids: list[int] = []
    folder: Optional[str] = None     # ganzer vorgeschlagener Ordner (rekursiv)
    include_duplicates: bool = False


ACTIONS = {"freigeben": "freigegeben", "ablehnen": "abgelehnt", "zurücksetzen": "offen"}


@router.post("/review")
def review(body: ReviewIn):
    if body.action not in ACTIONS:
        raise HTTPException(400, "Unbekannte Aktion")
    status = ACTIONS[body.action]
    with db.tx() as c:
        if body.file_ids:
            ids = body.file_ids
            cur = c.execute(f"UPDATE files SET review_status=? WHERE id IN ({','.join('?' * len(ids))})", (status, *ids))
        elif body.folder is not None:
            p = "COALESCE(final_path, suggested_path)"
            extra = "" if body.include_duplicates else " AND is_primary=1"
            folder = body.folder.strip("/")
            if folder:
                cur = c.execute(f"UPDATE files SET review_status=? WHERE missing=0 AND {p} LIKE ?{extra}", (status, folder + "/%"))
            else:
                cur = c.execute(f"UPDATE files SET review_status=? WHERE missing=0 AND suggested_path IS NOT NULL{extra}", (status,))
        else:
            raise HTTPException(400, "file_ids oder folder angeben")
    return {"geändert": cur.rowcount, "status": status}


class MoveIn(BaseModel):
    file_ids: list[int]
    folder: str                      # neuer Zielordner (relativ zu target.root)


@router.post("/proposal/move")
def proposal_move(body: MoveIn):
    """Dateien im VORSCHLAG in einen anderen Zielordner legen (virtuell, keine physische Änderung)."""
    folder = sanitize_rel(body.folder)
    with db.tx() as c:
        for fid in body.file_ids:
            r = c.execute("SELECT name FROM files WHERE id=?", (fid,)).fetchone()
            if r:
                c.execute("UPDATE files SET final_path=? WHERE id=?", (f"{folder}/{r['name']}".strip("/"), fid))
    return {"ok": True, "folder": folder}


class RenameFolderIn(BaseModel):
    old: str
    new: str


@router.post("/proposal/rename-folder")
def proposal_rename_folder(body: RenameFolderIn):
    """Vorgeschlagenen Ordner umbenennen – betrifft nur den Plan, nicht das Dateisystem."""
    old, new = body.old.strip("/"), sanitize_rel(body.new)
    rows = db.query("SELECT id, COALESCE(final_path, suggested_path) p FROM files WHERE COALESCE(final_path, suggested_path) LIKE ?", (old + "/%",))
    with db.tx() as c:
        for r in rows:
            c.execute("UPDATE files SET final_path=? WHERE id=?", (new + r["p"][len(old):], r["id"]))
    return {"geändert": len(rows)}


# ---------------- Schritt 4: Kopien ----------------

@router.get("/copy/ops")
def copy_ops(job_id: Optional[int] = None, status: Optional[str] = None, limit: int = 500):
    where, args = ["1=1"], []
    if job_id:
        where.append("o.job_id=?")
        args.append(job_id)
    if status:
        where.append("o.status=?")
        args.append(status)
    return db.query(f"""SELECT o.*, f.name, f.group_name, f.category FROM copy_ops o JOIN files f ON f.id=o.file_id
                        WHERE {' AND '.join(where)} ORDER BY o.id DESC LIMIT ?""", [*args, limit])


@router.get("/copy/preview")
def copy_preview(include_duplicates: bool = False):
    extra = "" if include_duplicates else " AND is_primary=1"
    t = db.one(f"""SELECT COUNT(*) n, COALESCE(SUM(size),0) bytes, COALESCE(SUM(online_only),0) online_only,
                   COALESCE(SUM(CASE WHEN online_only=1 THEN size END),0) online_bytes FROM files
                   WHERE review_status='freigegeben' AND missing=0{extra}""")
    groups = db.query(f"""SELECT group_name k, COUNT(*) n, COALESCE(SUM(size),0) bytes FROM files
                         WHERE review_status='freigegeben' AND missing=0{extra} GROUP BY 1""")
    by_computer = db.query(f"""SELECT computer_id k, COUNT(*) n, COALESCE(SUM(size),0) bytes FROM files
                         WHERE review_status='freigegeben' AND missing=0{extra} GROUP BY 1""")
    older = db.one(f"""SELECT COUNT(*) n, COALESCE(SUM(size),0) bytes FROM files WHERE review_status='freigegeben' AND missing=0{extra}
                       AND sim_kind='Versionen' AND sim_best=0""")
    return {**t, "by_group": groups, "by_computer": by_computer, "target_root": get_settings().target_root,
            "older_versions": older["n"], "older_bytes": older["bytes"]}
