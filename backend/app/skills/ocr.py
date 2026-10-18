"""Skill: OCR (Tesseract) für Bilder und gescannte PDFs – wie die OCR-Funktion von Screenarchiv/oneSCM."""
from __future__ import annotations

import os
from functools import lru_cache

# Tesseract nutzt sonst je Aufruf alle Kerne (OpenMP). Die Analyse liest mehrere Dateien parallel – ohne Begrenzung
# blockieren sich gleichzeitige OCR-Läufe gegenseitig (gemessen: 1 s einzeln → ~2 min parallel).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

from .. import platform_tools
from ..config import get_settings


def available() -> bool:
    return platform_tools.tesseract() is not None


def _pytesseract():
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = platform_tools.tesseract() or "tesseract"
    return pytesseract


@lru_cache
def languages() -> str:
    """Konfigurierte OCR-Sprachen, beschränkt auf tatsächlich installierte (Windows-Installer bringt oft nur 'eng' mit)."""
    wanted = get_settings().analysis.get("ocr_languages", "deu+eng").split("+")
    try:
        have = set(_pytesseract().get_languages(config=""))
    except Exception:
        return "+".join(wanted)
    use = [l for l in wanted if l in have] or (["eng"] if "eng" in have else wanted)
    return "+".join(use)


def ocr_image(path: str, max_pages: int = 10) -> str:
    """Bilder inkl. HEIC; mehrseitige TIFF-Dateien (Faxe, Scans) Seite für Seite."""
    from . import formats

    pytesseract = _pytesseract()
    out = []
    for im in formats.image_frames(path, max_pages):
        im.thumbnail((3000, 3000))
        out.append(pytesseract.image_to_string(im.convert("RGB"), lang=languages()))
    return "\n".join(out)


def ocr_pdf(path: str, max_pages: int = 5) -> str:
    """Nur für PDFs ohne Textebene (Scans)."""
    import io

    import pymupdf
    from PIL import Image

    pytesseract = _pytesseract()

    out = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=200)
            im = Image.open(io.BytesIO(pix.tobytes("png")))
            out.append(pytesseract.image_to_string(im, lang=languages()))
    return "\n".join(out)


def run(path: str, ext: str, existing_text: str) -> str:
    if not get_settings().analysis.get("ocr") or not available():
        return ""
    try:
        if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".heic", ".heif", ".hif", ".avif"}:
            return " ".join(ocr_image(path).split())[:20000]
        if ext == ".pdf" and len(existing_text.strip()) < 40:
            return " ".join(ocr_pdf(path).split())[:20000]
    except Exception as exc:  # OCR ist optional – nie die Analyse abbrechen
        return f"[OCR-Fehler: {exc}]"
    return ""
