"""Erzeugt realistische Demo-Daten für 4 Computer / 6 Festplatten / 2 Cloud-Ordner unter ./demo.

    python scripts/make_demo.py
"""
from __future__ import annotations

import json
import os
import random
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import docx
import openpyxl
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1] / "demo"
random.seed(7)


def stamp(p: Path, y: int, m: int = 6, d: int = 15):
    t = datetime(y, m, d, 10, 30).timestamp()
    os.utime(p, (t, t))


def pdf(p: Path, title: str, pages: list[str], y: int, m: int = 6):
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i, body in enumerate(pages):
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(0, 0, 595, 70), color=(0.12, 0.25, 0.5), fill=(0.12, 0.25, 0.5))
        page.insert_text((40, 45), title if i == 0 else f"{title} – Seite {i + 1}", fontsize=18, color=(1, 1, 1))
        page.insert_textbox(pymupdf.Rect(40, 100, 555, 800), body, fontsize=11)
    doc.save(p)
    doc.close()
    stamp(p, y, m)


def pptx(p: Path, title: str, slides: list[tuple[str, str]], y: int, color=(30, 64, 175)):
    p.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.33), Inches(7.5)
    for i, (h, body) in enumerate([(title, "Future Dateiverwaltung Demo")] + slides):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = RGBColor(*color) if i == 0 else RGBColor(248, 250, 252)
        tb = s.shapes.add_textbox(Inches(0.8), Inches(0.6 if i else 2.6), Inches(11.5), Inches(1.4))
        tb.text_frame.text = h
        r = tb.text_frame.paragraphs[0].runs[0]
        r.font.size = Pt(40 if i == 0 else 30)
        r.font.bold = True
        r.font.color.rgb = RGBColor(255, 255, 255) if i == 0 else RGBColor(*color)
        bb = s.shapes.add_textbox(Inches(0.8), Inches(2.0 if i else 4.0), Inches(11.5), Inches(4.5))
        bb.text_frame.word_wrap = True
        for j, line in enumerate(body.split("\n")):
            para = bb.text_frame.paragraphs[0] if j == 0 else bb.text_frame.add_paragraph()
            para.text = ("• " if i else "") + line
            para.runs[0].font.size = Pt(22 if i else 20)
            para.runs[0].font.color.rgb = RGBColor(220, 230, 255) if i == 0 else RGBColor(30, 41, 59)
        if i:
            bar = s.shapes.add_shape(1, Inches(0.8), Inches(1.75), Inches(2), Inches(0.08))
            bar.fill.solid()
            bar.fill.fore_color.rgb = RGBColor(*color)
            bar.line.fill.background()
    prs.save(p)
    stamp(p, y)


def word(p: Path, title: str, paras: list[str], y: int, pages: list[tuple[str, list[str]]] = ()):
    """DOCX; weitere Seiten über (Überschrift, Absätze) mit Seitenumbruch."""
    p.parent.mkdir(parents=True, exist_ok=True)
    d = docx.Document()
    d.add_heading(title, 0)
    for t in paras:
        d.add_paragraph(t)
    for heading, body in pages:
        d.add_page_break()
        d.add_heading(heading, 1)
        for t in body:
            d.add_paragraph(t)
    d.save(p)
    stamp(p, y)


def xlsx(p: Path, title: str, rows: list[list], y: int, sheets: dict[str, list[list]] | None = None):
    """XLSX; weitere Tabellenblätter werden beim Rendern zu weiteren Seiten."""
    from openpyxl.styles import Font, PatternFill
    p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    for i, (name, data) in enumerate([(title, rows), *(sheets or {}).items()]):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = name[:30]
        for r in data:
            ws.append(r)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="4F46E5")
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 18
    wb.save(p)
    stamp(p, y)


def text(p: Path, content: str, y: int, m: int = 3):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    stamp(p, y, m)


