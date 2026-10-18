"""Schritt 2 – Analyse-Agent: Inhalte lesen, OCR, LLM-Kategorie (50 → 4 Gruppen), Labels, Wichtigkeit,
Pfadvorschlag und Miniaturen. Arbeitet nur lesend auf den Quelldateien.

Für große Bestände:
- Cloud-Platzhalter (nur online) werden nie gelesen – Einordnung nur über Metadaten.
- Miniaturen nach Strategie (smart: alle Seiten nur für wichtige Dateien, sonst Deckblatt).
- Modus "unklare": nur Dateien, bei denen die Offline-Regeln unsicher sind, gehen an das LLM.
- Kostenlimit je Lauf; Batch-Modus (Anthropic Message Batches, 50 % günstiger).
- Fortsetzbar: jede Datei wird einzeln gespeichert; laufende Batches überstehen Neustarts.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from .. import db, llm
from ..categories import BY_ID, find_category
from ..config import get_settings
from ..jobs import Job
from ..llm.costs import CostMeter
from ..llm.rules_provider import RulesProvider
from ..skills import extract, importance, ocr, pathsuggest, thumbcache, thumbnails
from ..skills.labels import guess_year, rule_labels

log = logging.getLogger("fdv.analyse")
CHUNK = 200            # so viele Dateien gleichzeitig in Arbeit (begrenzt Speicher bei Millionen Dateien)
BATCH_POLL_S = 30


def _local_computers() -> set[str]:
    return {c["id"] for c in get_settings().computers if c["mode"] == "local"}


def _readable(f: dict, local: bool) -> bool:
    if not local or not os.path.isfile(f["path"]):
        return False
    return not f.get("online_only") or bool(get_settings().cloud.get("download_online_only"))


# ---------------------------------------------------------------- Bausteine

def prepare(f: dict, local: bool) -> dict:
    """Inhalt lesen (Text, OCR). Cloud-Platzhalter werden NICHT gelesen."""
    ctx = {"text": f.get("text_excerpt") or "", "ocr": f.get("ocr_text") or "", "pages": f.get("page_count"),
           "err": None, "ocr_done": 0, "readable": _readable(f, local)}
    if ctx["readable"] and f.get("status") != "wartet_llm":
        try:
            ctx["text"], ctx["pages"] = extract.extract_text(f["path"], f["ext"] or "")
        except Exception as exc:
            ctx["err"] = f"Textextraktion: {exc}"
        o = ocr.run(f["path"], f["ext"] or "", ctx["text"])
        if o and not o.startswith("[OCR-Fehler"):
            ctx["ocr"], ctx["ocr_done"] = o, 1
    ctx["full"] = (ctx["text"] + " " + ctx["ocr"]).strip()
    return ctx


def rules_result(f: dict, ctx: dict) -> dict:
    return llm.normalize(RulesProvider().analyze({**f, "page_count": ctx["pages"]}, ctx["full"]))


def needs_llm(rules: dict, params: dict) -> bool:
    s = get_settings().llm
    if s["provider"] == "rules":
        return False
    mode = params.get("mode") or s.get("mode", "alle")
    return not (mode == "unklare" and rules["confidence"] >= float(s.get("hybrid_min_confidence", 0.6)))


def finalize(f: dict, ctx: dict, result: dict, provider: str, rules_conf: float | None) -> dict:
    """Ergebnis speichern: Kategorie, Labels, Wichtigkeit, Pfad, Miniaturen."""
    stat = {"miniaturen": 0}
    cat = BY_ID[result["category_id"]]
    labels = set(result["labels"]) | rule_labels(f["name"], ctx["full"])
    mt = datetime.fromisoformat(f["mtime"]) if f.get("mtime") else datetime.now()
    year = guess_year(f["name"], ctx["full"], mt.year)
    labels.add(str(year))
    if f.get("online_only"):
        labels.add("Nur online")
    user_labels = {r["label"] for r in db.query("SELECT label FROM labels WHERE file_id=? AND source='nutzer'", (f["id"],))}
    labels |= user_labels

    imp, reason = importance.score(cat, labels, f["file_type"], f.get("mtime"), f.get("dup_count") or 1,
                                   bool(f.get("is_primary", 1)), result["importance"], bool(f.get("pinned")))
    sub = result["subfolder"] or pathsuggest.pick_subfolder(cat, f["name"], ctx["full"])
    suggested = pathsuggest.suggest(cat, f["name"], year, mt.month, f["file_type"], sub)

    pages, err = ctx["pages"], ctx["err"]
    if ctx["readable"] and thumbnails.supports(f["ext"] or ""):
        try:
            made, total = thumbcache.create(f, imp)
            stat["miniaturen"] = made
            if total and (f["ext"] in thumbnails.OFFICE_PAGED or f["ext"] in thumbnails.mail.MAIL_EXTS):
                pages = total  # gedruckte Seiten (bei XLSX sonst nur Anzahl der Blätter)
        except Exception as exc:
            err = (err + "; " if err else "") + f"Miniatur: {exc}"

    with db.tx() as c:
        c.execute(
            """UPDATE files SET text_excerpt=?, ocr_text=?, page_count=?, summary=?, category=?, group_name=?, confidence=?,
               importance=?, importance_reason=?, suggested_path=?, status='analysiert', error=?, llm_provider=?,
               analyzed_at=?, rules_confidence=? WHERE id=?""",
            (ctx["text"][:20000] or None, ctx["ocr"] or None, pages, result["summary"], cat.name, cat.group,
             result["confidence"], imp, reason, suggested, err, provider, db.now(), rules_conf, f["id"]),
        )
        c.execute("DELETE FROM labels WHERE file_id=? AND source!='nutzer'", (f["id"],))  # nur Metadaten
        c.executemany("INSERT OR IGNORE INTO labels(file_id, label, source) VALUES (?,?,?)",
                      [(f["id"], l, "llm") for l in labels if l not in user_labels])
        db.fts_update(c, f["id"])
    stat["fehler"] = int(bool(err))
    return stat


def analyze_file(f: dict, local: bool, params: dict, meter: CostMeter) -> dict:
    """Einzelanalyse (synchron)."""
    ctx = prepare(f, local)
    rules = rules_result(f, ctx)
    stat = {"ocr": ctx["ocr_done"], "llm_fallback": 0, "nur_regeln": 0, "llm": 0, "kostenlimit": 0}
    if needs_llm(rules, params):
        if meter.allow():
            result, provider, usage = llm.analyze({**f, "page_count": ctx["pages"]}, ctx["full"])
            if provider.endswith("(Fallback)"):
                stat["llm_fallback"] = 1
            else:
                stat["llm"] = 1
                if usage:
                    meter.add(f["id"], usage.get("model") or get_settings().llm["anthropic_model"], usage)
        else:
            result, provider = rules, "regeln (Kostenlimit)"
            stat["kostenlimit"] = 1
    else:
        result, provider = rules, ("regeln" if get_settings().llm["provider"] == "rules" else "regeln (sicher)")
        stat["nur_regeln"] = int(provider != "regeln")
    stat.update(finalize(f, ctx, result, provider, rules["confidence"]))
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
               importance=?, importance_reason=?, suggested_path=?, status='analysiert', error=NULL, llm_provider=?,
               analyzed_at=?, thumbs_complete=? WHERE id=?""",
            (src["text_excerpt"], src["ocr_text"], src["page_count"], src["summary"], src["category"], src["group_name"],
             src["confidence"], imp, reason, f"{folder}/{f['name']}", f"{src['llm_provider']} (Duplikat)", db.now(),
             src["thumbs_complete"], f["id"]),
        )
        c.execute("DELETE FROM labels WHERE file_id=? AND source!='nutzer'", (f["id"],))
        c.executemany("INSERT OR IGNORE INTO labels(file_id, label, source) VALUES (?,?, 'llm')", [(f["id"], l) for l in labels])
        c.execute("DELETE FROM thumbnails WHERE file_id=?", (f["id"],))
        c.execute("""INSERT INTO thumbnails(file_id, page, path, width, height, label, bytes)
                     SELECT ?, page, path, width, height, label, 0 FROM thumbnails WHERE file_id=?""", (f["id"], src_id))
        db.fts_update(c, f["id"])


