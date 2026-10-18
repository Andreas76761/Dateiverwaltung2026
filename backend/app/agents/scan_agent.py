"""Schritt 1 – Einlese-Agent: Dateien je Computer / Festplatte / Cloud-Ordner erfassen.

Liest ausschließlich Metadaten (Name, Größe, Datum) und berechnet Prüfsummen für
die Duplikat-Erkennung. Es wird nichts verändert.
"""
from __future__ import annotations

import os
import shutil

from .. import db
from ..config import get_settings
from ..connectors import local
from ..jobs import Job
from ..safety import sha256_file
from ..skills.filetype import detect

BATCH = 500


def upsert_entries(conn, computer_id: str, volume_id: str, entries: list[dict]) -> dict[str, int]:
    """Gemeinsame Ingest-Logik für lokalen Scan und Agent-Push. -> {rel_path: file_id}"""
    ids = {}
    ts = db.now()
    for e in entries:
        ext, ftype, mime = detect(e["name"])
        row = conn.execute(
            "SELECT id, size, mtime FROM files WHERE volume_id=? AND rel_path=?", (volume_id, e["rel_path"])
        ).fetchone()
        if row is None:
            cur = conn.execute(
                """INSERT INTO files(computer_id, volume_id, path, rel_path, name, ext, file_type, mime, size, mtime, ctime,
                   sha256, text_excerpt, page_count, scanned_at, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'eingelesen')""",
                (computer_id, volume_id, e["path"], e["rel_path"], e["name"], ext, ftype, mime, e["size"], e["mtime"],
                 e.get("ctime"), e.get("sha256"), e.get("text_excerpt"), e.get("page_count"), ts),
            )
            ids[e["rel_path"]] = cur.lastrowid
        else:
            changed = row["size"] != e["size"] or row["mtime"] != e["mtime"]
            if changed:
                conn.execute(
                    """UPDATE files SET path=?, size=?, mtime=?, ctime=?, sha256=?, text_excerpt=COALESCE(?, text_excerpt),
                       page_count=COALESCE(?, page_count), status='eingelesen', scanned_at=?, missing=0 WHERE id=?""",
                    (e["path"], e["size"], e["mtime"], e.get("ctime"), e.get("sha256"), e.get("text_excerpt"),
                     e.get("page_count"), ts, row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE files SET scanned_at=?, missing=0, sha256=COALESCE(?, sha256) WHERE id=?",
                    (ts, e.get("sha256"), row["id"]),
                )
            ids[e["rel_path"]] = row["id"]
    return ids


def scan_volume(job: Job, vol: dict, counters: dict) -> None:
    errors: list[str] = []
    batch: list[dict] = []
    started = db.now()

    def flush():
        with db.tx() as c:
            upsert_entries(c, vol["computer_id"], vol["id"], batch)
        batch.clear()

    for entry in local.iter_files(vol["path"], errors):
        if job.cancelled:
            break
        batch.append(entry.__dict__)
        counters["dateien"] += 1
        counters["bytes"] += entry.size
        if len(batch) >= BATCH:
            flush()
            job.update(progress=counters["dateien"], message=f"{vol['name']}: {counters['dateien']} Dateien", **counters)
    if batch:
        flush()

    with db.tx() as c:
        if not job.cancelled:
            # Nicht mehr gefundene Dateien nur markieren – niemals aus der DB oder dem Datenträger löschen
            cur = c.execute("UPDATE files SET missing=1 WHERE volume_id=? AND scanned_at < ?", (vol["id"], started))
            counters["nicht_mehr_gefunden"] += cur.rowcount
        try:
            du = shutil.disk_usage(vol["path"])
            c.execute("UPDATE volumes SET total_bytes=?, free_bytes=?, last_scan=? WHERE id=?",
                      (du.total, du.free, db.now(), vol["id"]))
        except OSError:
            c.execute("UPDATE volumes SET last_scan=? WHERE id=?", (db.now(), vol["id"]))
        c.execute("UPDATE computers SET last_seen=? WHERE id=?", (db.now(), vol["computer_id"]))
    counters["fehler"] += len(errors)
    counters.setdefault("fehlerliste", []).extend(errors[:20])


def compute_duplicates(job: Job | None = None) -> dict:
    """Prüfsummen nur für Dateien gleicher Größe berechnen (schnell), dann Duplikatgruppen bilden."""
    s = get_settings()
    max_bytes = int(s.analysis.get("hash_max_mb", 2048)) * 1024 * 1024
    local_comp = {c["id"] for c in s.computers if c["mode"] == "local"}
    cands = db.query(
        """SELECT id, path, computer_id, size FROM files
           WHERE missing=0 AND size>0 AND sha256 IS NULL AND size IN (
             SELECT size FROM files WHERE missing=0 AND size>0 GROUP BY size HAVING COUNT(*)>1)"""
    )
    hashed = 0
    for i, f in enumerate(cands):
        if job and job.cancelled:
            break
        if f["computer_id"] not in local_comp or f["size"] > max_bytes or not os.path.isfile(f["path"]):
            continue
        try:
            h = sha256_file(f["path"])
        except OSError:
            continue
        with db.tx() as c:
            c.execute("UPDATE files SET sha256=? WHERE id=?", (h, f["id"]))
        hashed += 1
        if job and i % 50 == 0:
            job.update(message=f"Prüfsummen: {i}/{len(cands)}")
    return refresh_dup_groups() | {"prüfsummen_berechnet": hashed}


def refresh_dup_groups() -> dict:
    with db.tx() as c:
        c.execute("UPDATE files SET dup_group=NULL, dup_count=1, is_primary=1")
        groups = c.execute(
            """SELECT sha256, COUNT(*) n, SUM(size) total, MAX(size) sz FROM files
               WHERE sha256 IS NOT NULL AND missing=0 GROUP BY sha256 HAVING n>1"""
        ).fetchall()
        wasted = 0
        for g in groups:
            members = c.execute(
                """SELECT f.id FROM files f JOIN volumes v ON v.id=f.volume_id
                   WHERE f.sha256=? AND f.missing=0
                   ORDER BY f.pinned DESC,
                            CASE WHEN f.name LIKE '%(_)%' OR f.name LIKE '%kopie%' OR f.name LIKE '%copy%' THEN 1 ELSE 0 END,
                            CASE v.kind WHEN 'cloud' THEN 0 WHEN 'internal' THEN 1 ELSE 2 END,
                            f.ctime ASC, length(f.rel_path) ASC""",
                (g["sha256"],),
            ).fetchall()
            ids = [m["id"] for m in members]
            c.execute(
                f"UPDATE files SET dup_group=?, dup_count=?, is_primary=0 WHERE id IN ({','.join('?' * len(ids))})",
                (g["sha256"], len(ids), *ids),
            )
            c.execute("UPDATE files SET is_primary=1 WHERE id=?", (ids[0],))
            wasted += g["total"] - g["sz"]
    rescore_duplicates()
    return {"duplikatgruppen": len(groups), "duplikate_bytes": wasted}


def rescore_duplicates() -> None:
    """Wichtigkeit neu berechnen, nachdem sich Original/Duplikat-Status geändert hat."""
    from ..categories import find_category
    from ..skills import importance

    rows = db.query("SELECT * FROM files WHERE status='analysiert' AND (dup_count>1 OR importance_reason LIKE '%Duplikat%')")
    with db.tx() as c:
        for f in rows:
            labels = {r["label"] for r in c.execute("SELECT label FROM labels WHERE file_id=?", (f["id"],))}
            score, reason = importance.score(find_category(f["category"]), labels, f["file_type"], f["mtime"],
                                             f["dup_count"], bool(f["is_primary"]), None, bool(f["pinned"]))
            c.execute("UPDATE files SET importance=?, importance_reason=? WHERE id=?", (score, reason, f["id"]))


def run(job: Job, params: dict) -> dict:
    s = get_settings()
    wanted = set(params.get("volume_ids") or [])
    vols = []
    for comp in s.computers:
        if comp["mode"] != "local":
            continue
        for v in comp["volumes"]:
            if (not wanted or v["id"] in wanted) and os.path.isdir(v["path"]):
                vols.append({**v, "computer_id": comp["id"]})
    counters = {"dateien": 0, "bytes": 0, "fehler": 0, "nicht_mehr_gefunden": 0, "festplatten": len(vols)}
    for vol in vols:
        if job.cancelled:
            break
        job.update(message=f"Lese {vol['name']} …", **counters)
        scan_volume(job, vol, counters)
    job.update(message="Duplikate werden ermittelt …", **counters)
    counters.update(compute_duplicates(job))
    job.update(progress=counters["dateien"], total=counters["dateien"], message="Einlesen abgeschlossen", **counters)
    return counters
