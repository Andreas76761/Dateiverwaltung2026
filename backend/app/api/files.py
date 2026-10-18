"""API: Erweiterter Explorer – Dateien, Filter, Baum, Details, Labels, Miniaturen."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db
from ..categories import find_category
from ..config import get_settings
from ..skills import importance as imp_skill
from ..skills import pathsuggest
from ..skills.labels import guess_year

router = APIRouter(prefix="/api", tags=["Explorer"])

SORTS = {
    "importance": "f.importance", "mtime": "f.mtime", "name": "f.name COLLATE NOCASE", "size": "f.size",
    "type": "f.file_type", "category": "f.category", "computer": "f.computer_id", "ctime": "f.ctime",
}


def _filters(q, computer, volume, group, category, label, file_type, ext, review, dup, date_from, date_to,
             folder, status, min_importance, include_missing, online=None, similar=None):
    where, args = ["1=1"], []
    if not include_missing:
        where.append("f.missing=0")
    if q and db.fts_query(q):
        # Volltextindex (FTS5): Name, Pfad, Zusammenfassung, Inhalt, OCR-Text, Labels – Wortanfänge genügen
        where.append("f.id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)")
        args.append(db.fts_query(q))
    for col, val in (("f.computer_id", computer), ("f.volume_id", volume), ("f.group_name", group),
                     ("f.category", category), ("f.file_type", file_type), ("f.ext", ext),
                     ("f.review_status", review), ("f.status", status)):
        if val:
            vals = val.split(",")
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            args += vals
    if label:
        for l in label.split(","):
            where.append("EXISTS (SELECT 1 FROM labels l WHERE l.file_id=f.id AND l.label=?)")
            args.append(l)
    if dup == "ja":
        where.append("f.dup_count>1")
    elif dup == "nur_kopien":
        where.append("f.dup_count>1 AND f.is_primary=0")
    elif dup == "nein":
        where.append("f.dup_count<=1")
    if date_from:
        where.append("f.mtime>=?")
        args.append(date_from)
    if date_to:
        where.append("f.mtime<=?")
        args.append(date_to + "T23:59:59")
    if folder:
        where.append("(f.rel_path LIKE ? ESCAPE '\\')")
        args.append(folder.replace("%", "\\%").replace("_", "\\_").rstrip("/") + "/%")
    if online == "ja":
        where.append("f.online_only=1")
    elif online == "nein":
        where.append("f.online_only=0")
    if similar == "ja":
        where.append("f.sim_group IS NOT NULL")
    elif similar == "ältere":
        where.append("f.sim_kind='Versionen' AND f.sim_best=0")
    elif similar in ("Versionen", "Formate", "Inhalt", "Fotos"):
        where.append("f.sim_kind=?")
        args.append(similar)
    if min_importance:
        where.append("f.importance>=?")
        args.append(min_importance)
    return " AND ".join(where), args


LIST_COLS = """f.id, f.computer_id, f.volume_id, f.path, f.rel_path, f.name, f.ext, f.file_type, f.size, f.mtime, f.ctime,
  f.page_count, f.summary, f.category, f.group_name, f.confidence, f.importance, f.suggested_path, f.final_path,
  f.review_status, f.dup_count, f.is_primary, f.status, f.pinned, f.missing, f.online_only, f.thumbs_complete, f.web_url,
  f.sim_group, f.sim_count, f.sim_kind, f.sim_best,
  (SELECT group_concat(label, '|') FROM labels l WHERE l.file_id=f.id) labels,
  (SELECT COUNT(*) FROM thumbnails t WHERE t.file_id=f.id) thumbs,
  (SELECT group_concat(COALESCE(t.label, ''), '|') FROM thumbnails t WHERE t.file_id=f.id AND f.file_type IN ('Video', 'E-Mail', 'Audio', 'Archiv', 'Bild')) thumb_labels,
  c.name computer_name, v.name volume_name, v.kind volume_kind"""


def _row(r: dict) -> dict:
    r["labels"] = sorted(set(r["labels"].split("|"))) if r.get("labels") else []
    r["thumb_labels"] = r["thumb_labels"].split("|") if r.get("thumb_labels") else []
    return r


@router.get("/files")
def list_files(
    q: Optional[str] = None, computer: Optional[str] = None, volume: Optional[str] = None, group: Optional[str] = None,
    category: Optional[str] = None, label: Optional[str] = None, file_type: Optional[str] = None, ext: Optional[str] = None,
    review: Optional[str] = None, dup: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    folder: Optional[str] = None, status: Optional[str] = None, min_importance: Optional[int] = None,
    include_missing: bool = False, online: Optional[str] = None, similar: Optional[str] = None,
    sort: str = "importance", order: str = "desc",
    page: int = Query(1, ge=1), limit: int = Query(100, ge=1, le=1000),
):
    where, args = _filters(q, computer, volume, group, category, label, file_type, ext, review, dup, date_from, date_to,
                           folder, status, min_importance, include_missing, online, similar)
    sort_sql = SORTS.get(sort, "f.importance")
    order_sql = "ASC" if order == "asc" else "DESC"
    base = "FROM files f JOIN computers c ON c.id=f.computer_id JOIN volumes v ON v.id=f.volume_id"
    total = db.one(f"SELECT COUNT(*) n, COALESCE(SUM(f.size),0) bytes FROM files f WHERE {where}", args)
    rows = db.query(
        f"SELECT {LIST_COLS} {base} WHERE {where} ORDER BY f.pinned DESC, {sort_sql} {order_sql}, f.id LIMIT ? OFFSET ?",
        [*args, limit, (page - 1) * limit],
    )
    return {"total": total["n"], "bytes": total["bytes"], "page": page, "limit": limit, "items": [_row(r) for r in rows]}


@router.get("/facets")
def facets(group: Optional[str] = None):
    """Zählwerte für die Filterleiste (zwischengespeichert)."""
    return db.cached("facets", _facets)


def _facets():
    w = "missing=0"
    return {
        "groups": db.query(f"SELECT group_name value, COUNT(*) n FROM files WHERE {w} AND group_name IS NOT NULL GROUP BY 1 ORDER BY n DESC"),
        "categories": db.query(f"SELECT category value, group_name grp, COUNT(*) n FROM files WHERE {w} AND category IS NOT NULL GROUP BY 1,2 ORDER BY n DESC"),
        "types": db.query(f"SELECT file_type value, COUNT(*) n FROM files WHERE {w} GROUP BY 1 ORDER BY n DESC"),
        "labels": db.query("SELECT label value, COUNT(*) n FROM labels l JOIN files f ON f.id=l.file_id WHERE f.missing=0 GROUP BY 1 ORDER BY n DESC LIMIT 80"),
        "computers": db.query(f"SELECT computer_id value, COUNT(*) n FROM files WHERE {w} GROUP BY 1"),
        "review": db.query(f"SELECT review_status value, COUNT(*) n FROM files WHERE {w} GROUP BY 1"),
    }


@router.get("/tree")
def tree(volume: str, prefix: str = ""):
    """Ordnerebene eines Volumes für den Explorer-Baum: Unterordner mit Anzahl/Größe.
    Die Gruppierung läuft komplett in SQLite (schnell auch bei Millionen Dateien) und wird zwischengespeichert."""
    return db.cached(f"tree:{volume}:{prefix.strip('/')}", lambda: _tree(volume, prefix.strip("/")), max_age=60)


def _tree(volume: str, prefix: str):
    start = len(prefix) + 2 if prefix else 1
    like = (prefix.replace("%", "\\%").replace("_", "\\_") + "/%") if prefix else "%"
    rows = db.query(
        """SELECT CASE WHEN instr(rest, '/') > 0 THEN substr(rest, 1, instr(rest, '/') - 1) END AS name,
                  COUNT(*) AS count, COALESCE(SUM(size), 0) AS size
           FROM (SELECT substr(rel_path, ?) AS rest, size FROM files
                 WHERE volume_id=? AND missing=0 AND rel_path LIKE ? ESCAPE '\\')
           GROUP BY name""", (start, volume, like))
    folders = [{"name": r["name"], "path": f"{prefix}/{r['name']}".strip("/"), "count": r["count"], "size": r["size"]}
               for r in rows if r["name"] is not None]
    files_here = next((r["count"] for r in rows if r["name"] is None), 0)
    return {"prefix": prefix, "folders": sorted(folders, key=lambda x: x["name"].lower()), "files_here": files_here}


@router.get("/files/{file_id}")
def file_detail(file_id: int):
    f = db.one(f"SELECT {LIST_COLS}, f.text_excerpt, f.ocr_text, f.importance_reason, f.sha256, f.error, f.llm_provider,"
               f" f.analyzed_at, f.scanned_at, f.mime FROM files f JOIN computers c ON c.id=f.computer_id"
               f" JOIN volumes v ON v.id=f.volume_id WHERE f.id=?", (file_id,))
    if not f:
        raise HTTPException(404, "Datei nicht gefunden")
    f = _row(f)
    f["label_details"] = db.query("SELECT label, source FROM labels WHERE file_id=? ORDER BY label", (file_id,))
    f["thumbnails"] = db.query("SELECT page, width, height, label FROM thumbnails WHERE file_id=? ORDER BY page", (file_id,))
    f["duplicates"] = db.query(
        """SELECT f.id, f.path, f.computer_id, c.name computer_name, v.name volume_name, f.mtime, f.is_primary
           FROM files f JOIN computers c ON c.id=f.computer_id JOIN volumes v ON v.id=f.volume_id
           WHERE f.sha256=? AND f.id!=? AND f.missing=0""", (f["sha256"], file_id)) if f.get("sha256") else []
    f["similar"] = similar_of(file_id, f.get("sim_group"))
    f["copies"] = db.query("SELECT * FROM copy_ops WHERE file_id=? ORDER BY id DESC", (file_id,))
    f["target_root"] = get_settings().target_root
    return f


SIM_COLS = """f.id, f.name, f.path, f.ext, f.file_type, f.size, f.mtime, f.computer_id, c.name computer_name, v.name volume_name,
  f.category, f.group_name, f.importance, f.sim_group, f.sim_kind, f.sim_best, f.online_only, f.review_status,
  (SELECT COUNT(*) FROM thumbnails t WHERE t.file_id=f.id) thumbs"""
SIM_KIND_TEXT = {"version": "Version", "format": "Gleicher Inhalt, anderes Format", "inhalt": "Ähnlicher Inhalt", "foto": "Ähnliches Foto"}


def similar_of(file_id: int, group: Optional[int]) -> list[dict]:
    """Andere Mitglieder der Ähnlichkeitsgruppe – mit direkter Ähnlichkeit zu dieser Datei, falls bekannt."""
    if not group:
        return []
    rows = db.query(f"""SELECT {SIM_COLS}, p.kind pair_kind, p.score FROM files f
                        JOIN computers c ON c.id=f.computer_id JOIN volumes v ON v.id=f.volume_id
                        LEFT JOIN similar_pairs p ON (p.a=? AND p.b=f.id) OR (p.b=? AND p.a=f.id)
                        WHERE f.sim_group=? AND f.id!=? AND f.missing=0
                        ORDER BY f.sim_best=1 DESC, f.sim_best DESC, p.score DESC, f.mtime DESC""", (file_id, file_id, group, file_id))
    for r in rows:
        r["pair_text"] = SIM_KIND_TEXT.get(r["pair_kind"] or "", "Über andere Datei der Gruppe verbunden")
    return rows


@router.get("/similar")
def similar_groups(kind: Optional[str] = None, q: Optional[str] = None, page: int = Query(1, ge=1),
                   limit: int = Query(30, ge=1, le=200)):
    """Ähnlichkeitsgruppen (Fotos, Versionen, Formate, Inhalt) – größte Einsparung zuerst."""
    where, args = ["f.missing=0", "f.sim_group IS NOT NULL"], []
    if kind:
        where.append("f.sim_kind=?")
        args.append(kind)
    if q and db.fts_query(q):
        where.append("f.sim_group IN (SELECT sim_group FROM files WHERE id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?))")
        args.append(db.fts_query(q))
    w = " AND ".join(where)
    total = db.one(f"SELECT COUNT(DISTINCT f.sim_group) n FROM files f WHERE {w}", args)["n"]
    groups = db.query(f"""SELECT f.sim_group id, f.sim_kind kind, COUNT(*) n, COALESCE(SUM(f.size),0) bytes,
                          COALESCE(SUM(CASE WHEN f.sim_best=0 THEN f.size END),0) other_bytes, MAX(f.importance) importance
                          FROM files f WHERE {w} GROUP BY f.sim_group, f.sim_kind
                          ORDER BY MAX(f.importance) DESC, n DESC, f.sim_group LIMIT ? OFFSET ?""", [*args, limit, (page - 1) * limit])
    if groups:
        ids = [g["id"] for g in groups]
        members = db.query(f"""SELECT {SIM_COLS} FROM files f JOIN computers c ON c.id=f.computer_id JOIN volumes v ON v.id=f.volume_id
                               WHERE f.missing=0 AND f.sim_group IN ({','.join('?' * len(ids))})
                               ORDER BY f.sim_best=1 DESC, f.sim_best DESC, f.mtime DESC""", ids)
        by_group: dict = {}
        for m in members:
            by_group.setdefault(m["sim_group"], []).append(m)
        scores = {r["g"]: r for r in db.query(
            f"""SELECT f.sim_group g, MIN(p.score) lo, MAX(p.score) hi FROM similar_pairs p JOIN files f ON f.id=p.a
                WHERE f.sim_group IN ({','.join('?' * len(ids))}) GROUP BY 1""", ids)}
        for g in groups:
            g["members"] = by_group.get(g["id"], [])
            g["score_min"], g["score_max"] = (scores[g["id"]]["lo"], scores[g["id"]]["hi"]) if g["id"] in scores else (None, None)
    summary = db.query("""SELECT sim_kind k, COUNT(DISTINCT sim_group) groups, COUNT(*) n,
                          COALESCE(SUM(CASE WHEN sim_best=0 THEN size END),0) other_bytes
                          FROM files WHERE missing=0 AND sim_group IS NOT NULL GROUP BY 1""")
    return {"total": total, "page": page, "limit": limit, "groups": groups, "summary": summary}


@router.get("/files/{file_id}/thumb/{page}")
def thumb(file_id: int, page: int):
    t = db.one("SELECT path FROM thumbnails WHERE file_id=? AND page=?", (file_id, page))
    if not t or not os.path.isfile(t["path"]):
        raise HTTPException(404, "Keine Miniatur")
    return FileResponse(t["path"], media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@router.post("/files/{file_id}/thumbs/ensure")
def ensure_thumbs(file_id: int, download: bool = False):
    """Alle Seiten erzeugen, wenn bisher nur das Deckblatt im Cache liegt (beim Öffnen einer Datei)."""
    from ..skills import thumbcache, thumbnails

    f = db.one("SELECT * FROM files WHERE id=?", (file_id,))
    if not f:
        raise HTTPException(404)
    if f["thumbs_complete"]:
        return {"pages": db.one("SELECT COUNT(*) n FROM thumbnails WHERE file_id=?", (file_id,))["n"], "complete": True}
    local = {c["id"] for c in get_settings().computers if c["mode"] == "local"}
    if f["computer_id"] == "cloud-api":
        from ..connectors import cloud_api
        with cloud_api.downloaded(f) as dl:
            if not dl:
                raise HTTPException(409, "Cloud-Datei: Für alle Seiten muss sie vorübergehend heruntergeladen werden – "
                                         "in den Einstellungen „Cloud-Inhalte laden“ aktivieren")
            r = thumbcache.ensure_all({**f, "path": dl[0], "ext": dl[1] or f["ext"]})
        return {**r, "complete": True}
    if f["computer_id"] not in local:
        raise HTTPException(409, "Datei liegt auf einem Agent-Computer – Seiten erzeugt der Agent beim nächsten Scan")
    if f["online_only"] and not (download or get_settings().cloud.get("download_online_only")):
        raise HTTPException(409, "Nur online: Die Vorschau würde den Download aus der Cloud auslösen")
    if not os.path.isfile(f["path"]) or not thumbnails.supports(f["ext"] or ""):
        raise HTTPException(404, "Keine Vorschau möglich")
    r = thumbcache.ensure_all(f)
    return {**r, "complete": True}


@router.get("/files/{file_id}/raw")
def raw(file_id: int):
    """Original zum Ansehen öffnen (nur lesend, nur Dateien dieses Servers)."""
    f = db.one("SELECT path, mime, name, computer_id, web_url FROM files WHERE id=?", (file_id,))
    if f and f["computer_id"] == "cloud-api" and f["web_url"]:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f["web_url"])  # Cloud-Datei im Browser bei OneDrive/Google öffnen
    local = {c["id"] for c in get_settings().computers if c["mode"] == "local"}
    if not f or f["computer_id"] not in local or not os.path.isfile(f["path"]):
        raise HTTPException(404, "Original auf diesem Server nicht verfügbar")
    return FileResponse(f["path"], media_type=f["mime"], filename=f["name"], content_disposition_type="inline")


class LabelIn(BaseModel):
    label: str


@router.post("/files/{file_id}/labels")
def add_label(file_id: int, body: LabelIn):
    lbl = body.label.strip()[:40]
    if not lbl:
        raise HTTPException(400, "Label leer")
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO labels(file_id, label, source) VALUES (?,?, 'nutzer')", (file_id, lbl))
        db.fts_update(c, file_id)
    _rescore(file_id)
    return {"ok": True}


@router.post("/files/{file_id}/labels/remove")
def remove_label(file_id: int, body: LabelIn):
    # entfernt nur die Metadaten-Zuordnung, keine Datei
    with db.tx() as c:
        c.execute("DELETE FROM labels WHERE file_id=? AND label=?", (file_id, body.label))
        db.fts_update(c, file_id)
    _rescore(file_id)
    return {"ok": True}


class PatchIn(BaseModel):
    category: Optional[str] = None
    final_path: Optional[str] = None
    pinned: Optional[bool] = None
    review_status: Optional[str] = None


@router.post("/files/{file_id}/update")
def update_file(file_id: int, body: PatchIn):
    f = db.one("SELECT * FROM files WHERE id=?", (file_id,))
    if not f:
        raise HTTPException(404)
    from ..safety import sanitize_rel
    with db.tx() as c:
        if body.category:
            cat = find_category(body.category)
            mtime = f["mtime"] or "2000-01-01"
            year = guess_year(f["name"], f["text_excerpt"] or "", int(mtime[:4]))
            sp = pathsuggest.suggest(cat, f["name"], year, int(mtime[5:7]), f["file_type"])
            c.execute("UPDATE files SET category=?, group_name=?, suggested_path=?, confidence=1.0 WHERE id=?",
                      (cat.name, cat.group, sp, file_id))
            c.execute("INSERT OR IGNORE INTO labels(file_id, label, source) VALUES (?, 'manuell geprüft', 'nutzer')", (file_id,))
        if body.final_path is not None:
            c.execute("UPDATE files SET final_path=? WHERE id=?", (sanitize_rel(body.final_path) or None, file_id))
        if body.pinned is not None:
            c.execute("UPDATE files SET pinned=? WHERE id=?", (int(body.pinned), file_id))
        if body.review_status in ("offen", "freigegeben", "abgelehnt"):
            c.execute("UPDATE files SET review_status=? WHERE id=?", (body.review_status, file_id))
    _rescore(file_id)
    return file_detail(file_id)


def _rescore(file_id: int) -> None:
    f = db.one("SELECT * FROM files WHERE id=?", (file_id,))
    if not f or not f["category"]:
        return
    labels = {r["label"] for r in db.query("SELECT label FROM labels WHERE file_id=?", (file_id,))}
    score, reason = imp_skill.score(find_category(f["category"]), labels, f["file_type"], f["mtime"], f["dup_count"],
                                    bool(f["is_primary"]), None, bool(f["pinned"]))
    with db.tx() as c:
        c.execute("UPDATE files SET importance=?, importance_reason=? WHERE id=?", (score, reason, file_id))
