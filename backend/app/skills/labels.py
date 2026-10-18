"""Skill: Regelbasierte Labels (ergänzt die LLM-Labels)."""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Vertrag", re.compile(r"\b(vertrag|vereinbarung|agreement|contract)\b", re.I)),
    ("Rechnung", re.compile(r"\b(rechnung|invoice|rechnungsnummer|rechnungsbetrag)\b", re.I)),
    ("Steuer", re.compile(r"\b(steuer|finanzamt|steuernummer|ust-?id)\b", re.I)),
    ("Frist", re.compile(r"\b(frist|fällig|spätestens|deadline|bis zum|kündigungsfrist)\b", re.I)),
    ("Unterschrift", re.compile(r"\b(unterschrift|unterzeichnet|signed|signature)\b", re.I)),
    ("Vertraulich", re.compile(r"\b(vertraulich|confidential|geheim|intern|nda)\b", re.I)),
    ("Finanzen", re.compile(r"\bDE\d{2}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{4}[ ]?\d{2}\b|\biban\b", re.I)),
    ("Personenbezogen", re.compile(r"\b(geburtsdatum|geb\.|sozialversicherungsnummer|personalnummer|steuer-?id)\b", re.I)),
    ("Kündigung", re.compile(r"\bkündig", re.I)),
    ("Bescheid", re.compile(r"\bbescheid\b", re.I)),
    ("Versicherung", re.compile(r"\b(versicherung|police|versicherungsnummer)\b", re.I)),
    ("Gesundheit", re.compile(r"\b(befund|diagnose|arzt|patient)\b", re.I)),
    ("Rechtlich", re.compile(r"\b(gericht|anwalt|klage|§\s?\d+|bgb|dsgvo)\b", re.I)),
    ("Zeugnis", re.compile(r"\b(zeugnis|zertifikat|certificate)\b", re.I)),
    ("Ausweis", re.compile(r"\b(personalausweis|reisepass|führerschein|aufenthaltstitel)\b", re.I)),
    ("Präsentation", re.compile(r"--- Folie \d+ ---")),
    ("KI", re.compile(r"\b(llm|gpt|claude|prompt|embedding|genai|künstliche intelligenz)\b", re.I)),
    ("Anhang", re.compile(r"Anhänge: ")),
    ("Entwurf", re.compile(r"\b(entwurf|draft|v0\.\d|wip)\b", re.I)),
]
AMOUNT = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}\s?(?:€|EUR)|(?:€|EUR)\s?\d", re.I)
YEAR = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")


def rule_labels(name: str, text: str) -> set[str]:
    hay = f"{name} {text[:15000]}"
    labels = {lbl for lbl, rx in PATTERNS if rx.search(hay)}
    if AMOUNT.search(hay):
        labels.add("Betrag")
    if re.search(r"(kopie|copy|\(\d\)|_alt|_old|backup)", name, re.I):
        labels.add("Mögliche Kopie")
    return labels


def guess_year(name: str, text: str, mtime_year: int) -> int:
    m = YEAR.search(name)
    if m:
        return int(m.group(1))
    years = [int(y) for y in YEAR.findall(text[:3000])]
    plausible = [y for y in years if y <= mtime_year + 1]
    return max(plausible) if plausible else mtime_year
