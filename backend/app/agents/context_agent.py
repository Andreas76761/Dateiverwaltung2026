"""Ordner-Kontext: unsicher eingeordnete Dateien übernehmen die Kategorie ihrer sicher eingeordneten Nachbarn.

Dateien im selben Ordner gehören meist zusammen (z. B. „Steuer/2023/scan0001.pdf“ neben drei sicher erkannten
Steuerbescheiden). Gilt nur für Einordnungen der Offline-Regeln mit geringer Sicherheit; LLM-Ergebnisse und
manuelle Korrekturen werden nie überschrieben. Manuell korrigierte Dateien zählen als besonders starke Nachbarn –
so lernt die Einordnung aus jeder Korrektur.

Ändert nur Einträge in der Datenbank (Kategorie, Bereich, Pfadvorschlag, Wichtigkeit) – keine Dateien.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .. import db
from ..categories import find_category
from ..skills import importance, pathsuggest
from ..skills.labels import guess_year

LOW = 0.6           # darunter gilt eine Regel-Einordnung als unsicher
NEIGHBOR = 0.7      # Nachbarn ab dieser Sicherheit zählen
MIN_WEIGHT = 3.0    # mindestens so viel „Stimmgewicht“ im Ordner
SHARE = 0.7         # so groß muss der Anteil der häufigsten Kategorie sein
MANUAL_WEIGHT = 3.0  # eine manuelle Korrektur zählt wie drei sichere Nachbarn
NEW_CONF = 0.62


def _folder(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def apply(volume_id: str | None = None, folder: str | None = None) -> dict:
    """Ordner-Kontext anwenden – für alles oder gezielt einen Ordner (z. B. nach einer manuellen Korrektur)."""
    where, args = ["missing=0", "status='analysiert'", "category IS NOT NULL"], []
    if volume_id:
        where.append("volume_id=?")
        args.append(volume_id)
    if folder is not None:
        where.append("(rel_path LIKE ? ESCAPE '\\' AND instr(substr(rel_path, ?), '/')=0)")
        args += [folder.replace("%", "\\%").replace("_", "\\_") + "/%", len(folder) + 2]
    rows = db.query(f"""SELECT id, volume_id, rel_path, name, category, confidence, llm_provider, mtime, file_type, text_excerpt,
                        dup_count, is_primary, pinned,
                        EXISTS(SELECT 1 FROM labels l WHERE l.file_id=files.id AND l.label='manuell geprüft') manual
                        FROM files WHERE {' AND '.join(where)}""", args)
    by_folder: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_folder[(r["volume_id"], _folder(r["rel_path"]))].append(r)
    changed = 0
    updates = []
    for members in by_folder.values():
        if len(members) < 2:
            continue
        votes: dict[str, float] = defaultdict(float)
        for m in members:
            if m["manual"]:
                votes[m["category"]] += MANUAL_WEIGHT
            elif (m["confidence"] or 0) >= NEIGHBOR:
                votes[m["category"]] += 1.0
        total = sum(votes.values())
        if total < MIN_WEIGHT:
            continue
        top, weight = max(votes.items(), key=lambda kv: kv[1])
        if weight / total < SHARE:
            continue
        for m in members:
            provider = m["llm_provider"] or ""
            if m["manual"] or not provider.startswith("regeln") or (m["confidence"] or 0) >= LOW or m["category"] == top:
                continue
            cat = find_category(top)
            mt = m["mtime"] or "2000-01-01"
            year = guess_year(m["name"], m["text_excerpt"] or "", int(mt[:4]))
            sub = pathsuggest.pick_subfolder(cat, m["name"], m["text_excerpt"] or "")
            sp = pathsuggest.suggest(cat, m["name"], year, int(mt[5:7]), m["file_type"] or "", sub)
            updates.append((cat.name, cat.group, sp, m["id"], m))
    if updates:
        with db.tx() as c:
            for name, group, sp, fid, m in updates:
                labels = {r["label"] for r in c.execute("SELECT label FROM labels WHERE file_id=?", (fid,))}
                score, reason = importance.score(find_category(name), labels, m["file_type"], m["mtime"], m["dup_count"] or 1,
                                                 bool(m["is_primary"]), None, bool(m["pinned"]))
                c.execute("""UPDATE files SET category=?, group_name=?, suggested_path=?, confidence=?, llm_provider=?,
                             importance=?, importance_reason=? WHERE id=?""",
                          (name, group, sp, NEW_CONF, "regeln (Ordner)", score, reason + ", Ordner-Kontext", fid))
                db.fts_update(c, fid)
                changed += 1
    return {"ordner_kontext": changed, "geprüft_ordner": len(by_folder), "zeit": datetime.now().isoformat(timespec="seconds")}
