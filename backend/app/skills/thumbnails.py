"""Skill: Miniaturansichten ALLER Seiten von PDF, PPTX, DOCX, XLSX, Keynote/Pages/Numbers (über LibreOffice),
Bildern (auch HEIC, RAW, mehrseitige TIFF), Videos (Standbilder über die Laufzeit), E-Mails (Mail-Seiten + Seiten der
Anhänge), Archiven (Inhaltsverzeichnis + enthaltene Bilder/Dokumente) und Audio (Cover + Wellenform)."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import platform_tools
from ..config import get_settings
from . import formats, mail, video
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


def _render_image(path, out_dir: Path, start: int = 0, label: str | None = None, max_pages: int = 200) -> list[dict]:
    """path darf ein Dateipfad oder ein Dateiobjekt (z. B. Mail-Anhang im Speicher) sein.
    Mehrseitige TIFF-Dateien liefern eine Miniatur je Seite; HEIC und RAW werden über formats geöffnet."""
    from PIL import Image, ImageOps

    if isinstance(path, (str, Path)):
        frames = list(formats.image_frames(str(path), max_pages))
    else:
        with Image.open(path) as im:
            frames = [im.copy()]
    res = []
    for i, im in enumerate(frames):
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 2))
        p = out_dir / f"p{start + i + 1:04d}.jpg"
        im.save(p, "JPEG", quality=75)
        r = {"page": start + i + 1, "path": str(p), "width": im.width, "height": im.height}
        if label:
            r["label"] = f"{label} · S. {i + 1}" if len(frames) > 1 else label
        elif len(frames) > 1:
            r["label"] = f"Seite {i + 1}"
        res.append(r)
    return res


def _html_page(html: str, out_dir: Path, start: int, label: str) -> list[dict]:
    """Kleine Info-Seite (z. B. Archiv-Inhaltsverzeichnis) als Miniatur."""
    import pymupdf

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "info.pdf"
        story = pymupdf.Story(html=html, user_css="* { font-family: sans-serif; } body { font-size: 10pt; color: #0f172a; } "
                                                     "h1 { font-size: 15pt; color: #312e81; } td { padding: 1pt 6pt 1pt 0; font-size: 9pt; } "
                                                     ".m { color: #64748b; }")
        writer = pymupdf.DocumentWriter(str(f))
        rect = pymupdf.paper_rect("a4")
        dev = writer.begin_page(rect)
        story.place(rect + (36, 36, -36, -36))  # nur die erste Seite – reicht als Übersicht
        story.draw(dev)
        writer.end_page()
        writer.close()
        return _render_pdf(str(f), out_dir, 1, start=start, label=label)


def _render_archive(path: str, out_dir: Path, max_pages: int) -> tuple[list[dict], int]:
    """Seite 1: Inhaltsverzeichnis; danach Vorschau der ersten enthaltenen Bilder, PDFs und Office-Dateien."""
    import io
    from html import escape

    entries = formats.archive_entries(path)
    files = [e for e in entries if not e["dir"]]
    rows = "".join(f"<tr><td>{escape(e['name'])}</td><td class='m'>{formats._fmt(e['size'] or 0)}</td></tr>" for e in files[:60])
    more = f"<p class='m'>… und {len(files) - 60} weitere</p>" if len(files) > 60 else ""
    head = escape(formats.describe_archive(entries).split("\n")[0])
    res = _html_page(f"<h1>{escape(Path(path).name)}</h1><p class='m'>{head}</p><table>{rows}</table>{more}", out_dir, 0, "Inhalt")
    previewable = [e for e in files if not e["encrypted"] and e["size"] <= formats.MAX_MEMBER
                   and Path(e["name"]).suffix.lower() in IMAGE_EXTS | formats.HEIC_EXTS | {".pdf"} | OFFICE_PAGED]
    budget = formats.MAX_UNPACK_TOTAL
    truncated = False
    with tempfile.TemporaryDirectory() as tmp:
        for i, e in enumerate(previewable[:formats.MAX_MEMBERS_PREVIEW]):
            if len(res) >= max_pages or budget <= 0:
                truncated = len(res) >= max_pages
                break
            data = formats._read_member(path, e["name"], e["size"])
            if not data:
                continue
            budget -= len(data)
            ext = Path(e["name"]).suffix.lower()
            lbl = Path(e["name"]).name
            try:
                if ext in IMAGE_EXTS:
                    res += _render_image(io.BytesIO(data), out_dir, start=len(res), label=lbl)
                    continue
                f = Path(tmp) / f"m{i}{ext}"  # eigener Dateiname – Pfade aus dem Archiv werden nie verwendet
                f.write_bytes(data)
                if ext in formats.HEIC_EXTS:
                    res += _render_image(str(f), out_dir, start=len(res), label=lbl, max_pages=1)
                elif ext == ".pdf":
                    res += _render_pdf(str(f), out_dir, min(3, max_pages - len(res)), start=len(res), label=lbl)
                elif (pdf := _office_to_pdf(str(f))):
                    res += _render_pdf(str(pdf), out_dir, min(3, max_pages - len(res)), sheet=ext in SHEET_EXTS, start=len(res), label=lbl)
            except Exception:
                continue  # defekter Eintrag darf die Archiv-Vorschau nicht verhindern
    # nur Deckblatt angefordert → Gesamtzahl schätzen, damit „Alle Seiten laden“ angeboten wird
    return res, (max(len(res) + 1, 1 + min(len(previewable), formats.MAX_MEMBERS_PREVIEW)) if truncated else len(res))


def _render_iwork(path: str, out_dir: Path, max_pages: int) -> tuple[list[dict], int]:
    """Keynote/Pages/Numbers: über LibreOffice alle Seiten, sonst die gespeicherte Vorschau des Dokuments."""
    import io

    if not formats.is_iwork(path):
        return [], 0
    pdf = _office_to_pdf(path)
    if pdf:
        return _render_pdf(str(pdf), out_dir, max_pages, sheet=path.lower().endswith(".numbers")), _pdf_pages(str(pdf))
    prev = formats.iwork_preview(path)
    if not prev:
        return [], 0
    data, ext = prev
    if ext == ".pdf":
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "preview.pdf"
            f.write_bytes(data)
            return _render_pdf(str(f), out_dir, max_pages), _pdf_pages(str(f))
    return _render_image(io.BytesIO(data), out_dir, label="Vorschau"), 1


def _render_audio(path: str, out_dir: Path) -> list[dict]:
    """Cover (falls eingebettet) und Wellenform."""
    import io

    res: list[dict] = []
    cover = formats.audio_cover(path)
    if cover:
        try:
            res += _render_image(io.BytesIO(cover), out_dir, label="Cover")
        except Exception:
            pass
    p = out_dir / f"p{len(res) + 1:04d}.jpg"
    if formats.audio_waveform(path, p):
        from PIL import Image

        with Image.open(p) as im:
            res.append({"page": len(res) + 1, "path": str(p), "width": im.width, "height": im.height, "label": "Wellenform"})
    return res


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
                elif ext in IMAGE_EXTS or ext in formats.HEIC_EXTS:
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
    elif ext in IMAGE_EXTS or ext in formats.HEIC_EXTS or ext in formats.RAW_EXTS:
        res = _render_image(path, out_dir, max_pages=max_pages)
        total = formats.page_count(path) if ext in formats.TIFF_EXTS else len(res)
    elif ext in formats.IWORK_EXTS:
        res, total = _render_iwork(path, out_dir, max_pages)
    elif formats.is_archive(path):
        res, total = _render_archive(path, out_dir, max_pages)
    elif ext in formats.AUDIO_EXTS:
        res = _render_audio(path, out_dir)
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
            or ext in formats.HEIC_EXTS or ext in formats.RAW_EXTS or ext in formats.IWORK_EXTS
            or ext in (".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz") or (ext in (".7z", ".rar") and formats._seven_zip() is not None)
            or (ext in formats.AUDIO_EXTS and (video.available() or formats.MUTAGEN_OK))
            or (ext in video.VIDEO_EXTS and video.available()))
