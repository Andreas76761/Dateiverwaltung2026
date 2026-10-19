"""Offline-Klassifikator: Schlüsselwörter + Dateiendung + Pfad. Immer verfügbar, kostenlos."""
from __future__ import annotations

import re

from ..categories import CATEGORIES, BY_ID
from ..skills.labels import rule_labels

PATH_HINTS = {
    "Beruf": ["arbeit", "firma", "work", "projekte", "kunden", "büro", "office", "business", "job"],
    "Privat": ["privat", "persönlich", "personal", "familie", "fotos", "pictures", "urlaub"],
    "GenAI": ["genai", "ki", "ai", "llm", "prompts", "models", "ollama", "huggingface", "agents"],
}


# Schlüsselwort → Kategorien; Index nach den ersten zwei Zeichen für EINEN Durchlauf über den Text
_KW_CATS: dict[str, list[str]] = {}
for _c in CATEGORIES:
    for _k in _c.keywords:
        _KW_CATS.setdefault(_k, []).append(_c.id)
_BY_PREFIX: dict[str, list[str]] = {}
for _k in _KW_CATS:
    _BY_PREFIX.setdefault(_k[:2], []).append(_k)
# Wortanfang ("nda" nicht in "andreas"); Wortende bleibt offen ("steuer" → "steuerbescheid")
_WORD_START = re.compile(r"(?<![a-z0-9äöüß])(?=\S)")


def keyword_hits(hay: str) -> dict[str, int]:
    """Wie oft jedes Schlüsselwort an einem Wortanfang vorkommt – ein Durchlauf statt einer Suche je Schlüsselwort."""
    hits: dict[str, int] = {}
    for m in _WORD_START.finditer(hay):
        i = m.start()
        for kw in _BY_PREFIX.get(hay[i:i + 2], ()):
            if hay.startswith(kw, i):
                hits[kw] = hits.get(kw, 0) + 1
    return hits


META_LINE = re.compile(r"^\[(?:raw-foto|iphone-/heic-foto|foto) · [^\]]*\]\s*")

# Dokumentart schlägt Thema: Was ein Dokument IST (Lebenslauf, Ausweis, Protokoll …), steht meist im Dateinamen
# und entscheidet über die Kategorie – auch wenn der Text voller Fachbegriffe eines anderen Themas ist
# (ein Lebenslauf über Supply Chain ist trotzdem eine Bewerbungsunterlage).
DOC_TYPES: dict[str, tuple[str, ...]] = {
    "b_personal": ("lebenslauf", "cv", "bewerbung", "anschreiben", "arbeitszeugnis", "zwischenzeugnis", "gehaltsabrechnung",
                   "lohnabrechnung", "entgeltabrechnung", "arbeitsvertrag", "resume", "curriculum"),
    "p_behoerden": ("personalausweis", "ausweis", "reisepass", "geburtsurkunde", "heiratsurkunde", "sterbeurkunde",
                    "meldebescheinigung", "führungszeugnis", "fuehrungszeugnis", "aufenthaltstitel", "rentenbescheid"),
    "p_gesundheit": ("impfpass", "impfausweis", "arztbrief", "befund", "attest", "arbeitsunfähigkeit", "au-bescheinigung",
                     "heilmittelverordnung", "überweisungsschein", "krankenhausbericht", "entlassbrief"),
    "p_steuern": ("steuerbescheid", "steuererklärung", "steuererklaerung", "lohnsteuerbescheinigung", "einkommensteuer",
                  "steuerberater", "est_", "elster", "finanzamt", "grundsteuer"),
    "p_finanzen": ("kontoauszug", "depotauszug", "kreditvertrag", "darlehensvertrag", "jahressteuerbescheinigung"),
    "p_versicherung": ("police", "versicherungsschein", "schadenmeldung", "schadensmeldung", "beitragsrechnung"),
    "p_wohnen": ("mietvertrag", "nebenkostenabrechnung", "betriebskostenabrechnung", "stromrechnung", "heizkostenabrechnung",
                 "übergabeprotokoll", "wohnungsgeberbestätigung"),
    "p_auto": ("fahrzeugschein", "fahrzeugbrief", "zulassungsbescheinigung", "tüv", "tuev", "hauptuntersuchung", "inspektion"),
    "p_vertraege": ("kündigung", "kuendigung", "handyvertrag", "mobilfunkvertrag"),
    "p_bildung": ("zeugnis", "abiturzeugnis", "masterurkunde", "bachelorurkunde", "diplom", "notenspiegel", "transcript"),
    "p_reisen": ("boarding", "bordkarte", "flugticket", "bahnticket", "hotelbuchung", "reisebestätigung", "visum"),
    "p_garantie": ("garantie", "garantieschein", "bedienungsanleitung", "gebrauchsanweisung", "handbuch"),
    "p_rechnungen": ("quittung", "kassenbon", "kassenbeleg"),
    "b_meetings": ("protokoll", "agenda", "tagesordnung", "jourfixe", "jour fixe", "aufzeichnung", "besprechung", "meeting"),
    "b_vertraege": ("rahmenvertrag", "nda", "geheimhaltungsvereinbarung", "dienstleistungsvertrag", "avv", "lizenzvertrag"),
    "b_angebote": ("angebot", "kostenvoranschlag", "auftragsbestätigung", "bestellung", "purchase order"),
    "b_rechnungen": ("invoice", "gutschrift", "mahnung"),
    "b_schulung": ("zertifikat", "teilnahmebestätigung", "teilnahmebescheinigung", "certificate"),
    "b_berichte": ("jahresbericht", "monatsbericht", "quartalsbericht", "report"),
    "g_medien": ("comfyui", "midjourney", "dall-e", "dalle", "stable diffusion", "sdxl"),
    "s_backups": ("backup", "sicherung", "datensicherung"),
}
_DT_INDEX: dict[str, list[str]] = {}
for _cid, _words in DOC_TYPES.items():
    for _w in _words:
        _DT_INDEX.setdefault(_w, []).append(_cid)
