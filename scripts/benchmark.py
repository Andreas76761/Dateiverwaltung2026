"""Lasttest: Einlesen/Analyse echter Dateien und Antwortzeiten der Oberfläche bei sehr vielen Dateien.

    python scripts/benchmark.py --files 20000 --rows 500000

1. Legt --files echte kleine Dateien (Text, ein Teil PDFs) in einem Temp-Ordner an und misst Einlesen
   und Analyse (Offline-Regeln, Miniaturen-Strategie "smart").
2. Füllt die Datenbank synthetisch auf --rows Einträge auf und misst die wichtigsten API-Aufrufe
   (Liste, Suche, Filter, Ordnerbaum, Statistik, Vorschlagsbaum).
Arbeitet ausschließlich in einem temporären Verzeichnis.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

WORDS = ("Rechnung Vertrag Steuer Projekt Angebot Protokoll Prompt Agent Urlaub Versicherung Budget Lieferant "
         "Bericht Kunde Meeting Konzept Foto Notiz Backup Modell").split()


def make_files(base: Path, n: int) -> None:
    import pymupdf

    rnd = random.Random(1)
    for i in range(n):
        d = base / f"Ordner_{i % 40:02d}" / f"Unter_{i % 7}"
        d.mkdir(parents=True, exist_ok=True)
        w = rnd.sample(WORDS, 3)
        if i % 50 == 0:  # 2 % mehrseitige PDFs
            doc = pymupdf.open()
            for p in range(3):
                doc.new_page().insert_text((50, 50), f"{' '.join(w)} Seite {p + 1}")
            doc.save(d / f"{w[0]}_{i}.pdf")
        else:
            (d / f"{w[0]}_{w[1]}_{i}.txt").write_text(" ".join(rnd.choices(WORDS, k=40)), encoding="utf-8")


def timed(label: str, fn, *a, **kw):
    t0 = time.perf_counter()
    r = fn(*a, **kw)
    dt = time.perf_counter() - t0
    print(f"  {label:<44} {dt * 1000:9.0f} ms")
    return r, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=20000)
    ap.add_argument("--rows", type=int, default=500000)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="fdv-bench-"))
    src = tmp / "platte"
    cfg = tmp / "fdv.yaml"
    cfg.write_text(f"""
server: {{data_dir: "{tmp / 'data'}"}}
target: {{root: "{tmp / 'ziel'}"}}
llm: {{provider: rules}}
analysis: {{ocr: false, thumbnails_mode: smart}}
computers:
  - id: pc
    name: Benchmark-PC
    volumes: [{{id: pc-c, name: "C:", path: "{src}"}}]
""", encoding="utf-8")
    os.environ["FDV_CONFIG"] = str(cfg)

    from app import db, jobs
    from app.agents import analysis_agent, scan_agent

    db.init_db()
    print(f"Testordner: {tmp}")
    print(f"\n1) {a.files:,} echte Dateien".replace(",", "."))
    _, t_make = timed("Dateien anlegen", make_files, src, a.files)

    class J(jobs.Job):
        def __init__(self):
            super().__init__(0, "bench")

        def update(self, *x, **k):
            pass

    stats, t_scan = timed("Einlesen (Scan + Duplikate)", scan_agent.run, J(), {})
    print(f"     → {a.files / t_scan:,.0f} Dateien/s".replace(",", "."))
    stats, t_an = timed("Analyse (Text, Regeln, Miniaturen smart)", analysis_agent.run, J(), {})
    print(f"     → {a.files / t_an:,.0f} Dateien/s · Miniaturen: {stats.get('miniaturen')}".replace(",", "."))

    print(f"\n2) Datenbank auf {a.rows:,} Einträge auffüllen".replace(",", "."))
    rnd = random.Random(2)
    groups = [("Privat", "Steuern"), ("Beruf", "Projekte"), ("GenAI", "Prompts & Prompt-Bibliothek"), ("Sonstiges", "Unsortiert")]

    def fill():
        with db.tx() as c:
            rows = []
            for i in range(a.rows - a.files):
                g, cat = groups[i % 4]
                w = rnd.sample(WORDS, 3)
                rel = f"Archiv_{i % 300}/Jahr_{2010 + i % 15}/Projekt_{i % 23}/{w[0]}_{i}.pdf"
                rows.append(("pc", "pc-c", f"/x/{rel}", rel, f"{w[0]}_{i}.pdf", ".pdf", "PDF", "application/pdf",
                             rnd.randint(1000, 5_000_000), f"20{10 + i % 15}-0{1 + i % 9}-15T10:00:00+00:00",
                             " ".join(rnd.choices(WORDS, k=60)), cat, g, rnd.randint(0, 100),
                             f"0{1 + i % 4}_{g}/{cat}/20{10 + i % 15}/{w[0]}_{i}.pdf", "analysiert"))
                if len(rows) == 20000:
                    c.executemany("""INSERT INTO files(computer_id, volume_id, path, rel_path, name, ext, file_type, mime, size, mtime,
                                     text_excerpt, category, group_name, importance, suggested_path, status)
                                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
                    rows.clear()
            if rows:
                c.executemany("""INSERT INTO files(computer_id, volume_id, path, rel_path, name, ext, file_type, mime, size, mtime,
                                 text_excerpt, category, group_name, importance, suggested_path, status)
                                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            c.execute("ANALYZE")

    timed("Einfügen", fill)
    timed("Suchindex aufbauen", db.fts_rebuild)

    from fastapi.testclient import TestClient
    from app.main import app

    print("\n3) Antwortzeiten der Oberfläche")
    with TestClient(app) as cl:
        for label, url in [
            ("Liste (Wichtigkeit, 150 Einträge)", "/api/files?limit=150"),
            ("Liste nach Speicherdatum", "/api/files?limit=150&sort=mtime"),
            ("Filter Bereich + Kategorie", "/api/files?limit=150&group=Beruf&category=Projekte"),
            ("Suche Dateiname", "/api/files?limit=150&q=Konzept_12"),
            ("Volltextsuche im Inhalt", "/api/files?limit=150&q=Lieferant%20Budget"),
            ("Ordnerbaum (oberste Ebene)", "/api/tree?volume=pc-c"),
            ("Ordnerbaum (Unterordner)", "/api/tree?volume=pc-c&prefix=Archiv_7"),
            ("Filterwerte (Facetten)", "/api/facets"),
            ("Übersicht / Statistik", "/api/stats"),
            ("Vorschlagsbaum", "/api/proposal/tree"),
        ]:
            r, _ = timed(label, cl.get, url)
            assert r.status_code == 200, (url, r.text[:200])
        print("  – zweiter Aufruf (zwischengespeichert) –")
        for label, url in [("Filterwerte (Facetten)", "/api/facets"), ("Übersicht / Statistik", "/api/stats"),
                           ("Vorschlagsbaum", "/api/proposal/tree")]:
            timed(label, cl.get, url)
    print(f"\nFertig. Testordner kann gelöscht werden: {tmp}")


if __name__ == "__main__":
    main()
