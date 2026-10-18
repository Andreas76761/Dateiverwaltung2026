"""Skill: E-Mails (.eml, Outlook .msg) – Kopf, Text und Anhänge lesen und als Seiten darstellen.

- .eml über die Standardbibliothek `email`
- .msg (Outlook) über `olefile` direkt aus den MAPI-Eigenschaften – keine Outlook-Installation nötig
Die E-Mail-Datei wird nur gelesen; Anhänge werden nur im Speicher bzw. temporär für die Vorschau verwendet.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

MAIL_EXTS = {".eml", ".msg"}


class _HtmlText(HTMLParser):
    """HTML-Mail → lesbarer Text (Skripte/Styles verwerfen, Absätze erhalten)."""

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(s: str) -> str:
    p = _HtmlText()
    p.feed(s)
    text = "".join(p.out)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _parse_eml(path: str) -> dict:
    with open(path, "rb") as fh:
        msg = BytesParser(policy=policy.default).parse(fh)
    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        content = part.get_content()
        body = html_to_text(content) if part.get_content_type() == "text/html" else content
    atts = []
    for a in msg.iter_attachments():
        data = a.get_payload(decode=True) or b""
        atts.append({"name": a.get_filename() or "anhang", "mime": a.get_content_type(), "data": data})
    date = None
    if msg["date"]:
        try:
            date = parsedate_to_datetime(str(msg["date"])).isoformat()
        except (TypeError, ValueError):
            date = str(msg["date"])
    return {"subject": str(msg["subject"] or ""), "from": str(msg["from"] or ""), "to": str(msg["to"] or ""),
            "cc": str(msg["cc"] or ""), "date": date, "body": body, "attachments": atts}


def _parse_msg(path: str) -> dict:
    import olefile

    ole = olefile.OleFileIO(path)
    try:
        def prop(tag: str, base: str = "") -> str:
            for suffix, enc in (("001F", "utf-16-le"), ("001E", "cp1252")):
                name = f"{base}__substg1.0_{tag}{suffix}"
                if ole.exists(name):
                    return ole.openstream(name).read().decode(enc, "ignore").rstrip("\x00")
            return ""

        body = prop("1000")
        if not body.strip():
            if ole.exists("__substg1.0_10130102"):  # HTML-Body (binär)
                body = html_to_text(ole.openstream("__substg1.0_10130102").read().decode("utf-8", "ignore"))
            elif h := prop("1013"):
                body = html_to_text(h)
        headers = prop("007D")
        date = None
        if m := re.search(r"^Date:\s*(.+)$", headers, re.M):
            try:
                date = parsedate_to_datetime(m.group(1).strip()).isoformat()
            except (TypeError, ValueError):
                date = m.group(1).strip()
        sender = prop("0C1A") or prop("0042")
        sender_mail = prop("0C1F") or prop("0065")
        atts = []
        for entry in ole.listdir():
            if entry and entry[0].startswith("__attach_version1.0_") and len(entry) == 1:
                base = entry[0] + "/"
                name = prop("3707", base) or prop("3704", base) or "anhang"
                data_stream = f"{base}__substg1.0_37010102"
                data = ole.openstream(data_stream).read() if ole.exists(data_stream) else b""
                atts.append({"name": name, "mime": prop("370E", base), "data": data})
        return {"subject": prop("0037"), "from": f"{sender} <{sender_mail}>" if sender_mail else sender,
                "to": prop("0E04"), "cc": prop("0E03"), "date": date, "body": body, "attachments": atts}
    finally:
        ole.close()


def parse(path: str) -> dict:
    return _parse_msg(path) if path.lower().endswith(".msg") else _parse_eml(path)


def to_text(m: dict) -> str:
    lines = [f"Betreff: {m['subject']}", f"Von: {m['from']}", f"An: {m['to']}"]
    if m.get("cc"):
        lines.append(f"Cc: {m['cc']}")
    if m.get("date"):
        lines.append(f"Datum: {m['date']}")
    lines.append("")
    lines.append(m.get("body") or "")
    if m["attachments"]:
        lines.append("\nAnhänge: " + ", ".join(a["name"] for a in m["attachments"]))
    return "\n".join(lines)


def _fmt_date(d: str | None) -> str:
    if not d:
        return ""
    try:
        return datetime.fromisoformat(d).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return d


def render_pdf(m: dict, out_pdf: Path) -> int:
    """Mail als A4-PDF (Kopf + Text + Anhangsliste) rendern. Gibt die Seitenzahl zurück."""
    import pymupdf

    e = html.escape
    rows = "".join(
        f"<tr><td class='k'>{k}</td><td>{e(v)}</td></tr>"
        for k, v in (("Von", m["from"]), ("An", m["to"]), ("Cc", m.get("cc") or ""), ("Datum", _fmt_date(m.get("date"))))
        if v
    )
    atts = ""
    if m["attachments"]:
        items = "".join(f"<li>{e(a['name'])} <span class='s'>({len(a['data']) // 1024 + 1} KB)</span></li>" for a in m["attachments"])
        atts = f"<div class='att'><b>Anhänge ({len(m['attachments'])})</b><ul>{items}</ul></div>"
    body = e(m.get("body") or "").replace("\n", "<br/>")
    doc_html = f"""<h1>{e(m['subject'] or '(ohne Betreff)')}</h1><table>{rows}</table>{atts}<div class='body'>{body}</div>"""
    css = """
      body { font-family: sans-serif; font-size: 10.5pt; color: #1e293b; }
      h1 { font-size: 15pt; color: #1e3a8a; margin: 0 0 8px 0; }
      table { border-collapse: collapse; margin-bottom: 8px; }
      td { padding: 1px 8px 1px 0; vertical-align: top; font-size: 9.5pt; }
      td.k { color: #64748b; font-weight: bold; }
      .att { background: #eef2ff; padding: 6px 8px; margin: 6px 0 10px 0; font-size: 9.5pt; }
      .att ul { margin: 2px 0 0 0; }
      .s { color: #64748b; }
      .body { border-top: 1px solid #cbd5e1; padding-top: 8px; line-height: 1.4; }
    """
    story = pymupdf.Story(html=doc_html, user_css=css)
    writer = pymupdf.DocumentWriter(str(out_pdf))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (48, 48, -48, -48)
    pages = 0
    more = True
    while more and pages < 50:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
    writer.close()
    return pages
