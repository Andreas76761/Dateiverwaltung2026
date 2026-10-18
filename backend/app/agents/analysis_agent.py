"""Schritt 2 – Analyse-Agent: Inhalte lesen, OCR, Miniaturen, LLM-Kategorie (50 → 4 Gruppen),
Labels, Wichtigkeit und Pfadvorschlag. Arbeitet nur lesend auf den Quelldateien."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from .. import db, llm
from ..categories import BY_ID, find_category
from ..config import get_settings
from ..jobs import Job
from ..skills import extract, importance, ocr, pathsuggest, thumbnails
from ..skills.labels import guess_year, rule_labels

log = logging.getLogger("fdv.analyse")


def _local_computers() -> set[str]:
    return {c["id"] for c in get_settings().computers if c["mode"] == "local"}


def analyze_file(f: dict, local: bool) -> dict:
    """Analysiert eine Datei und schreibt das Ergebnis. Gibt eine kleine Statistik zurück."""
    stat = {"ocr": 0, "miniaturen": 0, "fehler": 0}
    text, pages, ocr_text, err = f.get("text_excerpt") or "", f.get("page_count"), "", None
    readable = local and os.path.isfile(f["path"])
    if readable:
        try:
            text, pages = extract.extract_text(f["path"], f["ext"] or "")
        except Exception as exc:
            err = f"Textextraktion: {exc}"
        ocr_text = ocr.run(f["path"], f["ext"] or "", text)
        if ocr_text and not ocr_text.startswith("[OCR-Fehler"):
            stat["ocr"] = 1
        if thumbnails.supports(f["ext"] or ""):
            try:
                thumbs = thumbnails.generate(f["id"], f["path"], f["ext"])
                with db.tx() as c:
                    c.execute("DELETE FROM thumbnails WHERE file_id=?", (f["id"],))  # nur DB-Cache
                    c.executemany(
                        "INSERT INTO thumbnails(file_id, page, path, width, height) VALUES (?,?,?,?,?)",
                        [(f["id"], t["page"], t["path"], t["width"], t["height"]) for t in thumbs],
                    )
                stat["miniaturen"] = len(thumbs)
                if pages is None and thumbs and f["ext"] != ".pdf" and f["file_type"] != "Bild":
                    pages = len(thumbs)
            except Exception as exc:
                err = (err + "; " if err else "") + f"Miniatur: {exc}"

    full_text = (text + " " + ocr_text).strip()
    meta = {**f, "page_count": pages}
    result, provider = llm.analyze(meta, full_text)
    cat = BY_ID[result["category_id"]]

    labels = {l for l in result["labels"]} | rule_labels(f["name"], full_text)
    mt = datetime.fromisoformat(f["mtime"]) if f.get("mtime") else datetime.now()
    year = guess_year(f["name"], full_text, mt.year)
    labels.add(str(year))
    user_labels = {r["label"] for r in db.query("SELECT label FROM labels WHERE file_id=? AND source='nutzer'", (f["id"],))}
    labels |= user_labels

    imp, reason = importance.score(cat, labels, f["file_type"], f.get("mtime"), f.get("dup_count") or 1,
                                   bool(f.get("is_primary", 1)), result["importance"], bool(f.get("pinned")))
    sub = result["subfolder"] or pathsuggest.pick_subfolder(cat, f["name"], full_text)
    suggested = pathsuggest.suggest(cat, f["name"], year, mt.month, f["file_type"], sub)

    with db.tx() as c:
        c.execute(
            """UPDATE files SET text_excerpt=?, ocr_text=?, page_count=?, summary=?, category=?, group_name=?, confidence=?,
               importance=?, importance_reason=?, suggested_path=?, status='analysiert', error=?, llm_provider=?, analyzed_at=?
               WHERE id=?""",
            (text[:20000] or f.get("text_excerpt"), ocr_text or None, pages, result["summary"], cat.name, cat.group,
             result["confidence"], imp, reason, suggested, err, provider, db.now(), f["id"]),
        )
        c.execute("DELETE FROM labels WHERE file_id=? AND source!='nutzer'", (f["id"],))  # nur Metadaten
        c.executemany(
            "INSERT OR IGNORE INTO labels(file_id, label, source) VALUES (?,?,?)",
            [(f["id"], l, "llm") for l in labels if l not in user_labels],
        )
    if err:
        stat["fehler"] = 1
    return stat


def copy_analysis(src_id: int, f: dict) -> None:
    """Identische Datei (gleicher SHA-256) übernimmt die Analyse des Originals – konsistent und spart LLM-Kosten."""
    src = db.one("SELECT * FROM files WHERE id=?", (src_id,))
    if not src or src["status"] != "analysiert":
        return
    labels = {r["label"] for r in db.query("SELECT label FROM labels WHERE file_id=?", (src_id,))}
    labels |= {r["label"] for r in db.query("SELECT label FROM labels WHERE file_id=? AND source='nutzer'", (f["id"],))}
    cat = find_category(src["category"])
    imp, reason = importance.score(cat, labels, f["file_type"], f.get("mtime"), f.get("dup_count") or 2,
                                   bool(f.get("is_primary", 0)), None, bool(f.get("pinned")))
    folder = (src["suggested_path"] or "").rsplit("/", 1)[0]
    with db.tx() as c:
        c.execute(
            """UPDATE files SET text_excerpt=?, ocr_text=?, page_count=?, summary=?, category=?, group_name=?, confidence=?,
               importance=?, importance_reason=?, suggested_path=?, status='analysiert', error=NULL, llm_provider=?, analyzed_at=?
               WHERE id=?""",
            (src["text_excerpt"], src["ocr_text"], src["page_count"], src["summary"], src["category"], src["group_name"],
             src["confidence"], imp, reason, f"{folder}/{f['name']}", f"{src['llm_provider']} (Duplikat)", db.now(), f["id"]),
        )
        c.execute("DELETE FROM labels WHERE file_id=? AND source!='nutzer'", (f["id"],))
        c.executemany("INSERT OR IGNORE INTO labels(file_id, label, source) VALUES (?,?, 'llm')", [(f["id"], l) for l in labels])
        c.execute("DELETE FROM thumbnails WHERE file_id=?", (f["id"],))
        c.execute("INSERT INTO thumbnails(file_id, page, path, width, height) SELECT ?, page, path, width, height FROM thumbnails WHERE file_id=?",
                  (f["id"], src_id))


def run(job: Job, params: dict) -> dict:
    where = "missing=0"
    args: list = []
    if params.get("file_ids"):
        ids = [int(i) for i in params["file_ids"]]
        where += f" AND id IN ({','.join('?' * len(ids))})"
        args += ids
    elif not params.get("force"):
        where += " AND status!='analysiert'"
    files = db.query(f"SELECT * FROM files WHERE {where} ORDER BY id", args)
    local = _local_computers()
    total = len(files)
    stats = {"analysiert": 0, "ocr": 0, "miniaturen": 0, "fehler": 0, "provider": get_settings().llm["provider"]}
    job.update(progress=0, total=total, message=f"{total} Dateien werden analysiert", **stats)

    # Duplikate nur einmal analysieren
    analyzed = {} if params.get("force") else {
        r["sha256"]: r["id"] for r in db.query("SELECT sha256, id FROM files WHERE status='analysiert' AND sha256 IS NOT NULL")}
    reps, followers = [], []
    for f in files:
        h = f["sha256"]
        if h and h in analyzed:
            followers.append((f, analyzed[h]))
        else:
            reps.append(f)
            if h:
                analyzed[h] = f["id"]
    files = reps
    stats["duplikate_übernommen"] = 0

    workers = 6 if get_settings().llm["provider"] in ("anthropic",) else 3
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(analyze_file, f, f["computer_id"] in local): f for f in files}
        for i, fut in enumerate(as_completed(futs), 1):
            if job.cancelled:
                pool.shutdown(wait=False, cancel_futures=True)
                break
            try:
                st = fut.result()
                for k in ("ocr", "miniaturen", "fehler"):
                    stats[k] += st[k]
                stats["analysiert"] += 1
            except Exception as exc:
                f = futs[fut]
                log.exception("Analyse fehlgeschlagen: %s", f["path"])
                stats["fehler"] += 1
                with db.tx() as c:
                    c.execute("UPDATE files SET status='fehler', error=? WHERE id=?", (str(exc)[:500], f["id"]))
            if i % 5 == 0 or i == total:
                job.update(progress=i, message=f"{i}/{total} analysiert", **stats)

    for f, src_id in followers:
        if job.cancelled:
            break
        copy_analysis(src_id, f)
        stats["duplikate_übernommen"] += 1
    job.update(progress=total, message=f"{total}/{total} analysiert", **stats)

    from .scan_agent import refresh_dup_groups
    stats.update(refresh_dup_groups())
    return stats