# ---------------------------------------------------------------- Auswahl

def select_files(params: dict) -> tuple[list[dict], list[tuple[dict, int]], set[int]]:
    """-> (zu analysierende Dateien, Duplikate (Datei, Original-ID), Datei-IDs in laufenden Batches)"""
    from ..llm import batch as batchmod

    in_batch = {i for b in batchmod.pending() for i in json.loads(b["file_ids"])}
    where, args = "missing=0", []
    if params.get("file_ids"):
        ids = [int(i) for i in params["file_ids"]]
        where += f" AND id IN ({','.join('?' * len(ids))})"
        args += ids
    elif not params.get("force"):
        where += " AND status!='analysiert'"
    files = [f for f in db.query(f"SELECT * FROM files WHERE {where} ORDER BY importance DESC, id", args)
             if f["id"] not in in_batch]
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
    return reps, followers, in_batch


def _accumulate(stats: dict, st: dict) -> None:
    for k, v in st.items():
        if isinstance(v, (int, float)):
            stats[k] = stats.get(k, 0) + v


# ---------------------------------------------------------------- Batch-Modus

def _wait_and_apply_batches(job: Job, meter: CostMeter, stats: dict, local: set[str]) -> None:
    """Laufende Anthropic-Batches abwarten und Ergebnisse übernehmen (auch nach Server-Neustart)."""
    from ..llm import batch as batchmod

    for b in batchmod.pending():
        while True:
            if job.cancelled:
                batchmod.cancel(b["batch_id"])
                with db.tx() as c:  # Dateien wieder für den nächsten Lauf freigeben
                    c.execute(f"UPDATE files SET status='eingelesen' WHERE status='wartet_llm' AND id IN "
                              f"({','.join(str(int(i)) for i in json.loads(b['file_ids']))})")
                return
            st = batchmod.status(b["batch_id"])
            if st["status"] == "ended":
                break
            done = st["succeeded"] + st["errored"] + st["canceled"] + st["expired"]
            job.update(message=f"Warte auf Anthropic-Batch {b['batch_id'][-8:]}: {done}/{done + st['processing']} fertig", **stats)
            for _ in range(BATCH_POLL_S):
                if job.cancelled:
                    break
                time.sleep(1)
        ok = failed = 0
        for fid, result, usage, error in batchmod.results(b["batch_id"]):
            f = db.one("SELECT * FROM files WHERE id=?", (fid,))
            if not f:
                continue
            if usage:
                meter.add(fid, usage.get("model") or b["model"], usage, batch=True)
            ctx = prepare(f, f["computer_id"] in local)  # liest nur noch Miniaturen (Text liegt bereits in der DB)
            rules = rules_result(f, ctx)
            if result is None:
                result, provider = rules, f"regeln (Batch-Fehler: {error})"
                failed += 1
            else:
                provider = "anthropic (Batch)"
                ok += 1
            _accumulate(stats, finalize(f, ctx, result, provider, rules["confidence"]))
        batchmod.mark_done(b["batch_id"], f"{ok} ok, {failed} Fehler")
        stats["llm"] = stats.get("llm", 0) + ok
        stats["llm_fallback"] = stats.get("llm_fallback", 0) + failed
        stats.update(meter.stats())