def photo(p: Path, y: int, seed: int):
    p.parent.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    w, h = 960, 640
    im = Image.new("RGB", (w, h))
    dr = ImageDraw.Draw(im)
    c1 = [rnd.randint(40, 200) for _ in range(3)]
    c2 = [rnd.randint(40, 255) for _ in range(3)]
    for yy in range(h):
        t = yy / h
        dr.line([(0, yy), (w, yy)], fill=tuple(int(c1[k] * (1 - t) + c2[k] * t) for k in range(3)))
    for _ in range(6):
        x, yy, r = rnd.randint(0, w), rnd.randint(h // 2, h), rnd.randint(60, 220)
        dr.ellipse([x - r, yy - r // 2, x + r, yy + r // 2], fill=tuple(max(0, c - 40) for c in c1))
    dr.ellipse([w - 220, 60, w - 120, 160], fill=(255, 236, 170))
    im.save(p, quality=85)
    stamp(p, y, rnd.randint(1, 12))


def scan_image(p: Path, lines: list[str], y: int):
    """Simuliert einen eingescannten Beleg (nur Bild, kein Text) – für die OCR."""
    p.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1240, 1754), (250, 250, 247))
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 52)
    except OSError:
        font = big = ImageFont.load_default()
    dr.text((90, 90), lines[0], fill=(20, 20, 20), font=big)
    for i, line in enumerate(lines[1:]):
        dr.text((90, 220 + i * 60), line, fill=(40, 40, 40), font=font)
    im.save(p, quality=88)
    stamp(p, y)


