"""Schritt 4 – Kopier-Agent: erst nach manueller Freigabe werden KOPIEN im neuen Cloud-Ordner angelegt.

- Original bleibt unverändert (kein Verschieben, kein Löschen).
- Ziel wird nie überschrieben; identische Dateien werden übersprungen.
- Jede Kopie wird per SHA-256 verifiziert.
- Dateien auf Agent-Computern werden als Aufgabe eingeplant und dort vom Agenten kopiert.
"""
from __future__ import annotations

import json
from collections import Counter

from .. import db
from ..config import get_settings
from ..jobs import Job
from ..safety import SafetyError, safe_copy


def _cloud_copy(f: dict, folder_cache: dict) -> tuple[str, str, str]:
    """-> (status, Meldung, Ziel)"""
    from ..connectors import cloud_api

    p = cloud_api.provider_for_volume(f["volume_id"])
    if not p:
        return "fehler", "Cloud-Konto nicht mehr konfiguriert", f["target"]
    acc = p.acc
    folder_rel, _, name = f"{acc.target_folder.strip('/')}/{f['target']}".rpartition("/")
    shown = name
    for virt, _ in cloud_api.GOOGLE_NATIVE.values():  # interne Endung für Google-Dokumente nicht anzeigen
        shown = shown[: -len(virt)] if shown.endswith(virt) else shown
    dst = f"{acc.provider}://{acc.id}/{folder_rel}/{shown}"
    # Schon einmal erfolgreich hierhin kopiert? (wichtig für Google-Dokumente/OneDrive Business ohne vergleichbare Prüfsumme)
    if db.one("SELECT 1 FROM copy_ops WHERE file_id=? AND dst=? AND status='kopiert'", (f["id"], dst)):
        return "übersprungen", "Bereits kopiert (laut Kopierprotokoll)", dst
    if not cloud_api.status(acc)["write"]:
        return "fehler", f"{acc.name}: Schreibzugriff für Kopien fehlt – unter „Quellen“ mit „Kopieren erlauben“ verbinden", dst
    try:
        key = (acc.id, folder_rel)
        if key not in folder_cache:
            folder_cache[key] = p.ensure_folder(folder_rel)
        r = p.copy_into(f["remote_id"], folder_cache[key], name, f.get("sha256"), f.get("remote_hash"))
        return r["status"], r["message"], dst
    except cloud_api.CloudError as exc:
        return "fehler", str(exc), dst


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
    older = 0
    if params.get("skip_older_versions"):  # erkannte ältere Versionen auslassen (bleiben im Original erhalten)
        older = db.one(f"SELECT COUNT(*) n FROM files WHERE {where} AND sim_kind='Versionen' AND sim_best=0", ids)["n"]
        where += " AND NOT (COALESCE(sim_kind,'')='Versionen' AND sim_best=0)"
    files = db.query(f"SELECT *, COALESCE(final_path, suggested_path) target FROM files WHERE {where}", ids)
    dry = bool(params.get("dry_run"))
    allow_online = bool(params.get("download_online_only", s.cloud.get("download_online_only")))
    stats = {"geplant": len(files), "kopiert": 0, "übersprungen": 0, "fehler": 0, "an_agent_übergeben": 0, "nur_online": 0,
             "ältere_versionen_ausgelassen": older,
             "bytes": 0, "trockenlauf": dry, "ziel": s.target_root}
    stats["cloud_serverseitig"] = 0
    folder_cache: dict = {}
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
        elif f["computer_id"] == "cloud-api":
            # Datei liegt in OneDrive/Google Drive → serverseitig innerhalb derselben Cloud kopieren (kein Download)
            status, msg, dst = _cloud_copy(f, folder_cache)
            nbytes = (f["size"] or 0) if status == "kopiert" else 0
            if status == "kopiert":
                stats["cloud_serverseitig"] += 1
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
    if not dry and not job.cancelled and s.raw.get("target", {}).get("reports", True) and (stats["kopiert"] or stats["fehler"]):
        # Prüfbericht als PDF + Excel mit in den Zielordner legen (unter „_Prüfberichte“, nie überschreiben)
        from .. import exports
        job.update(**stats)
        try:
            stats["prüfbericht"] = exports.save_report_to_target(
                {**db.one("SELECT * FROM jobs WHERE id=?", (job.id,)), "stats": json.dumps(stats, ensure_ascii=False)})
        except Exception as exc:  # Bericht darf den Kopiervorgang nicht scheitern lassen
            stats["prüfbericht_fehler"] = str(exc)
    return stats