def _run_batch_mode(job: Job, params: dict, files: list[dict], local: set[str], meter: CostMeter, stats: dict) -> None:
    from ..llm import batch as batchmod

    requests, prepared = [], 0
    for i in range(0, len(files), CHUNK):
        if job.cancelled:
            return
        part = files[i:i + CHUNK]
        with ThreadPoolExecutor(max_workers=4) as pool:
            ctxs = list(pool.map(lambda f: (f, prepare(f, f["computer_id"] in local)), part))
        for f, ctx in ctxs:
            rules = rules_result(f, ctx)
            stats["ocr"] = stats.get("ocr", 0) + ctx["ocr_done"]
            if needs_llm(rules, params):
                requests.append(batchmod.build(f["id"], {**f, "page_count": ctx["pages"]}, ctx["full"]))
                with db.tx() as c:  # Text sichern, damit die Datei beim Auswerten nicht erneut gelesen werden muss
                    c.execute("UPDATE files SET text_excerpt=?, ocr_text=?, page_count=?, status='wartet_llm', rules_confidence=? WHERE id=?",
                              (ctx["text"][:20000] or None, ctx["ocr"] or None, ctx["pages"], rules["confidence"], f["id"]))
            else:
                _accumulate(stats, finalize(f, ctx, rules, "regeln (sicher)", rules["confidence"]))
                stats["nur_regeln"] = stats.get("nur_regeln", 0) + 1
            prepared += 1
        job.update(progress=prepared, message=f"Vorbereitung: {prepared}/{len(files)} Dateien gelesen", **stats)
    if requests:
        ids = batchmod.submit(requests, job.id)
        stats["batches"] = len(ids)
        job.update(message=f"{len(requests)} Anfragen in {len(ids)} Batch(es) an Anthropic übergeben", **stats)
    _wait_and_apply_batches(job, meter, stats, local)


