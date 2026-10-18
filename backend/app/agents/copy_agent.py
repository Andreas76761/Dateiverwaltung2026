"""Schritt 4 – Kopier-Agent: erst nach manueller Freigabe werden KOPIEN im neuen Cloud-Ordner angelegt.

- Original bleibt unverändert (kein Verschieben, kein Löschen).
- Ziel wird nie überschrieben; identische Dateien werden übersprungen.
- Jede Kopie wird per SHA-256 verifiziert.
- Dateien auf Agent-Computern werden als Aufgabe eingeplant und dort vom Agenten kopiert.
"""
from __future__ import annotations

from collections import Counter

from .. import db
from ..config import get_settings
from ..jobs import Job
from ..safety import SafetyError, safe_copy


def run(job: Job, params: dict) -> dict:
    s = get_settings()
    local = {c["id"] for c in s.computers if c["mode"] == "local"}
    where = "review_status='freigegeben' AND missing=0 AND COALESCE(final_path, suggested_path) IS NOT NULL"
    if not params.get("include_duplicates"):
        where += " AND is_primary=1"
    if params.get("file_ids"):
        ids = [int(i) for i in params["file_ids"]]
        where += f" AND id IN ({','.join('?' * len(ids))})"
    else:
        ids = []
    files = db.query(f"SELECT *, COALESCE(final_path, suggested_path) target FROM files WHERE {where}", ids)
    dry = bool(params.get("dry_run"))
    allow_online = bool(params.get("download_online_only", s.cloud.get("download_online_only")))
    stats = {"geplant": len(files), "kopiert": 0, "übersprungen": 0, "fehler": 0, "an_agent_übergeben": 0, "nur_online": 0,
             "bytes": 0, "trockenlauf": dry, "ziel": s.target_root}
    per_group: Counter = Counter()
    per_group_bytes: Counter = Counter()
    job.update(progress=0, total=len(files), message="Kopien werden erstellt …" if not dry else "Trockenlauf …", **stats)

    for i, f in enumerate(files, 1):
        if job.cancelled:
            break
        status, msg, dst, nbytes, verified = "geplant", "", f["target"], 0, 0
        if f["online_only"] and not allow_online:
            # Kopieren würde den Download aus der Cloud auslösen → nur mit ausdrücklicher Erlaubnis
            status, msg = "übersprungen", "Nur online – nicht heruntergeladen (in „Kopieren“ erlauben)"
            stats["nur_online"] += 1
        elif dry:
            status, msg = "geplant", "Trockenlauf – nichts kopiert"
            nbytes = f["size"] or 0
        elif f["computer_id"] not in local:
            if db.one("SELECT 1 FROM copy_ops WHERE file_id=? AND status IN ('geplant','kopiert')", (f["id"],)):
                stats["übersprungen"] += 1
                continue
            status, msg = "geplant", "Wird vom Agenten auf dem Quell-Computer ausgeführt"
            stats["an_agent_übergeben"] += 1
        else:
            try:
                r = safe_copy(f["path"], f["target"], f["sha256"])
                status, msg, dst, nbytes, verified = r["status"], r["message"], r["dst"], r["bytes"], int(r["verified"])
            except (SafetyError, OSError) as exc:
                status, msg = "fehler", str(exc)
        if not dry:
            with db.tx() as c:
                c.execute(
                    """INSERT INTO copy_ops(job_id, file_id, computer_id, src, dst, status, bytes, verified, message, created_at, done_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (job.id, f["id"], f["computer_id"], f["path"], dst, status, nbytes, verified, msg, db.now(),
                     db.now() if status != "geplant" else None),
                )
        if status in ("kopiert", "übersprungen", "fehler"):
            stats[status] += 1
        if status == "kopiert" or dry:
            stats["bytes"] += nbytes
            per_group[f["group_name"] or "?"] += 1
            per_group_bytes[f["group_name"] or "?"] += nbytes
        if i % 10 == 0 or i == len(files):
            job.update(progress=i, message=f"{i}/{len(files)} verarbeitet", **stats)

    stats["je_gruppe"] = dict(per_group)
    stats["je_gruppe_bytes"] = dict(per_group_bytes)
    return stats
