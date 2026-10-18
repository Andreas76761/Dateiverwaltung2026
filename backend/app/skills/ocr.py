"""Skill: OCR (Tesseract) für Bilder und gescannte PDFs – wie die OCR-Funktion von Screenarchiv/oneSCM."""
from __future__ import annotations

import shutil

from ..config import get_settings


def available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_image(path: str) -> str:
    import pytesseract
    from PIL import Image

    with Image.open(path) as im:
        im.thumbnail((3000, 3000))
        return pytesseract.image_to_string(im.convert("RGB"), lang=get_settings().analysis["ocr_languages"])


def ocr_pdf(path: str, max_pages: int = 5) -> str:
    """Nur für PDFs ohne Textebene (Scans)."""
    import io

    import pymupdf
    import pytesseract
    from PIL import Image

    out = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=200)
            im = Image.open(io.BytesIO(pix.tobytes("png")))
            out.append(pytesseract.image_to_string(im, lang=get_settings().analysis["ocr_languages"]))
    return "\n".join(out)


def run(path: str, ext: str, existing_text: str) -> str:
    if not get_settings().analysis.get("ocr") or not available():
        return ""
    try:
        if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}:
            return " ".join(ocr_image(path).split())[:20000]
        if ext == ".pdf" and len(existing_text.strip()) < 40:
            return " ".join(ocr_pdf(path).split())[:20000]
    except Exception as exc:  # OCR ist optional – nie die Analyse abbrechen
        return f"[OCR-Fehler: {exc}]"
    return ""
