"""Probelauf auf einem echten Computer – sicher, klein, mit Bericht.

    python scripts/probelauf.py                         # Ordner "Dokumente" des Benutzers, max. 2.000 Dateien
    python scripts/probelauf.py --ordner "D:/Projekte" --ordner "C:/Users/andreas/OneDrive" --max-dateien 5000
    python scripts/probelauf.py --claude --limit 1      # zusätzlich Claude-Analyse (nur unklare Dateien, max. 1 $)
    python scripts/probelauf.py --kopieren              # Kopien wirklich anlegen (sonst nur Trockenlauf)

Was passiert:
1. Einlesen der angegebenen Ordner (nur lesend), Cloud-Platzhalter werden erkannt und nicht gelesen.
2. Analyse (Offline-Regeln; mit --claude zusätzlich Claude für unklare Dateien – nach Kostenbestätigung).
3. Vorschlag der neuen Ordnerstruktur.
4. Kopie als TROCKENLAUF (es wird nichts geschrieben) – nur mit --kopieren in einen Probe-Zielordner
   (dann mit PDF-Prüfbericht im Zielordner unter _Prüfberichte).
5. Zweites Einlesen: prüft die Änderungserkennung und wie schnell ein erneuter Lauf ist.
6. Programme & LLMs dieses Computers (Inventar, Modelle, Empfehlungen) – nur lesend, abschaltbar mit --ohne-inventar.
7. Exporte als Excel (Vorschlag, Statistik, ähnliche Dateien, Programme) neben den Bericht.
Vorher/Nachher-Abgleich aller gelesenen Quelldateien (Größe + Änderungsdatum) beweist: nichts verändert.

Alle Daten des Probelaufs liegen getrennt in ~/.future-dateiverwaltung/probelauf (eigene Datenbank).
Ergebnis: probelauf-bericht.md (und .json) – mit --anonym ohne Datei- und Ordnernamen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

HOME = Path.home()
DATA = HOME / ".future-dateiverwaltung" / "probelauf"

EXCLUDE_DIRS = [".git", "node_modules", "__pycache__", "$RECYCLE.BIN", "System Volume Information", ".Trash", ".Trashes",
                "AppData", ".cache", "venv", ".venv", "OneDriveTemp", ".dropbox.cache",
                "Program Files", "Program Files (x86)", "ProgramData", ".tmp.drivedownload"]


def default_folder() -> Path:
    for name in ("Documents", "Dokumente", "Eigene Dokumente"):
        p = HOME / name
        if p.is_dir():
            return p
    return HOME


def find_cloud_target() -> Path:
    from app.connectors import cloud

    found = cloud.detect()
    base = Path(found[0]["path"]) if found else HOME
    return base / "Future-Dateiverwaltung-Probelauf"


def snapshot(paths: list[str]) -> dict[str, tuple[int, int]]:
    out = {}
    for p in paths:
        try:
            st = os.stat(p)  # nur Metadaten – löst bei Cloud-Platzhaltern keinen Download aus
            out[p] = (st.st_size, int(st.st_mtime))
        except OSError:
            out[p] = (-1, -1)
    return out


class Report:
    def __init__(self, anonym: bool):
        self.anonym = anonym
        self.lines: list[str] = []
        self.data: dict = {}

    def name(self, s: str) -> str:
        if not self.anonym or not s:
            return s
        ext = Path(s).suffix
        return f"datei-{hashlib.sha1(s.encode()).hexdigest()[:8]}{ext}"

    def path(self, s: str) -> str:
        if not self.anonym or not s:
            return s
        parts = s.replace("\\", "/").split("/")
        # Struktur der neuen Ablage (01_Privat/Steuern/2024) bleibt lesbar, nur der Dateiname wird ersetzt
        return "/".join(parts[:-1] + [self.name(parts[-1])])

    @staticmethod
    def local(s: str) -> str:
        """Benutzerverzeichnis als ~ zeigen (kein Benutzername im Bericht)."""
        home = str(HOME)
        return "~" + s[len(home):] if s.startswith(home) else s

    def h(self, t: str):
        self.lines += ["", f"## {t}", ""]

    def p(self, t: str = ""):
        self.lines.append(t)

    def table(self, head: list[str], rows: list[list]):
        self.lines.append("| " + " | ".join(head) + " |")
        self.lines.append("|" + "---|" * len(head))
        for r in rows:
            self.lines.append("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |")


def _has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def step(title: str):
    print(f"\n▶ {title}", flush=True)


def run_job(fn, params: dict, label: str) -> tuple[dict, float]:
    from app import jobs

    from app import db

    kind = {"Einlesen": "scan", "Zweites Einlesen": "scan", "Analyse": "analyze", "Vorschlag": "propose", "Kopie": "copy",
            "Inventar": "inventory"}.get(label, "probelauf")
    with db.tx() as c:  # echter Job-Eintrag – Kopierprotokoll und Prüfbericht beziehen sich darauf
        job_id = c.execute("INSERT INTO jobs(kind, status, params, created_at, started_at) VALUES (?, 'läuft', ?, ?, ?)",
                           (kind, json.dumps(params), db.now(), db.now())).lastrowid

    class J(jobs.Job):
        def __init__(self):
            super().__init__(job_id, kind)
            self._last = 0.0

        def update(self, progress=None, total=None, message=None, **stats):
            self.stats.update(stats)
            if message and time.time() - self._last > 2:
                print(f"   {message}", flush=True)
                self._last = time.time()

    t0 = time.perf_counter()
    stats = fn(J(), params) or {}
    dt = time.perf_counter() - t0
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='fertig', finished_at=?, stats=? WHERE id=?",
                  (db.now(), json.dumps(stats, ensure_ascii=False, default=str), job_id))
    stats["_job_id"] = job_id
    print(f"   ✓ {label} in {dt:.1f} s", flush=True)
    return stats, dt


def main():
    ap = argparse.ArgumentParser(description="Future Dateiverwaltung – Probelauf")
    ap.add_argument("--ordner", action="append", help="Zu lesender Ordner (mehrfach möglich). Standard: Dokumente")
    ap.add_argument("--ziel", help="Probe-Zielordner für --kopieren (Standard: Cloud-Ordner/Future-Dateiverwaltung-Probelauf)")
    ap.add_argument("--max-dateien", type=int, default=2000, help="Höchstens so viele Dateien je Ordner (0 = alle)")
    ap.add_argument("--claude", action="store_true", help="Zusätzlich Claude-Analyse (ANTHROPIC_API_KEY nötig)")
    ap.add_argument("--modell", default="claude-opus-5-5")
    ap.add_argument("--limit", type=float, default=1.0, help="Kostenlimit in USD für --claude")
    ap.add_argument("--inhalte", action="store_true", help="Mit --claude auch Textauszüge senden (sonst nur Metadaten)")
    ap.add_argument("--ja", action="store_true", help="Kostenabfrage bei --claude automatisch bestätigen")
    ap.add_argument("--kopieren", action="store_true", help="Kopien WIRKLICH anlegen (in den Probe-Zielordner)")
    ap.add_argument("--anonym", action="store_true", help="Bericht ohne Datei- und Ordnernamen")
    ap.add_argument("--neu", action="store_true", help="Probelauf-Datenbank vorher leeren")
    ap.add_argument("--ohne-inventar", action="store_true", help="Programme & LLMs dieses Computers nicht erfassen")
    a = ap.parse_args()

    folders = [Path(f).expanduser().resolve() for f in (a.ordner or [str(default_folder())])]
    for f in folders:
        if not f.is_dir():
            sys.exit(f"Ordner nicht gefunden: {f}")
    if a.neu and DATA.exists():
        import shutil
        shutil.rmtree(DATA)  # nur die eigene Probelauf-Datenbank
    DATA.mkdir(parents=True, exist_ok=True)

    os.environ["FDV_CONFIG"] = str(DATA / "probelauf.yaml")
    from app.connectors import cloud  # noqa: E402 (braucht noch keine Konfiguration)

    target = Path(a.ziel).expanduser() if a.ziel else find_cloud_target()
    import yaml

    cfg = {
        "server": {"data_dir": str(DATA / "daten")},
        "llm": {"provider": "anthropic" if a.claude else "rules", "anthropic_model": a.modell, "mode": "unklare",
                "max_cost_usd": a.limit, "send_content_to_cloud": a.inhalte},
        "analysis": {"thumbnails_mode": "smart", "thumbs_budget_gb": 2},
        "target": {"root": str(target), "structure": "{group}/{category}/{year}"},
        "cloud": {"download_online_only": False},
        "scan": {"exclude_dirs": EXCLUDE_DIRS, "exclude_ext": [".tmp", ".lock", ".part", ".crdownload"], "max_files": a.max_dateien},
        "computers": [{"id": "dieser-pc", "name": platform.node() or "Dieser Computer", "os": f"{platform.system()} {platform.release()}",
                       "mode": "local", "volumes": [
                           {"id": f"ordner-{i + 1}", "name": f.name or str(f), "path": str(f),
                            "kind": "cloud" if any(k in str(f).lower() for k in ("onedrive", "google drive", "googledrive", "dropbox", "icloud", "nextcloud", "clouddocs", "cloudstorage")) else "internal"}
                           for i, f in enumerate(folders)]}],
    }
    (DATA / "probelauf.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    from app import db, platform_tools
    from app.agents import analysis_agent, copy_agent, inventory_agent, organizer_agent, scan_agent, software_org
    from app.config import get_settings
    from app.skills import formats, ocr, thumbcache, video

    get_settings.cache_clear()
    db.init_db()
    R = Report(a.anonym)
    started = datetime.now()
    print("Future Dateiverwaltung – Probelauf")
    print(f"Ordner: {', '.join(map(str, folders))}\nDaten des Probelaufs: {DATA}")

    # ---------------------------------------------------------------- 1 Einlesen
    step("1/6 Einlesen (nur lesend)")
    scan, t_scan = run_job(scan_agent.run, {}, "Einlesen")
    paths = [r["path"] for r in db.query("SELECT path FROM files WHERE missing=0")]
    before = snapshot(paths)

    # ---------------------------------------------------------------- 2 Analyse
    step("2/6 Analyse (inkl. Duplikate und ähnliche Dateien)")
    est = None
    if a.claude:
        from app.llm import costs
        files, _, _ = analysis_agent.select_files({})
        est = costs.estimate(files, mode="unklare")
        print(f"   Kostenschätzung Claude ({a.modell}): bis {est['kosten_usd']:.2f} $ für {est['an_llm']} von {est['dateien']} Dateien "
              f"(Rest offline) · Limit {a.limit:.2f} $")
        if not a.ja and input("   Fortfahren? [j/N] ").strip().lower() not in ("j", "ja", "y", "yes"):
            print("   Claude übersprungen – Analyse offline.")
            get_settings().llm["provider"] = "rules"
    analysis, t_an = run_job(analysis_agent.run, {"mode": "unklare", "max_cost_usd": a.limit}, "Analyse")

    # ---------------------------------------------------------------- 3 Vorschlag
    step("3/6 Vorschlag der neuen Struktur (virtuell)")
    prop, _ = run_job(organizer_agent.run, {}, "Vorschlag")

    # ---------------------------------------------------------------- 4 Kopie
    step("4/6 Kopie " + ("(ECHT – in den Probe-Zielordner)" if a.kopieren else "(Trockenlauf – es wird nichts geschrieben)"))
    with db.tx() as c:  # nur in der Probelauf-Datenbank: alles freigeben, damit die Kopier-Statistik vollständig ist
        c.execute("UPDATE files SET review_status='freigegeben' WHERE missing=0 AND suggested_path IS NOT NULL")
    copy, t_copy = run_job(copy_agent.run, {"dry_run": not a.kopieren}, "Kopie")

    # ---------------------------------------------------------------- 5 Zweites Einlesen
    step("5/6 Zweites Einlesen (Änderungserkennung)")
    scan2, t_scan2 = run_job(scan_agent.run, {}, "Zweites Einlesen")

    # ---------------------------------------------------------------- 6 Programme & LLMs
    inv, recs, st_models = {}, [], {}
    if not a.ohne_inventar:
        step("6/6 Programme & LLMs dieses Computers (nur lesend)")
        inv, _ = run_job(inventory_agent.run, {"computer_id": "dieser-pc"}, "Inventar")
        recs = software_org.recommendations()
        st_models = next((c for c in software_org.storage()["computers"] if c["id"] == "dieser-pc"), {})

    after = snapshot(paths)
    changed = [p for p in paths if before.get(p) != after.get(p)]

    # ---------------------------------------------------------------- Exporte (nur in den Probelauf-Ordner)
    from app import exports
    out_files = []
    for kind, fname in (("vorschlag", "probelauf-vorschlag.xlsx"), ("statistik", "probelauf-statistik.xlsx"),
                        ("aehnliche", "probelauf-aehnliche.xlsx")) + ((("programme", "probelauf-programme.xlsx"),) if not a.ohne_inventar else ()):
        try:
            title, build = exports.EXPORTS[kind]
            (DATA / fname).write_bytes(exports.to_xlsx(build(), title))
            out_files.append(DATA / fname)
        except Exception as exc:
            print(f"   Export {fname} fehlgeschlagen: {exc}")
    if a.kopieren:
        job = exports.copy_job(copy.get("_job_id"))
        if job:
            (DATA / "probelauf-pruefbericht.pdf").write_bytes(exports.report_pdf(job))
            out_files.append(DATA / "probelauf-pruefbericht.pdf")

    # ---------------------------------------------------------------- Bericht
    q = db.query
    total = q("SELECT COUNT(*) n, COALESCE(SUM(size),0) b, SUM(online_only) o, SUM(status='analysiert') an, SUM(status='fehler') fe, "
              "SUM(dup_count>1 AND is_primary=0) d, COALESCE(SUM(CASE WHEN dup_count>1 AND is_primary=0 THEN size END),0) db_ "
              "FROM files WHERE missing=0")[0]
    gb = lambda b: f"{(b or 0) / 1024 ** 3:.2f} GB" if (b or 0) > 1024 ** 3 else f"{(b or 0) / 1024 ** 2:.1f} MB"
    long_paths = q("SELECT COUNT(*) n FROM files WHERE length(path) >= 240")[0]["n"]
    errs = (scan.get("fehlerliste") or [])[:25]
    file_errs = q("SELECT name, error FROM files WHERE error IS NOT NULL LIMIT 25")

    R.p("# Future Dateiverwaltung – Probelauf-Bericht")
    R.p(f"{started:%d.%m.%Y %H:%M} · {platform.node()} · {'Kopie echt' if a.kopieren else 'Trockenlauf (nichts geschrieben)'}")
    R.h("Ergebnis auf einen Blick")
    ok = not changed
    R.p(f"- **Quelldateien unverändert:** {'✅ ja' if ok else '❌ NEIN'} ({len(paths):,} Dateien vorher/nachher verglichen)".replace(",", "."))
    R.p(f"- **Dateien:** {total['n']:,} ({gb(total['b'])}) in {len(folders)} Ordner(n){' – Dateilimit erreicht' if scan.get('limit_erreicht') else ''}".replace(",", "."))
    R.p(f"- **Analysiert:** {total['an'] or 0:,} · Fehler: {total['fe'] or 0} · Lesefehler beim Einlesen: {scan.get('fehler', 0)}".replace(",", "."))
    R.p(f"- **Nur online (Cloud-Platzhalter, nicht gelesen):** {total['o'] or 0}")
    R.p(f"- **Duplikate:** {total['d'] or 0} überzählige Exemplare ({gb(total['db_'])})")
    R.p(f"- **Neue Struktur:** {prop.get('zielordner', 0)} Zielordner für {prop.get('dateien_im_vorschlag', 0)} Dateien")
    R.p(f"- **Kopie:** {copy.get('geplant', 0)} geplant · {copy.get('kopiert', 0)} kopiert · {copy.get('übersprungen', 0)} übersprungen "
        f"({copy.get('nur_online', 0)} nur online) · {copy.get('fehler', 0)} Fehler · {gb(copy.get('bytes'))}")
    sim = q("SELECT sim_kind k, COUNT(DISTINCT sim_group) g, COUNT(*) n FROM files WHERE missing=0 AND sim_group IS NOT NULL GROUP BY 1")
    R.p(f"- **Ähnliche Dateien:** " + (", ".join(f"{r['k']}: {r['g']} {'Gruppe' if r['g'] == 1 else 'Gruppen'} ({r['n']} Dateien)" for r in sim)
                                         or "keine gefunden"))
    ch = scan2.get("änderungen") or {}
    speed = f" ({t_scan / t_scan2:.0f}× so schnell wie das erste)" if t_scan > 2 and t_scan2 > 0 else ""
    R.p(f"- **Zweites Einlesen:** {t_scan2:.1f} s{speed} · "
        f"erkannt: {ch.get('neu', 0)} neu, {ch.get('geändert', 0)} geändert, {ch.get('fehlt', 0)} fehlen"
        + (" – zwischendurch wurden Dateien bearbeitet" if any(ch.values()) else " – wie erwartet keine Änderungen"))
    if not a.ohne_inventar:
        R.p(f"- **Programme & LLMs:** {inv.get('einträge', 0)} Einträge · lokale Modelle {gb(st_models.get('models'))} "
            f"({st_models.get('models_n', 0)}) · {len([r for r in recs if r['status'] == 'offen'])} Empfehlungen")
    R.p(f"- **Zeiten:** Einlesen {t_scan:.1f} s · Analyse {t_an:.1f} s ({(total['an'] or 0) / max(t_an, 0.01):.1f} Dateien/s) · Kopie {t_copy:.1f} s")
    if a.claude:
        R.p(f"- **Claude:** {analysis.get('llm', 0)} Aufrufe · {analysis.get('kosten_usd', 0):.4f} $ · "
            f"{analysis.get('nur_regeln', 0)} offline sicher · Fallback {analysis.get('llm_fallback', 0)}"
            + (f" · Fehler: {analysis.get('llm_fehler')}" if analysis.get("llm_fehler") else ""))
        if est:
            R.p(f"  Schätzung vorher: {est['kosten_usd']:.2f} $ für {est['an_llm']} Dateien")

    R.h("Umgebung")
    R.table(["Prüfpunkt", "Ergebnis"], [
        ["Betriebssystem", f"{platform.system()} {platform.release()} ({platform.machine()})"],
        ["Python", platform.python_version()],
        ["LibreOffice (Miniaturen PPTX/DOCX/XLSX)", platform_tools.soffice() or "❌ nicht gefunden"],
        ["Tesseract (OCR)", (platform_tools.tesseract() or "❌ nicht gefunden") + (f" · Sprachen: {ocr.languages()}" if ocr.available() else "")],
        ["ffmpeg (Video-Standbilder, Audio-Wellenform)", video.ffmpeg_exe() or "❌ nicht gefunden"],
        ["HEIC (iPhone-Fotos)", "✅ pillow-heif" if formats.HEIF_OK else ("macOS sips" if shutil.which("sips") else "❌ pillow-heif fehlt")],
        ["RAW-Kamerabilder", "✅ rawpy" if _has("rawpy") else "eingebettete Vorschau (rawpy fehlt)"],
        ["Audio-Tags & Cover", "✅ mutagen" if formats.MUTAGEN_OK else "nur Dauer über ffmpeg (mutagen fehlt)"],
        ["7z/RAR-Archive", formats._seven_zip() or "– (7-Zip nicht gefunden; ZIP/TAR gehen immer)"],
        ["Erkannte Cloud-Ordner", ", ".join(f"{c['provider']}: {R.local(c['path'])}" for c in cloud.detect()) or "–"],
        ["Gelesene Ordner", ", ".join(R.local(str(f)) for f in folders)],
        ["Probe-Zielordner", R.local(str(target)) + ("" if a.kopieren else " (im Trockenlauf nicht angelegt)")],
        ["Pfade ≥ 240 Zeichen", long_paths],
        ["Miniaturen-Cache", gb(thumbcache.usage()["total_bytes"])],
    ])

    R.h("Bereiche (Vorschlag Privat / Beruf / GenAI / Sonstiges)")
    R.table(["Bereich", "Dateien", "Größe"], [[r["k"] or "–", r["n"], gb(r["b"])] for r in
            q("SELECT group_name k, COUNT(*) n, SUM(size) b FROM files WHERE missing=0 GROUP BY 1 ORDER BY 2 DESC")])
    R.h("Top-Kategorien")
    R.table(["Kategorie", "Bereich", "Dateien", "Ø Wichtigkeit", "Ø Sicherheit"], [
        [r["category"], r["group_name"], r["n"], r["imp"], f"{(r['conf'] or 0) * 100:.0f} %"] for r in
        q("SELECT category, group_name, COUNT(*) n, ROUND(AVG(importance)) imp, AVG(confidence) conf FROM files "
          "WHERE missing=0 GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20")])
    R.h("Dateitypen")
    R.table(["Typ", "Dateien", "Größe", "mit Miniatur"], [[r["file_type"], r["n"], gb(r["b"]), r["t"]] for r in
            q("SELECT file_type, COUNT(*) n, SUM(size) b, SUM((SELECT COUNT(*) FROM thumbnails t WHERE t.file_id=f.id) > 0) t "
              "FROM files f WHERE missing=0 GROUP BY 1 ORDER BY 2 DESC LIMIT 20")])
    fmt_rows = q("""SELECT CASE WHEN lower(ext) IN ('.heic','.heif','.avif','.hif') THEN 'HEIC (iPhone)'
                     WHEN lower(ext) IN ('.cr2','.cr3','.nef','.arw','.dng','.raf','.orf','.rw2','.pef','.srw','.raw') THEN 'RAW'
                     WHEN lower(ext) IN ('.tif','.tiff') THEN 'TIFF' WHEN file_type='Archiv' THEN 'Archiv'
                     WHEN lower(ext) IN ('.key','.pages','.numbers') THEN 'Keynote/Pages/Numbers' WHEN file_type='Audio' THEN 'Audio' END k,
                     COUNT(*) n, SUM((SELECT COUNT(*) FROM thumbnails t WHERE t.file_id=f.id) > 0) t,
                     SUM(COALESCE(length(text_excerpt), 0) + COALESCE(length(ocr_text), 0) > 0) tx
                     FROM files f WHERE missing=0 GROUP BY 1 HAVING k IS NOT NULL ORDER BY 2 DESC""")
    if fmt_rows:
        R.h("Weitere Formate")
        R.table(["Format", "Dateien", "mit Vorschau", "mit Inhalt/Metadaten"], [[r["k"], r["n"], r["t"], r["tx"]] for r in fmt_rows])
    if sim:
        R.h("Ähnliche Dateien (Beispiele)")
        R.table(["Art", "Empfehlung (★)", "Weitere Dateien der Gruppe"], [
            [r["sim_kind"], R.name(r["best"]), ", ".join(R.name(x) for x in (r["others"] or "").split("|")[:4])] for r in
            q("""SELECT sim_kind, MAX(CASE WHEN sim_best=1 THEN name END) best,
                 group_concat(CASE WHEN sim_best!=1 THEN name END, '|') others FROM files
                 WHERE missing=0 AND sim_group IS NOT NULL GROUP BY sim_group ORDER BY MAX(importance) DESC LIMIT 12""")])
    if recs:
        R.h("Programme & LLMs – Empfehlungen")
        R.table(["Priorität", "Empfehlung", "Einsparung"], [[r["priority_text"], r["title"], gb(r["saving"]) if r["saving"] else "–"]
                                                           for r in recs[:12]])
    R.h("Wichtigste Dateien und vorgeschlagener neuer Pfad")
    R.table(["Wichtigkeit", "Datei", "Kategorie", "Neuer Pfad (Vorschlag)"], [
        [r["importance"], R.name(r["name"]), r["category"], R.path(r["suggested_path"] or "")] for r in
        q("SELECT importance, name, category, suggested_path FROM files WHERE missing=0 AND is_primary=1 ORDER BY importance DESC LIMIT 25")])
    R.h("Unsichere Einordnungen (Kandidaten für Claude oder manuelle Prüfung)")
    R.table(["Sicherheit", "Datei", "Kategorie"], [[f"{(r['confidence'] or 0) * 100:.0f} %", R.name(r["name"]), r["category"]] for r in
            q("SELECT confidence, name, category FROM files WHERE missing=0 AND is_primary=1 ORDER BY confidence ASC LIMIT 15")])
    if total["o"]:
        R.h("Nur online (nicht gelesen, nicht heruntergeladen)")
        R.table(["Datei", "Ordner", "Kategorie (aus Name/Pfad)"], [[R.name(r["name"]), R.path(r["rel_path"]), r["category"]] for r in
                q("SELECT name, rel_path, category FROM files WHERE online_only=1 LIMIT 20")])
    R.h("Fehler und Hinweise")
    if not errs and not file_errs and ok:
        R.p("Keine.")
    for e in errs:
        R.p(f"- Einlesen: `{R.local(R.path(e) if a.anonym else e)}`")
    for r in file_errs:
        R.p(f"- {R.name(r['name'])}: {r['error']}")
    if changed:
        R.p(f"- ❌ Veränderte Quelldateien: {', '.join(R.name(Path(p).name) for p in changed[:20])}")
    if out_files:
        R.h("Exporte")
        for f in out_files:
            R.p(f"- `{R.local(str(f))}`")
    R.h("Nächste Schritte")
    R.p(f"- Ergebnis in der Oberfläche ansehen: `FDV_CONFIG=\"{DATA / 'probelauf.yaml'}\" python -m uvicorn app.main:app --port 8800` "
        "im Ordner `backend` (Windows PowerShell: `$env:FDV_CONFIG=\"…\"`), dann http://localhost:8800")
    R.p("- Diesen Bericht zurückschicken – daraus werden Regeln, Ausschlüsse und Kategorien für den echten Lauf abgestimmt.")

    R.data = {"scan": scan, "analyse": analysis, "vorschlag": prop, "kopie": copy, "zweites_einlesen": scan2, "inventar": inv,
              "empfehlungen": [{k: r[k] for k in ("type", "priority_text", "title", "saving")} for r in recs],
              "aehnliche": sim, "formate": fmt_rows, "unveraendert": ok, "geaendert": len(changed),
              "dateien": total["n"], "zeit_s": {"einlesen": t_scan, "analyse": t_an, "kopie": t_copy, "zweites_einlesen": t_scan2}}
    out_md, out_json = DATA / "probelauf-bericht.md", DATA / "probelauf-bericht.json"
    out_md.write_text("\n".join(R.lines) + "\n", encoding="utf-8")
    out_json.write_text(json.dumps(R.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\n" + "\n".join(R.lines[:18]))
    print(f"\nBericht: {out_md}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
