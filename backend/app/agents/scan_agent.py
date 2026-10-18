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
    existing = {}
    for i in range(0, len(entries), 500):  # vorhandene Einträge blockweise statt einzeln nachschlagen
        part = [e["rel_path"] for e in entries[i:i + 500]]
        for r in conn.execute(f"SELECT id, rel_path, size, mtime, online_only FROM files WHERE volume_id=? AND rel_path IN "
                              f"({','.join('?' * len(part))})", (volume_id, *part)):
            existing[r["rel_path"]] = r
    for e in entries:
        ext, ftype, mime = detect(e["name"])
        online = int(bool(e.get("online_only")))
        row = existing.get(e["rel_path"])
        if row is None:
            cur = conn.execute(
                """INSERT INTO files(computer_id, volume_id, path, rel_path, name, ext, file_type, mime, size, mtime, ctime,
                   sha256, text_excerpt, page_count, scanned_at, status, online_only)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'eingelesen', ?)""",
                (computer_id, volume_id, e["path"], e["rel_path"], e["name"], ext, ftype, mime, e["size"], e["mtime"],
                 e.get("ctime"), e.get("sha256"), e.get("text_excerpt"), e.get("page_count"), ts, online),
            )
            ids[e["rel_path"]] = cur.lastrowid
            db.fts_update(conn, cur.lastrowid)
        else:
            # Geändert – oder inzwischen heruntergeladen (vorher nur online): Inhalt neu analysieren
            changed = row["size"] != e["size"] or row["mtime"] != e["mtime"] or (row["online_only"] and not online)
            if changed:
                conn.execute(
                    """UPDATE files SET path=?, size=?, mtime=?, ctime=?, sha256=?, quick_hash=NULL,
                       text_excerpt=COALESCE(?, text_excerpt), page_count=COALESCE(?, page_count), status='eingelesen',
                       thumbs_complete=0, scanned_at=?, missing=0, online_only=? WHERE id=?""",
                    (e["path"], e["size"], e["mtime"], e.get("ctime"), e.get("sha256"), e.get("text_excerpt"),
                     e.get("page_count"), ts, online, row["id"]),
                )
                db.fts_update(conn, row["id"])
            else:
                conn.execute(
                    "UPDATE files SET path=?, scanned_at=?, missing=0, online_only=?, sha256=COALESCE(?, sha256) WHERE id=?",
                    (e["path"], ts, online, e.get("sha256"), row["id"]),
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

    max_files = get_settings().max_files
    seen, truncated = 0, False
    for entry in local.iter_files(vol["path"], errors):
        if job.cancelled:
            break
        seen += 1
        if max_files and seen > max_files:
            counters["limit_erreicht"] = True
            truncated = True
            break
        batch.append(entry.__dict__)
        counters["dateien"] += 1
        counters["bytes"] += entry.size
        counters["nur_online"] += int(entry.online_only)
        if len(batch) >= BATCH:
            flush()
            job.update(progress=counters["dateien"], message=f"{vol['name']}: {counters['dateien']} Dateien", **counters)
    if batch:
        flush()

    with db.tx() as c:
        if not job.cancelled and not truncated:  # bei Dateilimit nicht vollständig gelesen → nichts als fehlend markieren
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


QUICK_CHUNK = 1024 * 1024


def _save(pending: list[tuple[str, int]], col: str) -> None:
    if pending:
        with db.tx() as c:
            c.executemany(f"UPDATE files SET {col}=? WHERE id=?", pending)
        pending.clear()


def quick_hash(path: str, size: int) -> str:
    """Schnell-Prüfsumme: Größe + erstes und letztes MB. Nur Vorfilter – Duplikate bestätigt erst SHA-256."""
    import hashlib

    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(QUICK_CHUNK))
        if size > 2 * QUICK_CHUNK:
            fh.seek(-QUICK_CHUNK, os.SEEK_END)
            h.update(fh.read(QUICK_CHUNK))
    return h.hexdigest()


def compute_duplicates(job: Job | None = None) -> dict:
    """Duplikate effizient finden – auch bei Millionen Dateien und großen Videos:
    1. nur Dateien mit gleicher Größe kommen in Frage (ohne Lesen),
    2. davon Schnell-Prüfsumme (2 MB lesen),
    3. nur bei gleicher Schnell-Prüfsumme vollständiger SHA-256.
    Cloud-Platzhalter (nur online) werden nie gelesen."""
    s = get_settings()
    max_bytes = int(s.analysis.get("hash_max_mb", 4096)) * 1024 * 1024
    local_comp = {c["id"] for c in s.computers if c["mode"] == "local"}
    allow_online = bool(s.cloud.get("download_online_only"))
    readable = lambda f: (f["computer_id"] in local_comp and (allow_online or not f["online_only"])
                          and os.path.isfile(f["path"]))
    same_size = """SELECT size FROM files WHERE missing=0 AND size>0 GROUP BY size HAVING COUNT(*)>1"""

    # Stufe 2: Schnell-Prüfsumme
    cands = db.query(f"""SELECT id, path, computer_id, size, online_only FROM files
                         WHERE missing=0 AND size>0 AND sha256 IS NULL AND quick_hash IS NULL AND size IN ({same_size})""")
    quick, pending = 0, []
    for i, f in enumerate(cands):
        if job and job.cancelled:
            break
        if not readable(f):
            continue
        try:
            pending.append((quick_hash(f["path"], f["size"]), f["id"]))
        except OSError:
            continue
        quick += 1
        if len(pending) >= 500:
            _save(pending, "quick_hash")
        if job and i % 200 == 0:
            job.update(message=f"Schnell-Prüfsummen: {i}/{len(cands)}")
    _save(pending, "quick_hash")

    # Stufe 3: SHA-256 nur, wo Größe UND Schnell-Prüfsumme übereinstimmen (oder Gegenstück schon SHA hat, z. B. vom Agenten)
    cands = db.query(
        """SELECT f.id, f.path, f.computer_id, f.size, f.online_only FROM files f
           WHERE f.missing=0 AND f.size>0 AND f.sha256 IS NULL AND (
             f.quick_hash IN (SELECT quick_hash FROM files WHERE quick_hash IS NOT NULL AND missing=0
                              GROUP BY quick_hash HAVING COUNT(*)>1)
             OR f.size IN (SELECT size FROM files WHERE sha256 IS NOT NULL AND missing=0))""")
    hashed, pending = 0, []
    for i, f in enumerate(cands):
        if job and job.cancelled:
            break
        if f["size"] > max_bytes or not readable(f):
            continue
        try:
            pending.append((sha256_file(f["path"]), f["id"]))
        except OSError:
            continue
        hashed += 1
        if len(pending) >= 200:
            _save(pending, "sha256")
        if job and i % 50 == 0:
            job.update(message=f"Prüfsummen: {i}/{len(cands)}")
    _save(pending, "sha256")
    return refresh_dup_groups() | {"schnellprüfsummen": quick, "prüfsummen_berechnet": hashed}


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
    counters = {"dateien": 0, "bytes": 0, "fehler": 0, "nicht_mehr_gefunden": 0, "nur_online": 0, "festplatten": len(vols)}
    for vol in vols:
        if job.cancelled:
            break
        job.update(message=f"Lese {vol['name']} …", **counters)
        scan_volume(job, vol, counters)
    job.update(message="Duplikate werden ermittelt …", **counters)
    counters.update(compute_duplicates(job))
    job.update(progress=counters["dateien"], total=counters["dateien"], message="Einlesen abgeschlossen", **counters)
    return counters
