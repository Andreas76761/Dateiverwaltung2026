"""Offline-Klassifikator: Schlüsselwörter + Dateiendung + Pfad. Immer verfügbar, kostenlos."""
from __future__ import annotations

import re

from ..categories import CATEGORIES, BY_ID
from ..skills.labels import rule_labels

PATH_HINTS = {
    "Beruf": ["arbeit", "firma", "work", "projekte", "kunden", "büro", "office", "business", "job"],
    "Privat": ["privat", "persönlich", "personal", "familie", "fotos", "pictures", "urlaub"],
    "GenAI": ["genai", "ki", "ai", "llm", "prompts", "models", "ollama", "huggingface", "agents"],
}


_KW: dict[str, re.Pattern] = {}


def _kw(kw: str) -> re.Pattern:
    # Wortanfang muss passen ("nda" nicht in "andreas"), Wortende darf offen sein ("steuer" → "steuerbescheid")
    if kw not in _KW:
        _KW[kw] = re.compile(r"(?<![a-z0-9äöüß])" + re.escape(kw))
    return _KW[kw]


class RulesProvider:
    name = "regeln"

    def analyze(self, meta: dict, text: str) -> dict:
        name = meta["name"].lower()
        path = meta["path"].lower().replace("\\", "/")
        ext = (meta.get("ext") or "").lower()
        hay_name = f"{name} {path}"
        hay_text = text[:12000].lower()

        scores: dict[str, float] = {}
        for c in CATEGORIES:
            s = 0.0
            if ext and ext in c.exts:
                # Bild mit OCR-Text (z. B. gescannter Beleg) oder Video mit Titel → Inhalt zählt mehr als die Endung
                s += 1.0 if (meta.get("file_type") in ("Bild", "Video") and len(hay_text) > 80) else 3.0
            for kw in c.keywords:
                rx = _kw(kw)
                if rx.search(hay_name):
                    s += 2.5
                if hay_text:
                    s += min(len(rx.findall(hay_text)), 5) * 0.6
            if c.id == "p_fotos" and meta.get("file_type") == "Bild" and len(hay_text) > 80:
                s *= 0.4  # Bild mit viel Text ist eher ein gescanntes Dokument
            if s:
                scores[c.id] = s

        segs = set(re.split(r"[/_\-. ]+", path))
        for group, hints in PATH_HINTS.items():
            if any(h in segs for h in hints):
                for cid in scores:
                    if BY_ID[cid].group == group:
                        scores[cid] *= 1.4

        if scores:
            best = max(scores, key=scores.get)
            total = sum(scores.values())
            conf = round(min(0.95, 0.35 + scores[best] / (total + 3)), 2)
        else:
            best, conf = "s_unbekannt", 0.2
        cat = BY_ID[best]

        labels = sorted(rule_labels(meta["name"], text))[:6]
        first = " ".join(text.split()[:24]) if text else ""
        summary = f"{meta.get('file_type', 'Datei')} „{meta['name']}“" + (f": {first}…" if first else "")
        return {
            "category_id": cat.id,
            "labels": labels,
            "summary": summary[:200],
            "subfolder": "",
            "importance": 50,
            "confidence": conf,
        }
