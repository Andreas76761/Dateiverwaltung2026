"""Weitere Formate: HEIC, RAW, mehrseitige TIFF, Archive (ZIP/TAR), Keynote/Pages, Audio."""
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.skills import extract, formats, thumbnails  # noqa: E402


def picture(size=(640, 480), color=(200, 80, 40)):
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).ellipse([100, 100, 400, 380], fill=(30, 90, 200))
    return im


def exif(make="Apple", model="iPhone 15 Pro", when="2025:08:14 18:22:05"):
    e = Image.Exif()
    e[0x010F], e[0x0110] = make, model
    e.get_ifd(0x8769)[0x9003] = when
    return e


def render(path: Path, tmp_path: Path, max_pages=50):
    out = tmp_path / ("out_" + path.name)
    out.mkdir()
    return thumbnails.render_to(str(path), path.suffix.lower(), out, max_pages)


@pytest.mark.skipif(not formats.HEIF_OK, reason="pillow-heif nicht installiert")
def test_heic(tmp_path):
    p = tmp_path / "IMG_5012.HEIC"
    picture().save(p, format="HEIF", exif=exif().tobytes())
    res, total = render(p, tmp_path)
    assert total == 1 and res[0]["width"] > 0
    text, _ = extract.extract_text(str(p), ".heic")
    assert text == "[iPhone-/HEIC-Foto · aufgenommen 14.08.2025 18:22 · iPhone 15 Pro · 640×480]" or "Apple iPhone" in text


def test_raw_embedded_preview_without_rawpy(tmp_path, monkeypatch):
    buf = io.BytesIO()
    picture((800, 533)).save(buf, "JPEG", exif=exif("NIKON CORPORATION", "NIKON Z 6II", "2024:05:03 09:41:12").tobytes())
    small = io.BytesIO()
    picture((160, 120)).save(small, "JPEG")
    p = tmp_path / "DSC_2001.NEF"
    p.write_bytes(b"II*\x00" + bytes(2048) + small.getvalue() + bytes(512) + buf.getvalue() + bytes(1000))
    monkeypatch.setitem(sys.modules, "rawpy", None)  # Fallback ohne rawpy prüfen
    im = formats.open_image(str(p))
    assert im.size == (800, 533)  # größte eingebettete Vorschau gewählt
    res, total = render(p, tmp_path)
    assert total == 1 and res[0]["width"] == 800
    text, _ = extract.extract_text(str(p), ".nef")
    assert text == "[RAW-Foto · aufgenommen 03.05.2024 09:41 · NIKON Z 6II · 800×533]"


def test_multipage_tiff(tmp_path):
    p = tmp_path / "Fax.tif"
    pages = [Image.new("L", (600, 800), 255) for _ in range(3)]
    pages[0].save(p, save_all=True, append_images=pages[1:])
    res, total = render(p, tmp_path)
    assert total == 3 and [r["label"] for r in res] == ["Seite 1", "Seite 2", "Seite 3"]
    assert extract.extract_text(str(p), ".tif") == ("", 3)  # Scan ohne Kameradaten: kein „Foto“-Text
    res, total = render(p, tmp_path / "x" if (tmp_path / "x").mkdir() else tmp_path / "x", max_pages=1)
    assert len(res) == 1 and total == 3  # „alle Seiten laden“ bleibt möglich


