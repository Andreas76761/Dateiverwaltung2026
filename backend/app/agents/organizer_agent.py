"""Schritt 3 – Organisations-Agent: virtuelle neue Eingruppierung (Vorschlag ohne physische Änderung)."""
from __future__ import annotations

from .. import db
from ..jobs import Job
from .scan_agent import refresh_dup_groups


def effective_path_sql() -> str:
    return "COALESCE(final_path, suggested_path)"


def build_tree(only_primary: bool = True, status: str | None = None) -> dict:
    """Baum der vorgeschlagenen Struktur mit Anzahl & Größe je Ordner."""
    where = ["missing=0", "suggested_path IS NOT NULL"]
    args: list = []
    if only_primary:
        where.append("is_primary=1")
    if status:
        where.append("review_status=?")
        args.append(status)
    p = effective_path_sql()
    # rtrim(p, replace(p,'/','')) = Ordnerteil des Pfads (alles bis zum letzten '/')
    rows = db.query(
        f"""SELECT rtrim(rtrim({p}, replace({p}, '/', '')), '/') AS folder, COUNT(*) n, COALESCE(SUM(size),0) size,
                   SUM(review_status='freigegeben') approved, SUM(review_status='abgelehnt') rejected
            FROM files WHERE {' AND '.join(where)} GROUP BY folder""", args)
    root = {"name": "", "path": "", "count": 0, "size": 0, "approved": 0, "rejected": 0, "children": {}}
    for r in rows:
        parts = r["folder"].split("/") if r["folder"] else []
        node = root
        for depth in range(len(parts) + 1):
            node["count"] += r["n"]
            node["size"] += r["size"]
            node["approved"] += r["approved"]
            node["rejected"] += r["rejected"]
            if depth == len(parts):
                break
            name = parts[depth]
            node = node["children"].setdefault(name, {
                "name": name, "path": "/".join(parts[: depth + 1]), "count": 0, "size": 0,
                "approved": 0, "rejected": 0, "children": {},
            })

    def finish(n):
        n["children"] = sorted((finish(c) for c in n["children"].values()), key=lambda x: x["name"])
        return n

    return finish(root)


def run(job: Job, params: dict) -> dict:
    job.update(message="Duplikate & primäre Exemplare werden bestimmt …")
    stats = refresh_dup_groups()
    rows = db.query("SELECT COUNT(*) n, SUM(is_primary=0) d FROM files WHERE missing=0 AND suggested_path IS NOT NULL")[0]
    paths = db.query(f"SELECT {effective_path_sql()} p FROM files WHERE missing=0 AND suggested_path IS NOT NULL AND is_primary=1")
    folders = len({r["p"].rsplit("/", 1)[0] for r in paths})
    stats.update({"dateien_im_vorschlag": rows["n"] or 0, "duplikate_ausgeblendet": rows["d"] or 0, "zielordner": folders})
    job.update(progress=1, total=1, message="Vorschlag erstellt", **stats)
    return stats
