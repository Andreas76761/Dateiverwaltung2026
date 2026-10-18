"""Skill-Registry: Jeder Skill ist ein klar abgegrenzter, wiederverwendbarer Analyse-Schritt.

Die Agenten (scan, analyse, organize, copy, inventory) kombinieren diese Skills.
"""
from . import ocr, thumbnails

SKILLS = [
    {"id": "filetype", "name": "Dateityp-Erkennung", "beschreibung": "Endung & MIME → Dateityp-Gruppe", "agent": "Scan"},
    {"id": "hash", "name": "Duplikat-Erkennung", "beschreibung": "Schnell-Hash + SHA-256, Gruppierung identischer Dateien über alle Computer", "agent": "Scan/Analyse"},
    {"id": "extract", "name": "Textextraktion", "beschreibung": "PDF, PPTX, DOCX, XLSX, ODF, Notebooks, Text & Code", "agent": "Analyse"},
    {"id": "ocr", "name": "OCR (Tesseract)", "beschreibung": "Texterkennung in Bildern und gescannten PDFs", "agent": "Analyse", "verfügbar": None},
    {"id": "thumbnails", "name": "Miniaturansichten", "beschreibung": "Alle Seiten von PDF/PPTX/DOCX/XLSX (via LibreOffice) und Bilder", "agent": "Analyse"},
    {"id": "formats", "name": "Weitere Formate", "beschreibung": "HEIC, RAW, mehrseitige TIFF, ZIP/TAR-Inhalte, Keynote/Pages/Numbers, Audio (Cover, Wellenform, Titel)", "agent": "Analyse"},
    {"id": "classify", "name": "LLM-Klassifikation", "beschreibung": "50 Kategorien → Privat / Beruf / GenAI / Sonstiges, Zusammenfassung", "agent": "Analyse"},
    {"id": "labels", "name": "Labels", "beschreibung": "Wichtige Labels (Vertrag, Frist, Steuer, …) per LLM + Regeln", "agent": "Analyse"},
    {"id": "similarity", "name": "Ähnliche Dateien", "beschreibung": "Ähnliche Fotos (pHash), Versionen (Angebot_v2/_final) und gleicher Inhalt als PDF/DOCX (MinHash)", "agent": "Ähnlichkeit"},
    {"id": "importance", "name": "Wichtigkeit", "beschreibung": "Score 0–100 aus Kategorie, Labels, Aktualität, Duplikaten", "agent": "Analyse"},
    {"id": "pathsuggest", "name": "Pfadvorschlag", "beschreibung": "Neue Ordnerstruktur inkl. Unterordner – nur virtuell", "agent": "Organisation"},
    {"id": "safecopy", "name": "Sichere Kopie", "beschreibung": "Kopie mit SHA-256-Prüfung, nie überschreiben, nie löschen", "agent": "Kopie"},
    {"id": "inventory", "name": "Programm- & LLM-Inventar", "beschreibung": "Installierte Programme, lokale LLMs, Modelle je Computer", "agent": "Inventar"},
]


def list_skills() -> list[dict]:
    out = []
    for s in SKILLS:
        s = dict(s)
        if s["id"] == "ocr":
            s["verfügbar"] = ocr.available()
        elif s["id"] == "thumbnails":
            s["verfügbar"] = True
            from .. import platform_tools
            s["office"] = bool(platform_tools.soffice())
        else:
            s["verfügbar"] = True
        out.append(s)
    return out