_DT_RX = re.compile(r"(?<![a-z0-9äöüß])(" + "|".join(sorted(map(re.escape, _DT_INDEX), key=len, reverse=True)) + r")(?![a-zäöüß])")
# Ein „report“ von Hugging Face ist kein Geschäftsbericht – Dokumentart im Pfad zählt nur halb, im Text nur am Anfang (Titel)
DT_NAME, DT_PATH, DT_TITLE = 7.0, 3.0, 2.0
MEDIA_TYPES = ("Bild", "Video", "Audio")
MAIL_REPLY = re.compile(r"^(aw|wg|re|fw|fwd|antw)[\s:_-]", re.I)


def doc_type_hits(name: str, folder: str, title: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for hay, w in ((name, DT_NAME), (folder, DT_PATH), (title, DT_TITLE)):
        for m in _DT_RX.finditer(hay.replace("_", " ").replace("-", " ") if hay is not name else re.sub(r"[_\-.]", " ", hay)):
            for cid in _DT_INDEX[m.group(1)]:
                scores[cid] = max(scores.get(cid, 0.0), 0.0) + w
    return scores


class RulesProvider:
    name = "regeln"

    def analyze(self, meta: dict, text: str) -> dict:
        name = meta["name"].lower()
        # Pfad innerhalb des Datenträgers: der Speicherort des Datenträgers selbst (z. B. …\AppData\Local\Temp
        # oder D:\Sicherung) sagt nichts über die einzelne Datei aus
        path = (meta.get("rel_path") or meta["path"]).lower().replace("\\", "/")
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        ext = (meta.get("ext") or "").lower()
        hay_name = f"{name} {path}"
        hay_text = text[:12000].lower()

        name_hits = keyword_hits(hay_name)
        text_hits = keyword_hits(hay_text) if hay_text else {}
        # Foto-Metadaten (Aufnahmedatum, Kamera) sind kein Dokumenttext – zählen nicht als „Bild mit viel Text“
        content = META_LINE.sub("", hay_text, count=1)
        content_len = len(content)
        dtype = doc_type_hits(name, folder, content[:160])
        media = meta.get("file_type") in MEDIA_TYPES
        # Medien mit sprechendem Namen (z. B. „Sprachmemo_Termin_Steuerberater.m4a“, „Personalausweis.jpg“):
        # der Name sagt mehr als die Endung
        topical_name = any(cid not in ("p_fotos", "p_videos", "p_musik") for kw in name_hits for cid in _KW_CATS[kw]) or bool(dtype)
        scores: dict[str, float] = {}
        for c in CATEGORIES:
            s = 0.0
            if ext and ext in c.exts:
                weak = media and (content_len > 80 or topical_name)
                s += 1.0 if weak else 3.0
            for kw in c.keywords:
                if kw in name_hits:
                    s += 2.5
                if kw in text_hits:
                    s += min(text_hits[kw], 5) * 0.6
            s += dtype.get(c.id, 0.0)
            if c.id == "b_kunden" and ext in (".eml", ".msg") and MAIL_REPLY.match(name):
                s += 2.0  # „AW: …“ / „WG: …“ – geschäftliche Korrespondenz
            if c.id == "p_fotos" and meta.get("file_type") == "Bild" and (content_len > 80 or dtype):
                s *= 0.4  # Bild mit viel Text oder Dokumentnamen ist eher ein gescanntes Dokument
            if s:
                scores[c.id] = s

        segs = set(re.split(r"[/_\-. ]+", path))
        for group, hints in PATH_HINTS.items():
            if any(h in segs for h in hints):
                for cid in scores:
                    if BY_ID[cid].group == group:
                        scores[cid] *= 1.4

        if scores:
            ranked = sorted(scores.values(), reverse=True)
            best = max(scores, key=scores.get)
            top, second = ranked[0], (ranked[1] if len(ranked) > 1 else 0.0)
            # Sicherheit aus dem Vorsprung vor der zweitbesten Kategorie – knappe Entscheidungen gelten als unsicher
            # (gehen im Modus „unklare“ an das LLM); wenig Belege insgesamt ebenfalls
            margin = (top - second) / top
            conf = 0.35 + 0.6 * margin * min(1.0, top / 6)
            conf = round(min(0.95, max(0.25, conf)), 2)
        else:
            best, conf = "s_unbekannt", 0.2
        cat = BY_ID[best]

        labels = sorted(rule_labels(meta["name"], text))[:6]
        first = " ".join(text.split()[:24]) if text else ""
        summary = f"{meta.get('file_type', 'Datei')} „{meta['name']}“" + (f": {first}…" if first else "")
        return {
            "category_id": cat.id,
            "labels": labels,
            "summary": summary[:200],
            "subfolder": "",
            "importance": 50,
            "confidence": conf,
        }
