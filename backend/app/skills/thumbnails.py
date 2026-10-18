"""Skill: Miniaturansichten ALLER Seiten von PDF, PPTX, DOCX, XLSX (über LibreOffice) und Bildern."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import get_settings
from .filetype import IMAGE_EXTS, OFFICE_PAGED

THUMB_WIDTH = 900  # scharf genug für die Großansicht, klein genug für Listen


def _office_to_pdf(path: str) -> Path | None:
    """Konvertiert eine Office-Datei in eine PDF im Cache (Quelle bleibt unverändert)."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    cache = get_settings().data_dir / "pdf-cache"
    cache.mkdir(exist_ok=True)
    st = Path(path).stat()
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()
    out = cache / f"{key}.pdf"
    if out.exists():
        return out
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "lo-profile"
        cmd = [soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--norestore",
               "--convert-to", "pdf", "--outdir", tmp, path]
        subprocess.run(cmd, capture_output=True, timeout=180, check=False)
        produced = list(Path(tmp).glob("*.pdf"))
        if not produced:
            return None
        shutil.move(str(produced[0]), out)
    return out


def _render_pdf(pdf: str, out_dir: Path, max_pages: int) -> list[dict]:
    import pymupdf

    res = []
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            zoom = THUMB_WIDTH / max(page.rect.width, 1)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            p = out_dir / f"p{i + 1:04d}.jpg"
            pix.save(str(p), jpg_quality=72)
            res.append({"page": i + 1, "path": str(p), "width": pix.width, "height": pix.height})
    return res


def _render_image(path: str, out_dir: Path) -> list[dict]:
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
        p = out_dir / "p0001.jpg"
        im.save(p, "JPEG", quality=75)
        return [{"page": 1, "path": str(p), "width": im.width, "height": im.height}]


def generate(file_id: int, path: str, ext: str) -> list[dict]:
    s = get_settings()
    if not s.analysis.get("thumbnails", True):
        return []
    out_dir = s.thumbs_dir / str(file_id)
    if out_dir.exists():
        shutil.rmtree(out_dir)  # nur eigener Cache im Datenverzeichnis
    out_dir.mkdir(parents=True)
    max_pages = int(s.analysis.get("thumbnail_max_pages", 200))
    if ext == ".pdf":
        return _render_pdf(path, out_dir, max_pages)
    if ext in OFFICE_PAGED:
        pdf = _office_to_pdf(path)
        return _render_pdf(str(pdf), out_dir, max_pages) if pdf else []
    if ext in IMAGE_EXTS:
        return _render_image(path, out_dir)
    return []


def supports(ext: str) -> bool:
    return ext == ".pdf" or ext in OFFICE_PAGED or ext in IMAGE_EXTS
