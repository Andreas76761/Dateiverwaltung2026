"""Skill: Wichtigkeit 0..100 berechnen (Sortierung "nach Wichtigkeit")."""
from __future__ import annotations

from datetime import datetime, timezone

from ..categories import IMPORTANT_LABELS, Category

TYPE_BONUS = {"PDF": 8, "Textdokument": 7, "Tabelle": 6, "Präsentation": 6, "E-Mail": 5, "Bild": 2,
              "Quellcode": 3, "Text & Notizen": 3, "Programm": -10, "Archiv": -2}


def score(cat: Category, labels: set[str], file_type: str, mtime: str | None, dup_count: int,
          is_primary: bool, llm_hint: int | None, pinned: bool) -> tuple[int, str]:
    reasons = [f"Kategorie {cat.name} (+{cat.weight})"]
    s = cat.weight
    lb = sum(IMPORTANT_LABELS.get(l, 0) for l in labels)
    lb = min(lb, 30)
    if lb:
        s += lb
        reasons.append(f"Labels (+{lb})")
    tb = TYPE_BONUS.get(file_type, 0)
    s += tb
    if mtime:
        try:
            age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(mtime)).days
            rec = 12 if age_days < 90 else 8 if age_days < 365 else 4 if age_days < 3 * 365 else 0
            if rec:
                s += rec
                reasons.append(f"aktuell (+{rec})")
        except ValueError:
            pass
    if llm_hint is not None:
        adj = round((llm_hint - 50) / 5)  # LLM-Einschätzung ±10
        s += adj
        if adj:
            reasons.append(f"LLM-Einschätzung ({adj:+d})")
    if dup_count > 1 and not is_primary:
        s -= 15
        reasons.append("Duplikat (−15)")
    if "Ältere Version" in labels:
        s -= 10
        reasons.append("ältere Version (−10)")
    if pinned:
        s += 25
        reasons.append("angeheftet (+25)")
    return max(0, min(100, s)), ", ".join(reasons)