# ---------------------------------------------------------------- Lauf

def run(job: Job, params: dict) -> dict:
    s = get_settings()
    local = _local_computers()
    llm.reset()
    meter = CostMeter(job.id, float(params.get("max_cost_usd", s.llm.get("max_cost_usd", 0)) or 0))
    stats = {"analysiert": 0, "ocr": 0, "miniaturen": 0, "fehler": 0, "provider": s.llm["provider"], "llm": 0,
             "llm_fallback": 0, "nur_regeln": 0, "kostenlimit": 0, "duplikate_übernommen": 0,
             "modus": params.get("mode") or s.llm.get("mode", "alle")}
    batch_mode = s.llm["provider"] == "anthropic" and bool(params.get("batch", s.llm.get("batch")))

    # 1. Batches aus einem früheren (unterbrochenen) Lauf zu Ende bringen
    from ..llm import batch as batchmod
    if s.llm["provider"] == "anthropic" and batchmod.pending():
        job.update(message="Laufende Anthropic-Batches werden fortgesetzt …")
        _wait_and_apply_batches(job, meter, stats, local)

    files, followers, _ = select_files(params)
    total = len(files)
    stats["dateien"] = total
    job.update(progress=0, total=total, message=f"{total} Dateien werden analysiert", **stats)

    # 2. Analyse
    if batch_mode and files:
        _run_batch_mode(job, params, files, local, meter, stats)
        stats["analysiert"] = stats.get("llm", 0) + stats.get("llm_fallback", 0) + stats.get("nur_regeln", 0)
    else:
        workers = 6 if s.llm["provider"] == "anthropic" else 3
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i in range(0, total, CHUNK):          # in Blöcken – begrenzt Speicher bei sehr vielen Dateien
                if job.cancelled:
                    break
                futs = {pool.submit(analyze_file, f, f["computer_id"] in local, params, meter): f for f in files[i:i + CHUNK]}
                for fut in as_completed(futs):
                    done += 1
                    try:
                        _accumulate(stats, fut.result())
                        stats["analysiert"] += 1
                    except Exception as exc:
                        f = futs[fut]
                        log.exception("Analyse fehlgeschlagen: %s", f["path"])
                        stats["fehler"] += 1
                        with db.tx() as c:
                            c.execute("UPDATE files SET status='fehler', error=? WHERE id=?", (str(exc)[:500], f["id"]))
                    if llm.last_error:
                        stats["llm_fehler"] = llm.last_error
                    if done % 5 == 0 or done == total:
                        stats.update(meter.stats())
                        job.update(progress=done, message=f"{done}/{total} analysiert", **stats)
                if job.cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)

    # 3. Duplikate übernehmen die Analyse ihres Originals
    for f, src_id in followers:
        if job.cancelled:
            break
        copy_analysis(src_id, f)
        stats["duplikate_übernommen"] += 1

    stats.update(meter.stats())
    job.update(progress=total, message=f"{total}/{total} analysiert", **stats)
    from .scan_agent import refresh_dup_groups
    stats.update(refresh_dup_groups())
    stats["cache"] = thumbcache.enforce_budget()
    return stats