def test_zip_and_tar(tmp_path, monkeypatch):
    import pymupdf

    pdf = tmp_path / "Rechnung.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 80), "Rechnung Nr. 4711 Betrag 120 EUR")
    doc.save(pdf)
    img = io.BytesIO()
    picture().save(img, "PNG")
    zp = tmp_path / "Unterlagen.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.write(pdf, "Ordner/Rechnung.pdf")
        z.writestr("Ordner/Bild.png", img.getvalue())
        z.writestr("Ordner/Notiz.txt", "Projekt Phoenix Meilenstein 4")
        z.writestr("../../boese.txt", "Pfad außerhalb – darf nie entpackt werden")
        z.writestr("Groß.bin", b"x" * 2048)
    text, _ = extract.extract_text(str(zp), ".zip")
    assert text.startswith("Archiv mit 5 Dateien")
    assert "Rechnung Nr. 4711" in text and "Meilenstein 4" in text and "Groß.bin" in text
    res, total = render(zp, tmp_path)
    assert [r["label"] for r in res] == ["Inhalt", "Rechnung.pdf", "Bild.png"]
    assert not (tmp_path.parent / "boese.txt").exists()
    # Größenlimit: große Einträge werden nicht ausgepackt
    monkeypatch.setattr(formats, "MAX_MEMBER", 100)
    assert "Rechnung Nr. 4711" not in extract.extract_text(str(zp), ".zip")[0]

    tg = tmp_path / "Fotos.tar.gz"
    with tarfile.open(tg, "w:gz") as t:
        info = tarfile.TarInfo("Fotos/a.png")
        info.size = len(img.getvalue())
        t.addfile(info, io.BytesIO(img.getvalue()))
    assert formats.is_archive(str(tg))
    assert extract.extract_text(str(tg), ".gz")[0].startswith("Archiv mit 1 Datei ")


def test_iwork_preview_and_key_file(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnails, "_office_to_pdf", lambda p: None)  # ohne LibreOffice: gespeicherte Vorschau
    jpg = io.BytesIO()
    picture((1024, 768)).save(jpg, "JPEG")
    key = tmp_path / "Praesentation.key"
    with zipfile.ZipFile(key, "w") as z:
        z.writestr("Index/Document.iwa", b"\x00")
        z.writestr("preview.jpg", jpg.getvalue())
    res, total = render(key, tmp_path)
    assert total == 1 and res[0]["label"] == "Vorschau"
    pem = tmp_path / "server.key"  # TLS-Schlüssel, keine Keynote-Datei
    pem.write_text("-----BEGIN PRIVATE KEY-----\nMIIEv…\n-----END PRIVATE KEY-----\n")
    assert render(pem, tmp_path) == ([], 0)
    assert extract.extract_text(str(pem), ".key") == ("", None)


def test_audio(tmp_path):
    from app.skills import video

    if not video.available():
        pytest.skip("ffmpeg fehlt")
    import subprocess

    p = tmp_path / "Lied.mp3"
    subprocess.run([video.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-t", "4", "-i", "sine=frequency=440",
                    "-metadata", "title=Sommerlied", "-metadata", "artist=Demo-Band", "-y", str(p)], check=True)
    if formats.MUTAGEN_OK:
        from mutagen.id3 import APIC, ID3
        t = ID3(p)
        c = io.BytesIO()
        picture((300, 300)).save(c, "JPEG")
        t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=c.getvalue()))
        t.save(p)
    text, _ = extract.extract_text(str(p), ".mp3")
    assert text.startswith("Audio · Dauer 0:04") and "Titel: Sommerlied" in text and "Interpret: Demo-Band" in text
    res, _ = render(p, tmp_path)
    assert [r["label"] for r in res] == (["Cover", "Wellenform"] if formats.MUTAGEN_OK else ["Wellenform"])
    assert thumbnails.supports(".mp3") and thumbnails.supports(".heic") and thumbnails.supports(".nef") and thumbnails.supports(".zip")


def test_photo_meta_not_counted_as_document_text():
    from app.llm.rules_provider import RulesProvider

    meta = {"name": "IMG_5012.HEIC", "path": "/Users/a/Pictures/iPhone/IMG_5012.HEIC", "ext": ".heic", "file_type": "Bild"}
    r = RulesProvider().analyze(meta, "[iPhone-/HEIC-Foto · aufgenommen 14.08.2025 18:22 · Apple iPhone 15 Pro · 4032×3024 · mit GPS-Position]")
    assert r["category_id"] == "p_fotos"
