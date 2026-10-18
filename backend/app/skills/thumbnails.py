"""Skill: Miniaturansichten ALLER Seiten von PDF, PPTX, DOCX, XLSX (über LibreOffice), Bildern,
Videos (Standbilder über die Laufzeit) und E-Mails (Mail-Seiten + Seiten der Anhänge)."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import platform_tools
from ..config import get_settings
from . import mail, video
from .filetype import IMAGE_EXTS, OFFICE_PAGED

THUMB_WIDTH = 900  # scharf genug für die Großansicht, klein genug für Listen
SHEET_MARGIN = 28
SHEET_EXTS = {".xlsx", ".xls", ".xlsm", ".ods", ".csv"}
# Tabellen: jedes Blatt als EINE Seite statt Druckaufteilung (LibreOffice ≥ 7.4)
CALC_SINGLE_PAGE = 'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}'


def _office_to_pdf(path: str) -> Path | None:
    """Konvertiert eine Office-Datei in eine PDF im Cache (Quelle bleibt unverändert)."""
    soffice = platform_tools.soffice()
    if not soffice:
        return None
    cache = get_settings().data_dir / "pdf-cache"
    cache.mkdir(exist_ok=True)
    st = Path(path).stat()
    sheet = Path(path).suffix.lower() in SHEET_EXTS
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}|{sheet}".encode()).hexdigest()
    out = cache / f"{key}.pdf"
    if out.exists():
        return out
    # Für Tabellen zuerst "ein Blatt = eine Seite", bei älteren LibreOffice-Versionen normale Druckansicht
    for target in ([CALC_SINGLE_PAGE, "pdf"] if sheet else ["pdf"]):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "lo-profile"
            cmd = [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
                   "--convert-to", target, "--outdir", tmp, path]
            subprocess.run(cmd, capture_output=True, timeout=180, check=False)
            produced = list(Path(tmp).glob("*.pdf"))
            if produced:
                shutil.move(str(produced[0]), out)
                return out
    return None


def _render_pdf(pdf: str, out_dir: Path, max_pages: int, sheet: bool = False, start: int = 0,
                label: str | None = None) -> list[dict]:
    """Rendert jede Seite. Bei Tabellenblättern (beliebige Größe) wird das Format auf
    Querformat … A4-Hochformat begrenzt: flache Blätter weiß auffüllen, lange oben anschneiden."""
    import pymupdf
    from PIL import Image

    res = []
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            rect = page.rect
            clip = None
            zoom = THUMB_WIDTH / max(rect.width, 1)
            if sheet:
                zoom = min((THUMB_WIDTH - 2 * SHEET_MARGIN) / max(rect.width, 1), 1.6)  # kleine Blätter nicht aufblasen
                max_h = (THUMB_WIDTH * 1.414 - 2 * SHEET_MARGIN) / zoom  # höchstens A4-Hochformat
                if rect.height > max_h:
                    clip = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + max_h)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, clip=clip)
            p = out_dir / f"p{start + i + 1:04d}.jpg"
            meta = {"page": start + i + 1, "path": str(p)}
            if label:
                meta["label"] = f"{label} · S. {i + 1}" if doc.page_count > 1 else label
            if sheet:
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                w = THUMB_WIDTH  # einheitliche Blattbreite, Inhalt oben links wie auf einem Ausdruck
                h = max(img.height + 2 * SHEET_MARGIN, int(w * 0.62))
                canvas = Image.new("RGB", (w, h), "white")
                canvas.paste(img, (SHEET_MARGIN, SHEET_MARGIN))
                canvas.save(p, "JPEG", quality=78)
                res.append({**meta, "width": w, "height": h})
            else:
                pix.save(str(p), jpg_quality=72)
                res.append({**meta, "width": pix.width, "height": pix.height})
    return res


def _render_image(path, out_dir: Path, start: int = 0, label: str | None = None) -> list[dict]:
    """path darf ein Dateipfad oder ein Dateiobjekt (z. B. Mail-Anhang im Speicher) sein."""
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
        p = out_dir / f"p{start + 1:04d}.jpg"
        im.save(p, "JPEG", quality=75)
        r = {"page": start + 1, "path": str(p), "width": im.width, "height": im.height}
        return [{**r, "label": label} if label else r]


def _render_mail(path: str, out_dir: Path, max_pages: int) -> list[dict]:
    """E-Mail-Seiten (Kopf, Text, Anhangsliste) und danach alle Seiten der Anhänge."""
    import io

    m = mail.parse(path)
    res: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        mail_pdf = Path(tmp) / "mail.pdf"
        mail.render_pdf(m, mail_pdf)
        res += _render_pdf(str(mail_pdf), out_dir, max_pages, label="E-Mail")
        for i, a in enumerate(m["attachments"]):
            if len(res) >= max_pages or not a["data"]:
                continue
            ext = Path(a["name"]).suffix.lower()
            lbl = f"Anhang: {a['name']}"
            try:
                if ext == ".pdf" or a["mime"] == "application/pdf":
                    f = Path(tmp) / f"a{i}.pdf"
                    f.write_bytes(a["data"])
                    res += _render_pdf(str(f), out_dir, max_pages - len(res), start=len(res), label=lbl)
                elif ext in IMAGE_EXTS:
                    res += _render_image(io.BytesIO(a["data"]), out_dir, start=len(res), label=lbl)
                elif ext in OFFICE_PAGED:
                    f = Path(tmp) / f"a{i}{ext}"
                    f.write_bytes(a["data"])
                    pdf = _office_to_pdf(str(f))
                    if pdf:
                        res += _render_pdf(str(pdf), out_dir, max_pages - len(res), sheet=ext in SHEET_EXTS,
                                           start=len(res), label=lbl)
            except Exception:
                continue  # defekter Anhang darf die Mail-Vorschau nicht verhindern
    return res


def _pdf_pages(pdf: str) -> int:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return doc.page_count


def render_to(path: str, ext: str, out_dir: Path, max_pages: int = 200, video_frames: int = 8) -> tuple[list[dict], int]:
    """Seiten/Standbilder einer Datei als JPEG in out_dir (höchstens max_pages).
    Rückgabe: (erzeugte Miniaturen, Gesamtzahl verfügbarer Seiten). Wird auch vom Agenten genutzt."""
    if ext == ".pdf":
        res, total = _render_pdf(path, out_dir, max_pages), _pdf_pages(path)
    elif ext in OFFICE_PAGED:
        pdf = _office_to_pdf(path)
        if not pdf:
            return [], 0
        res, total = _render_pdf(str(pdf), out_dir, max_pages, sheet=ext in SHEET_EXTS), _pdf_pages(str(pdf))
    elif ext in IMAGE_EXTS:
        res = _render_image(path, out_dir)
        total = len(res)
    elif ext in video.VIDEO_EXTS:
        dur = video.probe(path).get("duration") or 0
        total = max(1, min(video_frames, int(dur // 2) or 1))
        res = video.frames(path, out_dir, THUMB_WIDTH, min(total, max_pages))
    elif ext in mail.MAIL_EXTS:
        res = _render_mail(path, out_dir, max(max_pages, 50))  # Mails immer komplett (meist wenige Seiten)
        total = len(res)
    else:
        return [], 0
    for r in res:
        r["bytes"] = Path(r["path"]).stat().st_size
    return res, max(total, len(res))


def generate(file_id: int, path: str, ext: str, max_pages: int | None = None) -> tuple[list[dict], int]:
    """Miniaturen in den Cache (data/thumbs/<id>) schreiben. max_pages=1 → nur Deckblatt."""
    s = get_settings()
    if not s.analysis.get("thumbnails", True):
        return [], 0
    out_dir = s.thumbs_dir / str(file_id)
    if out_dir.exists():
        shutil.rmtree(out_dir)  # nur eigener Cache im Datenverzeichnis
    out_dir.mkdir(parents=True)
    limit = int(s.analysis.get("thumbnail_max_pages", 200))
    return render_to(path, ext, out_dir, min(max_pages or limit, limit), int(s.analysis.get("video_frames", 8)))


CLOUD_NATIVE = {".gdoc", ".gsheet", ".gslides", ".gdraw"}  # Google-Formate: Deckblatt kommt von der Cloud


def supports(ext: str) -> bool:
    return (ext == ".pdf" or ext in CLOUD_NATIVE or ext in OFFICE_PAGED or ext in IMAGE_EXTS or ext in mail.MAIL_EXTS
            or (ext in video.VIDEO_EXTS and video.available()))
