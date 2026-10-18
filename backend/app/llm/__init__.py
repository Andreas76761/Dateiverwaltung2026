"""LLM-Schicht: austauschbare Provider (Anthropic Claude, Ollama lokal, Regeln offline).

Alle Provider liefern dasselbe Ergebnisformat:
{category_id, labels[], summary, subfolder, confidence, importance}
"""
from __future__ import annotations

import json
import logging

from ..categories import CATEGORIES, find_category
from ..config import get_settings

log = logging.getLogger("fdv.llm")

CATEGORY_LIST = "\n".join(f"- {c.id}: {c.name} [{c.group}]" for c in CATEGORIES)

SYSTEM_PROMPT = f"""Du bist der Analyse-Agent der Anwendung "Future Dateiverwaltung".
Du ordnest einzelne Dateien eines privaten/beruflichen Datenbestands ein, damit der Nutzer
eine neue, saubere Ordnerstruktur in der Cloud bekommt. Du änderst nichts – du schlägst nur vor.

Wähle genau eine der folgenden 50 Kategorien (Angabe der id):
{CATEGORY_LIST}

Regeln:
- Beruf = alles, was erkennbar mit Arbeit/Unternehmen/Kunden zu tun hat. GenAI = Inhalte rund um
  KI/LLMs/Prompts/Agenten/Modelle. Privat = persönliche Angelegenheiten. Sonstiges = Software, System, Archive, Unklares.
- labels: 2–6 kurze deutsche Labels, die für Wiederfinden und Wichtigkeit relevant sind
  (z. B. Vertrag, Rechnung, Frist, Steuer, Vertraulich, Unterschrift, Original, Entwurf, Kunde XY, Projekt XY, Jahr).
- summary: ein deutscher Satz (max. 200 Zeichen), was die Datei ist.
- subfolder: optionaler sinnvoller Unterordnername (z. B. Projekt- oder Firmenname), sonst leer.
- importance: 0–100, wie wichtig es ist, die Datei aufzubewahren und schnell zu finden
  (Urkunden, Verträge, Steuern hoch; temporäre Dateien, Installer niedrig).
- confidence: 0–1, wie sicher die Einordnung ist."""

SCHEMA = {
    "type": "object",
    "properties": {
        "category_id": {"type": "string", "enum": [c.id for c in CATEGORIES]},
        "labels": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "subfolder": {"type": "string"},
        "importance": {"type": "integer"},
        "confidence": {"type": "number"},
    },
    "required": ["category_id", "labels", "summary", "subfolder", "importance", "confidence"],
    "additionalProperties": False,
}


def build_user_prompt(meta: dict, text: str, include_content: bool) -> str:
    lines = [
        f"Dateiname: {meta['name']}",
        f"Pfad: {meta['path']}",
        f"Computer / Festplatte: {meta.get('computer_name', '')} / {meta.get('volume_name', '')}",
        f"Dateityp: {meta.get('file_type')} ({meta.get('ext')}), Größe: {meta.get('size')} Bytes, geändert: {meta.get('mtime')}",
    ]
    if meta.get("page_count"):
        lines.append(f"Seiten/Folien: {meta['page_count']}")
    if include_content and text:
        lines.append("\nInhalt (Auszug):\n<<<\n" + text + "\n>>>")
    elif not include_content:
        lines.append("\n(Inhalt aus Datenschutzgründen nicht übermittelt – nur Metadaten bewerten.)")
    return "\n".join(lines)


def get_provider(name: str | None = None):
    name = (name or get_settings().llm["provider"]).lower()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider()
    from .rules_provider import RulesProvider
    return RulesProvider()


def normalize(result: dict) -> dict:
    cat = find_category(result.get("category_id") or result.get("category"))
    labels = [str(l).strip()[:40] for l in (result.get("labels") or []) if str(l).strip()][:8]
    try:
        imp = int(result.get("importance", 50))
    except (TypeError, ValueError):
        imp = 50
    try:
        conf = float(result.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "category_id": cat.id,
        "labels": labels,
        "summary": str(result.get("summary") or "")[:300],
        "subfolder": str(result.get("subfolder") or "")[:60],
        "importance": max(0, min(100, imp)),
        "confidence": max(0.0, min(1.0, conf)),
    }


def analyze(meta: dict, text: str) -> tuple[dict, str]:
    """Analysiert mit dem konfigurierten Provider; fällt bei Fehlern auf Regeln zurück."""
    provider = get_provider()
    try:
        return normalize(provider.analyze(meta, text)), provider.name
    except Exception as exc:
        log.warning("LLM-Provider %s fehlgeschlagen (%s) – Fallback auf Regeln", provider.name, exc)
        from .rules_provider import RulesProvider
        rp = RulesProvider()
        return normalize(rp.analyze(meta, text)), f"{rp.name} (Fallback)"


def parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])
