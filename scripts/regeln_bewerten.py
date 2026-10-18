"""Trefferquote der Offline-Einordnung auf dem Prüfsatz (backend/tests/data/einordnung.yaml).

    cd backend && python ../scripts/regeln_bewerten.py          # Übersicht + Fehlzuordnungen
    python ../scripts/regeln_bewerten.py --alle                  # jede Datei einzeln

Neue Fälle (z. B. aus dem Probelauf-Bericht) in die YAML-Datei eintragen und erneut prüfen.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.categories import BY_ID  # noqa: E402
from app.llm.rules_provider import RulesProvider  # noqa: E402
from app.skills.filetype import detect  # noqa: E402

CASES = Path(__file__).resolve().parents[1] / "backend" / "tests" / "data" / "einordnung.yaml"


def evaluate() -> tuple[float, list[dict]]:
    rows = []
    rp = RulesProvider()
    for name, folder, text, want in yaml.safe_load(CASES.read_text(encoding="utf-8")):
        ext, ftype, _ = detect(name)
        r = rp.analyze({"name": name, "path": f"{folder}/{name}", "ext": ext, "file_type": ftype}, text or "")
        rows.append({"name": name, "want": want, "got": r["category_id"], "conf": r["confidence"], "ok": r["category_id"] == want})
    acc = sum(r["ok"] for r in rows) / len(rows)
    return acc, rows


def main():
    acc, rows = evaluate()
    wrong = [r for r in rows if not r["ok"]]
    print(f"Trefferquote: {acc:.0%} ({len(rows) - len(wrong)} von {len(rows)})")
    grp = sum(BY_ID[r["want"]].group == BY_ID[r["got"]].group for r in rows) / len(rows)
    print(f"Bereich (Privat/Beruf/GenAI/Sonstiges) richtig: {grp:.0%}")
    conf_ok = [r["conf"] for r in rows if r["ok"]]
    conf_bad = [r["conf"] for r in wrong]
    if conf_ok and conf_bad:
        print(f"Ø Sicherheit richtig {sum(conf_ok) / len(conf_ok):.0%} · falsch {sum(conf_bad) / len(conf_bad):.0%}")
    for r in (rows if "--alle" in sys.argv else wrong):
        mark = "✓" if r["ok"] else "✗"
        print(f" {mark} {r['name'][:48]:48} erwartet {BY_ID[r['want']].name:28} erhalten {BY_ID[r['got']].name:28} {r['conf']:.0%}")
    print("Häufigste Verwechslungen:", Counter(f"{BY_ID[r['want']].name} → {BY_ID[r['got']].name}" for r in wrong).most_common(5))


if __name__ == "__main__":
    main()
