"""Skill: Miniaturen-Cache – speichern, bei Bedarf nachladen und Speicher-Obergrenze einhalten.

Strategie (analysis.thumbnails_mode):
- smart (Standard): Deckblatt für alle Dateien, ALLE Seiten sofort nur für wichtige Dateien
  (Wichtigkeit ≥ thumbs_all_pages_min_importance) – der Rest beim ersten Öffnen.
- alle: alle Seiten sofort (nur für kleinere Bestände sinnvoll)
- bei_bedarf: nur Deckblatt, alle Seiten erst beim Öffnen

Obergrenze (analysis.thumbs_budget_gb): Wird sie überschritten, werden zuerst die Folgeseiten der
UNWICHTIGSTEN Dateien aus dem Cache entfernt (Deckblätter bleiben). Gelöscht wird ausschließlich
im eigenen Datenverzeichnis – nie eine Nutzerdatei.
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import db
from ..config import get_settings
from . import thumbnails


def pages_now(importance: int, pinned: bool = False) -> int | None:
    """Wie viele Seiten sofort erzeugt werden (None = alle)."""
    a = get_settings().analysis
    mode = a.get("thumbnails_mode", "smart")
    if mode == "alle":
        return None
    if mode == "smart" and (pinned or importance >= int(a.get("thumbs_all_pages_min_importance", 50))):
        return None
    return 1


def store(file_id: int, thumbs: list[dict], total: int) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM thumbnails WHERE file_id=?", (file_id,))  # nur Cache-Metadaten
        c.executemany(
            "INSERT INTO thumbnails(file_id, page, path, width, height, label, bytes) VALUES (?,?,?,?,?,?,?)",
            [(file_id, t["page"], t["path"], t["width"], t["height"], t.get("label"), t.get("bytes", 0)) for t in thumbs],
        )
        c.execute("UPDATE files SET thumbs_complete=? WHERE id=?", (int(len(thumbs) >= total), file_id))


def create(f: dict, importance: int) -> tuple[int, int]:
    """Miniaturen nach Strategie erzeugen. -> (erzeugt, gesamt)"""
    thumbs, total = thumbnails.generate(f["id"], f["path"], f["ext"] or "", pages_now(importance, bool(f.get("pinned"))))
    store(f["id"], thumbs, total)
    return len(thumbs), total


def ensure_all(f: dict) -> dict:
    """Alle Seiten nachträglich erzeugen (beim Öffnen einer Datei)."""
    thumbs, total = thumbnails.generate(f["id"], f["path"], f["ext"] or "")
    store(f["id"], thumbs, total)
    enforce_budget(protect={f["id"]})
    return {"pages": len(thumbs), "total": total}


def _dir_size(p: Path) -> int:
    return sum(x.stat().st_size for x in p.glob("*") if x.is_file()) if p.exists() else 0


def usage() -> dict:
    s = get_settings()
    thumbs = db.one("SELECT COALESCE(SUM(bytes),0) b, COUNT(*) n FROM (SELECT DISTINCT path, bytes FROM thumbnails)")
    pdf_cache = _dir_size(s.data_dir / "pdf-cache")
    return {"thumbs_bytes": thumbs["b"], "thumbs_pages": thumbs["n"], "pdf_cache_bytes": pdf_cache,
            "total_bytes": thumbs["b"] + pdf_cache,
            "budget_bytes": int(float(s.analysis.get("thumbs_budget_gb", 20)) * 1024 ** 3),
            "complete_files": db.one("SELECT COUNT(*) n FROM files WHERE thumbs_complete=1")["n"],
            "cover_only_files": db.one("SELECT COUNT(DISTINCT file_id) n FROM thumbnails t JOIN files f ON f.id=t.file_id "
                                       "WHERE f.thumbs_complete=0")["n"]}


def enforce_budget(protect: set[int] | None = None) -> dict:
    """Cache unter die Obergrenze bringen (Ziel 90 %). Nur Folgeseiten unwichtiger Dateien + alter PDF-Cache."""
    s = get_settings()
    u = usage()
    budget = u["budget_bytes"]
    if u["total_bytes"] <= budget:
        return {"entfernt_bytes": 0}
    target = int(budget * 0.9)
    over = u["total_bytes"] - target
    freed = 0
    protect = protect or set()
    # 1. Alter PDF-Cache (konvertierte Office-Dateien) – wird bei Bedarf neu erzeugt
    cache = s.data_dir / "pdf-cache"
    if cache.exists():
        for p in sorted(cache.glob("*.pdf"), key=lambda x: x.stat().st_atime):
            if freed >= over:
                break
            freed += p.stat().st_size
            p.unlink(missing_ok=True)
    # 2. Folgeseiten der unwichtigsten Dateien (Deckblatt bleibt)
    if freed < over:
        rows = db.query(
            """SELECT t.file_id, t.page, t.path, t.bytes FROM thumbnails t JOIN files f ON f.id=t.file_id
               WHERE t.page>1 AND f.pinned=0 ORDER BY f.importance ASC, t.file_id, t.page DESC""")
        drop_paths, touched = [], set()
        for r in rows:
            if freed >= over:
                break
            if r["file_id"] in protect:
                continue
            drop_paths.append(r["path"])
            touched.add(r["file_id"])
            freed += r["bytes"] or 0
        with db.tx() as c:
            for chunk in range(0, len(drop_paths), 500):
                part = drop_paths[chunk:chunk + 500]
                ph = ",".join("?" * len(part))
                ids = [x["file_id"] for x in c.execute(f"SELECT DISTINCT file_id FROM thumbnails WHERE path IN ({ph})", part)]
                c.execute(f"DELETE FROM thumbnails WHERE path IN ({ph})", part)
                if ids:
                    c.execute(f"UPDATE files SET thumbs_complete=0 WHERE id IN ({','.join('?' * len(ids))})", ids)
        thumbs_root = str(s.thumbs_dir.resolve())
        for p in drop_paths:
            if os.path.realpath(p).startswith(thumbs_root + os.sep):  # nur im eigenen Cache löschen
                Path(p).unlink(missing_ok=True)
    return {"entfernt_bytes": freed}
