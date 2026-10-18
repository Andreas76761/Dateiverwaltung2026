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


# Schlüsselwort → Kategorien; Index nach den ersten zwei Zeichen für EINEN Durchlauf über den Text
_KW_CATS: dict[str, list[str]] = {}
for _c in CATEGORIES:
    for _k in _c.keywords:
        _KW_CATS.setdefault(_k, []).append(_c.id)
_BY_PREFIX: dict[str, list[str]] = {}
for _k in _KW_CATS:
    _BY_PREFIX.setdefault(_k[:2], []).append(_k)
# Wortanfang ("nda" nicht in "andreas"); Wortende bleibt offen ("steuer" → "steuerbescheid")
_WORD_START = re.compile(r"(?<![a-z0-9äöüß])(?=\S)")


def keyword_hits(hay: str) -> dict[str, int]:
    """Wie oft jedes Schlüsselwort an einem Wortanfang vorkommt – ein Durchlauf statt einer Suche je Schlüsselwort."""
    hits: dict[str, int] = {}
    for m in _WORD_START.finditer(hay):
        i = m.start()
        for kw in _BY_PREFIX.get(hay[i:i + 2], ()):
            if hay.startswith(kw, i):
                hits[kw] = hits.get(kw, 0) + 1
    return hits


META_LINE = re.compile(r"^\[(?:raw-foto|iphone-/heic-foto|foto) · [^\]]*\]\s*")


class RulesProvider:
    name = "regeln"

    def analyze(self, meta: dict, text: str) -> dict:
        name = meta["name"].lower()
        path = meta["path"].lower().replace("\\", "/")
        ext = (meta.get("ext") or "").lower()
        hay_name = f"{name} {path}"
        hay_text = text[:12000].lower()

        name_hits = keyword_hits(hay_name)
        text_hits = keyword_hits(hay_text) if hay_text else {}
        # Foto-Metadaten (Aufnahmedatum, Kamera) sind kein Dokumenttext – zählen nicht als „Bild mit viel Text“
        content_len = len(META_LINE.sub("", hay_text, count=1))
        scores: dict[str, float] = {}
        for c in CATEGORIES:
            s = 0.0
            if ext and ext in c.exts:
                # Bild mit OCR-Text (z. B. gescannter Beleg) oder Video mit Titel → Inhalt zählt mehr als die Endung
                s += 1.0 if (meta.get("file_type") in ("Bild", "Video") and content_len > 80) else 3.0
            for kw in c.keywords:
                if kw in name_hits:
                    s += 2.5
                if kw in text_hits:
                    s += min(text_hits[kw], 5) * 0.6
            if c.id == "p_fotos" and meta.get("file_type") == "Bild" and content_len > 80:
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
