"""Miniaturen aller Seiten für PDF, PPTX, DOCX, XLSX, PNG, JPEG."""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

needs_office = pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice fehlt")


@pytest.fixture()
def thumbs(tmp_path, monkeypatch):
    monkeypatch.setenv("FDV_CONFIG", str(tmp_path / "keine.yaml"))
    monkeypatch.setenv("FDV_DATA_DIR", str(tmp_path / "data"))
    from app.config import get_settings
    get_settings.cache_clear()
    from app.skills import thumbnails
    yield thumbnails
    get_settings.cache_clear()


def test_pdf_and_images(thumbs, tmp_path):
    import pymupdf
    from PIL import Image
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((50, 50), f"Seite {i + 1}")
    doc.save(tmp_path / "a.pdf")
    assert len(thumbs.generate(1, str(tmp_path / "a.pdf"), ".pdf")) == 3
    Image.new("RGBA", (300, 200), (0, 0, 255, 128)).save(tmp_path / "b.png")
    Image.new("RGB", (300, 200), "red").save(tmp_path / "c.jpg")
    assert len(thumbs.generate(2, str(tmp_path / "b.png"), ".png")) == 1
    assert len(thumbs.generate(3, str(tmp_path / "c.jpg"), ".jpg")) == 1


@needs_office
def test_docx_all_pages(thumbs, tmp_path):
    import docx
    d = docx.Document()
    for i in range(3):
        if i:
            d.add_page_break()
        d.add_heading(f"Kapitel {i + 1}", 1)
    d.save(tmp_path / "d.docx")
    assert len(thumbs.generate(4, str(tmp_path / "d.docx"), ".docx")) == 3


@needs_office
def test_xlsx_one_thumbnail_per_sheet(thumbs, tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append([f"Spalte {c}" for c in range(30)])  # breit: darf nicht auf mehrere Seiten zerfallen
    long = wb.create_sheet("Lang")
    for i in range(500):
        long.append([f"Artikel {i}", i])
    wb.create_sheet("Leer").append(["x"])
    wb.save(tmp_path / "e.xlsx")
    res = thumbs.generate(5, str(tmp_path / "e.xlsx"), ".xlsx")
    assert len(res) == 3
    assert all(r["width"] == thumbs.THUMB_WIDTH for r in res)
    assert max(r["height"] for r in res) <= thumbs.THUMB_WIDTH * 1.42  # lange Blätter auf A4 begrenzt


def test_video_frames(thumbs, tmp_path):
    from app.skills import video
    if not video.available():
        pytest.skip("ffmpeg fehlt")
    import subprocess
    f = tmp_path / "v.mp4"
    subprocess.run([video.ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-t", "10", "-i", "testsrc2=size=320x240:rate=10",
                    "-metadata", "title=Teams Meeting Projekt", "-pix_fmt", "yuv420p", "-y", str(f)], check=True)
    info = video.probe(str(f))
    assert round(info["duration"]) == 10 and info["width"] == 320 and info["title"] == "Teams Meeting Projekt"
    res = thumbs.generate(6, str(f), ".mp4")
    assert len(res) == 5  # 10 s → alle 2 s ein Standbild (max. 8)
    assert [r["label"] for r in res] == ["0:01", "0:03", "0:05", "0:07", "0:09"]


def test_eml_with_attachments(thumbs, tmp_path):
    import pymupdf
    from email.message import EmailMessage
    from PIL import Image
    from app.skills import mail
    pdf = pymupdf.open()
    for i in range(2):
        pdf.new_page().insert_text((50, 50), f"Rechnung Seite {i + 1}")
    img = tmp_path / "foto.png"
    Image.new("RGB", (200, 100), "green").save(img)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "Rechnung 4711", "a@example.com", "b@example.com"
    msg["Date"] = "Mon, 13 Oct 2025 09:41:00 +0200"
    msg.set_content("Text")
    msg.add_alternative("<html><body><p>Anbei die <b>Rechnung</b>.</p><script>x()</script></body></html>", subtype="html")
    msg.add_attachment(pdf.tobytes(), maintype="application", subtype="pdf", filename="rechnung.pdf")
    msg.add_attachment(img.read_bytes(), maintype="image", subtype="png", filename="foto.png")
    f = tmp_path / "m.eml"
    f.write_bytes(bytes(msg))
    m = mail.parse(str(f))
    assert m["subject"] == "Rechnung 4711" and [a["name"] for a in m["attachments"]] == ["rechnung.pdf", "foto.png"]
    assert "Anhänge: rechnung.pdf, foto.png" in mail.to_text(m)
    res = thumbs.generate(7, str(f), ".eml")
    assert [r["label"] for r in res] == ["E-Mail", "Anhang: rechnung.pdf · S. 1", "Anhang: rechnung.pdf · S. 2", "Anhang: foto.png"]
    assert mail.html_to_text("<p>a</p><script>x()</script><p>b</p>") == "a\nb"


def test_msg_outlook_properties(monkeypatch):
    """Outlook-.msg: MAPI-Eigenschaften aus dem OLE-Container (nachgebildet, da keine echte .msg erzeugt werden kann)."""
    import io
    import olefile
    from app.skills import mail
    u = lambda s: s.encode("utf-16-le")
    streams = {
        "__substg1.0_0037001F": u("Angebot Lagerlogistik"),
        "__substg1.0_0C1A001F": u("Nordwind Vertrieb"),
        "__substg1.0_0C1F001F": u("vertrieb@nordwind.de"),
        "__substg1.0_0E04001F": u("Andreas"),
        "__substg1.0_1000001F": u("Sehr geehrte Damen und Herren,\nanbei unser Angebot."),
        "__substg1.0_007D001F": u("Date: Tue, 14 Oct 2025 08:00:00 +0200\r\n"),
        "__attach_version1.0_#00000000/__substg1.0_3707001F": u("Angebot.pdf"),
        "__attach_version1.0_#00000000/__substg1.0_37010102": b"%PDF-1.4 ...",
    }

    class FakeOle:
        def __init__(self, path): pass
        def exists(self, name): return name in streams
        def openstream(self, name): return io.BytesIO(streams[name])
        def listdir(self): return [k.split("/") for k in streams] + [["__attach_version1.0_#00000000"]]
        def close(self): pass

    monkeypatch.setattr(olefile, "OleFileIO", FakeOle)
    m = mail.parse("x.msg")
    assert m["subject"] == "Angebot Lagerlogistik"
    assert m["from"] == "Nordwind Vertrieb <vertrieb@nordwind.de>"
    assert m["date"].startswith("2025-10-14T08:00")
    assert m["body"].startswith("Sehr geehrte") and m["attachments"][0]["name"] == "Angebot.pdf"