def dup(src: Path, dst: Path):
    """Doppelte Datei auf anderem Computer/Datenträger (für die Duplikat-Erkennung)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def png_diagram(p: Path, title: str, boxes: list[str], y: int):
    """PNG-Grafik (z. B. Architekturdiagramm / Screenshot) – für die Miniaturansicht."""
    p.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", (1400, 800), (248, 250, 252, 255))
    dr = ImageDraw.Draw(im)
    try:
        f1, f2 = ImageFont.truetype("DejaVuSans-Bold.ttf", 44), ImageFont.truetype("DejaVuSans.ttf", 28)
    except OSError:
        f1 = f2 = ImageFont.load_default()
    dr.rectangle([0, 0, 1400, 110], fill=(79, 70, 229, 255))
    dr.text((50, 30), title, fill="white", font=f1)
    for i, b in enumerate(boxes):
        x = 60 + (i % 3) * 440
        yy = 190 + (i // 3) * 260
        dr.rounded_rectangle([x, yy, x + 380, yy + 170], 22, fill=(238, 240, 255, 255), outline=(99, 102, 241, 255), width=4)
        dr.text((x + 30, yy + 65), b, fill=(30, 41, 59), font=f2)
        if i % 3 < 2 and i + 1 < len(boxes):
            dr.line([x + 380, yy + 85, x + 440, yy + 85], fill=(99, 102, 241), width=5)
    im.save(p)
    stamp(p, y)


def video(p: Path, seconds: int, y: int, source: str, title: str = ""):
    """Kurzes Testvideo mit ffmpeg erzeugen (übersprungen, falls ffmpeg fehlt)."""
    import subprocess
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            print("  (ffmpeg fehlt – Demo-Video übersprungen)")
            return
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = ["-metadata", f"title={title}"] if title else []
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-t", str(seconds), "-i", f"{source}=size=960x540:rate=25",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", *meta, "-y", str(p)], check=True)
    stamp(p, y)


def eml(p: Path, subject: str, sender: str, to: str, body: str, y: int, m: int, attachments: list[Path] = (), html_body: str = ""):
    """E-Mail im .eml-Format (wie aus Outlook/Thunderbird gespeichert) mit echten Anhängen."""
    import mimetypes
    from email.message import EmailMessage
    from email.utils import format_datetime
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg["Date"] = format_datetime(datetime(y, m, 12, 9, 41).astimezone())
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    for a in attachments:
        ctype = (mimetypes.guess_type(a.name)[0] or "application/octet-stream").split("/")
        msg.add_attachment(a.read_bytes(), maintype=ctype[0], subtype=ctype[1], filename=a.name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(bytes(msg))
    stamp(p, y, m)


def binary(p: Path, size: int, y: int, header: bytes = b""):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(header + os.urandom(size))
    stamp(p, y)


def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    pc_c, pc_d = ROOT / "pc-buero/C/Users/andreas", ROOT / "pc-buero/D"
    lap = ROOT / "laptop/C/Users/andreas"
    od = ROOT / "cloud/OneDrive/Dokumente"
    ws = ROOT / "workstation/home/andreas"
    models = ws / "models"
    mac, usb, gd = ROOT / "mac/Users/andreas", ROOT / "usb-backup", ROOT / "cloud/GoogleDrive"
    (ROOT / "cloud/OneDrive/Future-Dateiverwaltung").mkdir(parents=True)

    # ---------- Privat ----------
    pdf(pc_c / "Documents/Scan_2023_04_12.pdf", "Einkommensteuerbescheid 2022", [
        "Finanzamt München – Steuerbescheid für 2022\nSteuernummer 143/123/45678\nFestgesetzte Einkommensteuer: 4.812,00 EUR\n"
        "Erstattung: 1.204,33 EUR auf IBAN DE12 7001 0080 0123 4567 89.\nEinspruchsfrist: ein Monat nach Bekanntgabe.",
        "Erläuterungen zur Festsetzung. Werbungskosten wurden in Höhe von 2.340,00 EUR anerkannt.\nDieser Bescheid ist vorläufig gemäß § 165 AO."], 2023, 4)
    pdf(od / "Wohnung/Mietvertrag_Lindenstr_12.pdf", "Mietvertrag Wohnraum", [
        "Zwischen Hausverwaltung Berger GmbH (Vermieter) und Andreas (Mieter) wird folgender Mietvertrag geschlossen.\n"
        "§1 Mietsache: 3-Zimmer-Wohnung, Lindenstraße 12.\n§3 Miete: 1.150,00 EUR zzgl. Nebenkosten 210,00 EUR.",
        "§5 Kündigung: Die Kündigungsfrist beträgt drei Monate.\n§9 Kaution: 3 Nettokaltmieten.",
        "Unterschrift Vermieter ____________   Unterschrift Mieter ____________\nOrt, Datum: München, 01.02.2021"], 2021, 2)
    dup(od / "Wohnung/Mietvertrag_Lindenstr_12.pdf", usb / "Backup_2022/Dokumente/Mietvertrag_Lindenstr_12.pdf")
    pdf(mac / "Downloads/Befund_Dr_Weber.pdf", "Laborbefund", [
        "Praxis Dr. Weber – Patient: Andreas, geb. 12.03.1976\nBefund vom 14.09.2025: Blutbild unauffällig, Vitamin D leicht erniedrigt.\n"
        "Diagnose: keine Auffälligkeiten. Empfehlung: Kontrolle in 6 Monaten."], 2025, 9)
    pdf(lap / "Downloads/Rechnung_Amazon_302-889.pdf", "Rechnung", [
        "Amazon EU S.à r.l. – Rechnung Nr. DE5-889-2231\nBestellung: Noise-Cancelling Kopfhörer\nGesamtbetrag: 279,99 EUR inkl. MwSt.\n"
        "Gewährleistung 2 Jahre. Seriennummer: QX-55812."], 2024, 11)
    pdf(pc_d / "Privat/Versicherung/Haftpflicht_Police_2024.pdf", "Versicherungsschein Privathaftpflicht", [
        "Allianz Versicherungs-AG – Versicherungsschein Nr. PH-77881\nVersicherungsnehmer: Andreas\nJahresbeitrag 64,20 EUR\n"
        "Versicherungsbeginn 01.01.2024, Laufzeit 1 Jahr, verlängert sich automatisch. Kündigungsfrist 3 Monate."], 2024, 1)
    pdf(pc_d / "Privat/Reisen/Boarding_Pass_LH2034.pdf", "Lufthansa Boarding Pass", [
        "Flug LH2034 München – Lissabon, 12.07.2025, Sitz 14A\nBuchungscode Q7XK2L. Hotel-Buchung über booking.com bestätigt."], 2025, 7)
    word(mac / "Documents/Lebenslauf_Andreas_2025.docx", "Lebenslauf", [
        "Andreas – Senior Consultant Supply Chain & GenAI", "Berufserfahrung: 2018–heute Head of SCM Digital, oneSCM-Einführung, GenAI-Programm.",
        "Ausbildung: Master Wirtschaftsingenieurwesen, TU München.", "Zertifikate: PMP, AWS Machine Learning Specialty."], 2025,
        pages=[("Projekterfahrung", ["2023–2025: Einführung oneSCM Lieferantenportal in 4 Werken.", "2024: GenAI-Programm mit 12 Use Cases, RAG über Vertragsarchiv.",
                                      "2021: Neuaufbau Disposition mit KI-Prognose."] * 3),
               ("Kenntnisse & Sprachen", ["SAP, oneSCM, Python, SQL, Power BI, Claude/LLM-Agenten.", "Deutsch (Muttersprache), Englisch (verhandlungssicher)."])])
    dup(mac / "Documents/Lebenslauf_Andreas_2025.docx", gd / "Bewerbung/Lebenslauf_Andreas_2025.docx")
    scan_image(lap / "Pictures/Scans/IMG_20240518_beleg.jpg", [
        "QUITTUNG", "Autohaus Schmidt GmbH", "Inspektion & TÜV Fahrzeug M-AB 1234", "Betrag: 489,00 EUR", "Datum: 18.05.2024",
        "Vielen Dank für Ihren Auftrag!"], 2024)
    for i in range(6):
        photo(mac / f"Pictures/Urlaub_Portugal_2025/IMG_{4200 + i}.jpg", 2025, i)
    for i in range(3):
        photo(pc_d / f"Fotos/2019/DSC_{1000 + i}.jpg", 2019, 100 + i)
    shutil.copytree(mac / "Pictures/Urlaub_Portugal_2025", usb / "Fotos_Sicherung/Urlaub_Portugal_2025")
    text(pc_c / "Desktop/Notizen_Kuendigung_Fitnessstudio.txt",
         "Kündigung Fitnessstudio FitX – Mitgliedsnummer 88213. Vertrag läuft bis 31.03.2026, Kündigungsfrist 4 Wochen.", 2026, 1)

    # ---------- Beruf ----------
    pptx(pc_c / "Documents/Arbeit/Q3_Review_SCM_2025.pptx", "Quartalsreview Q3 2025 – Supply Chain", [
        ("Agenda", "KPI-Überblick\nLieferantenperformance\nProjekte & Roadmap\nNächste Schritte"),
        ("KPI-Überblick", "Liefertreue 96,4 % (+1,2 pp)\nLagerreichweite 28 Tage\nBeschaffungskosten −3,1 %"),
        ("Lieferantenbewertung", "Top-10-Lieferanten bewertet\n2 Lieferanten mit Maßnahmenplan\noneSCM Lieferantenportal live"),
        ("Roadmap", "Q4: Disposition mit KI-Prognose\nQ1: Rollout Lager Süd\nQ2: Integration ERP"),
        ("Nächste Schritte", "Budgetfreigabe Lenkungskreis\nProjektplan finalisieren\nKickoff Pilot")], 2025)
    dup(pc_c / "Documents/Arbeit/Q3_Review_SCM_2025.pptx", od / "Arbeit/Q3_Review_SCM_2025 (1).pptx")
    pdf(pc_c / "Documents/Arbeit/Rahmenvertrag_Logistik_Nordwind.pdf", "Rahmenvertrag Logistikdienstleistungen", [
        "Rahmenvertrag zwischen Muster AG und Nordwind Logistik GmbH.\nGegenstand: Lager- und Transportdienstleistungen.\nSLA: Liefertreue ≥ 98 %.",
        "Laufzeit 36 Monate. Vertraulichkeit gemäß NDA vom 03.03.2024.\nGerichtsstand München.", "Unterschriften der Vertragsparteien."], 2024, 3)
    word(lap / "Documents/Projekt_Phoenix/Protokoll_JourFixe_2025-10-02.docx", "Protokoll Jour Fixe Projekt Phoenix", [
        "Teilnehmer: Andreas, M. Klein, S. Roth", "TOP 1: Status Meilensteine – Meilenstein 3 erreicht.",
        "TOP 2: Risiken – Lieferengpass Halbleiter, Maßnahme: Zweitlieferant.", "Nächstes Meeting: 16.10.2025"], 2025,
        pages=[("Anlage: Maßnahmenliste", [f"M{i:02d}: Maßnahme {i} – verantwortlich S. Roth – Frist KW {40 + i}" for i in range(1, 25)])])
    xlsx(pc_d / "Arbeit/Budget_2026_Planung.xlsx", "Budget 2026", [
        ["Kostenstelle", "Q1", "Q2", "Q3", "Q4"], ["SCM Digital", 120000, 115000, 130000, 140000],
        ["GenAI Programm", 80000, 95000, 110000, 120000], ["Schulung", 15000, 12000, 10000, 18000]], 2025,
        sheets={"Personal": [["Rolle", "FTE", "Kosten/Jahr"], ["Data Scientist", 2, 180000], ["SCM Analyst", 3, 210000], ["Prompt Engineer", 1, 95000]],
                "Lizenzen": [["Produkt", "Anzahl", "Preis"], ["oneSCM", 120, 54000], ["Claude Team", 40, 24000], ["Power BI", 60, 7200]]})
    xlsx(pc_d / "Arbeit/Artikelliste_Lager_Sued.xlsx", "Artikel", [["Artikel", "Bestand", "Wert", "Lager"]] +
         [[f"Artikel {i}", i, round(i * 1.19, 2), "Lager Süd"] for i in range(800)], 2026,
         sheets={"Breit": [[f"Spalte {c}" for c in range(40)], list(range(40))]})
    pdf(pc_d / "Arbeit/Rechnungen/Rechnung_2025-0815_Nordwind.pdf", "Rechnung Nr. 2025-0815", [
        "Nordwind Logistik GmbH an Muster AG\nLeistungszeitraum August 2025\nNetto 18.400,00 EUR, USt 19 %, Brutto 21.896,00 EUR\nZahlbar bis 30.09.2025."], 2025, 8)
    text(ws / "projects/scm-forecast/forecast.py",
         "import pandas as pd\n\ndef forecast(df):\n    \"\"\"Bedarfsprognose für die Disposition.\"\"\"\n    return df.rolling(4).mean()\n", 2025, 5)
    word(pc_c / "Documents/Arbeit/Prozessbeschreibung_Wareneingang.docx", "Prozessbeschreibung Wareneingang (SOP)", [
        "Ziel: Einheitlicher Wareneingangsprozess im Lager.", "Schritt 1: Lieferschein prüfen.", "Schritt 2: Buchung im ERP / oneSCM.",
        "Verantwortlich: Lagerleitung."], 2023)

    # ---------- GenAI ----------
    pptx(od / "GenAI/GenAI_Strategie_2026.pptx", "GenAI-Strategie 2026", [
        ("Vision", "Generative KI als Co-Pilot für jede Rolle\nSichere Nutzung gemäß AI Act\nMessbarer Business-Nutzen"),
        ("Use Cases", "Angebotserstellung mit LLM\nRAG über Vertragsarchiv\nKI-Agenten in der Disposition"),
        ("Plattform", "Claude & lokale LLMs (Ollama)\nVektor-DB Qdrant\nGovernance & Prompt-Bibliothek"),
        ("Roadmap", "Q1 Pilot\nQ2 Rollout Einkauf\nQ3 Skalierung")], 2026, color=(109, 40, 217))
    text(ws / "genai/prompts/system_prompt_vertragspruefung.md",
         "# System Prompt – Vertragsprüfung\n\nDu bist ein erfahrener Vertragsjurist. Prüfe den folgenden Vertrag auf Haftung, "
         "Kündigungsfristen und SLA. Antworte strukturiert.\n\n## Few-shot Beispiele\n...", 2025, 9)
    text(ws / "genai/agents/disposition_agent.py",
         "from anthropic import Anthropic\n\n# KI-Agent mit Tool Use für Dispositionsvorschläge (MCP-Tools: lager, erp)\n"
         "client = Anthropic()\n\ndef run_agent(task):\n    ...\n", 2026, 2)
    nb = {"cells": [{"cell_type": "markdown", "source": ["# RAG Experiment – Embeddings & Retrieval\n"]},
                    {"cell_type": "code", "source": ["import chromadb\n", "# chunk size 512, embedding model e5\n"]}],
          "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    text(ws / "genai/notebooks/rag_experiment.ipynb", json.dumps(nb), 2025, 11)
    text(ws / "genai/datasets/finetune_angebote.jsonl",
         "\n".join(json.dumps({"prompt": f"Angebot {i}", "completion": "..."}) for i in range(20)), 2025, 6)
    pdf(mac / "Downloads/2501.01234_attention_agents.pdf", "Attention Is Not All You Need for Agents (arXiv)", [
        "Abstract. Large language model agents rely on tool use and planning. We benchmark transformer-based agents ...",
        "1 Introduction. Retrieval-augmented generation (RAG) and agentic workflows ...", "References."], 2025, 1)
    dup(mac / "Downloads/2501.01234_attention_agents.pdf", ws / "papers/2501.01234_attention_agents.pdf")
    binary(models / "gguf/llama-3.1-8b-instruct-Q4_K_M.gguf", 300_000, 2025, b"GGUF")
    binary(models / "comfyui/sdxl_lora_produktfotos.safetensors", 120_000, 2025)
    text(lap / ".config/ollama_notes.txt", "ollama run llama3.1 – Modelle lokal, API key nicht nötig. LM Studio als Alternative.", 2025)

    png_diagram(ws / "genai/architektur/RAG_Architektur.png", "RAG-Architektur GenAI-Plattform",
                ["Dokumente", "Chunking", "Embeddings", "Vektor-DB Qdrant", "Retrieval", "Claude LLM"], 2026)
    png_diagram(pc_c / "Pictures/Screenshots/Screenshot_Lieferantenportal.png", "oneSCM Lieferantenportal",
                ["Bestellungen 128", "Liefertreue 96,4 %", "Offene Rechnungen 7", "Lieferant Nordwind", "Status: aktiv"], 2025)

    # ---------- Videos ----------
    video(mac / "Movies/Urlaub_Portugal_2025_Strand.mp4", 16, 2025, "testsrc2", "Urlaub Portugal – Strand von Lagos")
    video(lap / "Videos/Teams_Aufzeichnung_JourFixe_Phoenix.mp4", 24, 2025, "smptebars",
          "Teams-Meeting Aufzeichnung Projekt Phoenix – Jour Fixe Meilensteine")
    video(ws / "genai/demos/Agent_Demo_Disposition.mp4", 12, 2026, "mandelbrot", "Demo KI-Agent Disposition mit Claude")

    # ---------- E-Mails (mit Anhängen) ----------
    eml(od / "Arbeit/Mails/Rechnung 2025-0815 Nordwind Logistik.eml", "Rechnung Nr. 2025-0815 – Lagerleistungen August",
        "Buchhaltung Nordwind <rechnung@nordwind-logistik.de>", "Andreas <andreas@muster-ag.de>",
        "Sehr geehrter Herr Andreas,\n\nanbei erhalten Sie unsere Rechnung Nr. 2025-0815 über 21.896,00 EUR brutto "
        "für die Lagerleistungen im August 2025.\nZahlbar bis 30.09.2025 ohne Abzug.\n\nMit freundlichen Grüßen\nBuchhaltung Nordwind Logistik GmbH",
        2025, 8, [pc_d / "Arbeit/Rechnungen/Rechnung_2025-0815_Nordwind.pdf"])
    eml(od / "Arbeit/Mails/AW Budget 2026 und Lizenzen.eml", "AW: Budget 2026 – Planung GenAI und Lizenzen",
        "M. Klein <m.klein@muster-ag.de>", "Andreas <andreas@muster-ag.de>",
        "Hallo Andreas,\n\nanbei die überarbeitete Budgetplanung 2026 (Blatt Lizenzen ergänzt) und die Präsentation fürs Q3-Review.\n"
        "Bitte bis Freitag freigeben – Frist für den Lenkungskreis.\n\nViele Grüße\nMartin",
        2025, 10, [pc_d / "Arbeit/Budget_2026_Planung.xlsx", pc_c / "Documents/Arbeit/Q3_Review_SCM_2025.pptx"])
    eml(gd / "Mails/Newsletter KI-Update Oktober.eml", "KI-Update Oktober: Agenten, RAG und neue Modelle",
        "KI-Newsletter <news@ki-update.example>", "andreas@example.com",
        "KI-Update Oktober – Agenten, RAG und neue LLM-Modelle.", 2026, 10,
        [ws / "genai/architektur/RAG_Architektur.png"],
        html_body="<html><body><h1>KI-Update Oktober</h1><p>Diese Woche: <b>KI-Agenten</b> mit Tool Use, "
                  "<b>RAG</b> mit Vektor-Datenbanken und neue <b>LLM</b>-Modelle.</p><p>Viel Spaß beim Lesen!</p></body></html>")

    # ---------- Nextcloud: Dateien, die nur online liegen (Platzhalter) ----------
    nc = ROOT / "cloud/Nextcloud"
    for name in ("Steuererklaerung_2024_ELSTER.pdf", "Familienfotos_2023.zip", "Projektplan_Phoenix_v3.pptx",
                 "Arbeitsvertrag_Muster_AG.pdf"):
        ph = nc / ("Dokumente" if "Foto" not in name else "Fotos") / f"{name}.nextcloud"
        ph.parent.mkdir(parents=True, exist_ok=True)
        ph.write_bytes(b"")  # virtuelle Datei: Inhalt liegt nur auf dem Server
        stamp(ph, 2025, 3)
    text(nc / "Dokumente/Notizen_lokal.md", "# Notizen\nDiese Datei ist lokal synchronisiert.", 2025)

    # ---------- Sonstiges ----------
    binary(lap / "Downloads/OllamaSetup.exe", 80_000, 2025, b"MZ")
    binary(pc_c / "Downloads/vlc-3.0.20-win64.msi", 60_000, 2024)
    with zipfile.ZipFile(pc_d / "Archiv_alt_2017.zip", "w") as z:
        z.writestr("readme.txt", "altes Archiv")
    stamp(pc_d / "Archiv_alt_2017.zip", 2017)
    text(pc_c / "AppData/Roaming/app/debug.log", "DEBUG cache warmup ...\n" * 20, 2026, 1)
    text(gd / "Rezepte/Lasagne.md", "# Lasagne\nRezept für 4 Personen – kochen macht Spaß.", 2022)

    n = sum(1 for _ in ROOT.rglob("*") if _.is_file())
    print(f"Demo-Daten erzeugt: {n} Dateien unter {ROOT}")


if __name__ == "__main__":
    main()
