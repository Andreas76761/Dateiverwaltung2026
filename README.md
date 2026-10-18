# Future Dateiverwaltung

Ansicht, Analyse, Eingruppierung und sichere Archivierung **aller Dateien auf mehreren Computern, Festplatten und Cloud-Ordnern** – mit einem erweiterten Explorer, LLM-Inhaltsanalyse, OCR, Miniaturen aller Seiten (PDF/PPTX/DOCX/XLSX), Labels, Wichtigkeit, Duplikat-Erkennung und einem Vorschlag für eine neue Ordnerstruktur in der Cloud.

> **Grundregel:** Es wird **nichts gelöscht, verschoben oder umbenannt**. Quellen sind read-only. Geschrieben wird ausschließlich in den neuen Cloud-Zielordner – und erst nach manueller Freigabe, als verifizierte Kopie.

## Die 4 Schritte

| Schritt | Agent | Was passiert | Physische Änderung |
|---|---|---|---|
| 1 · Einlesen | `scan_agent` | Dateien je Computer / Festplatte / Cloud-Ordner erfassen, Prüfsummen für Duplikate | keine |
| 2 · Analysieren | `analysis_agent` | Text, OCR, Miniaturen, LLM → 50 Kategorien → **Privat / Beruf / GenAI / Sonstiges**, Labels, Wichtigkeit, Pfadvorschlag | keine |
| 3 · Vorschlag | `organizer_agent` | Virtuelle neue Ordnerstruktur, prüfen, umbenennen, verschieben, freigeben/ablehnen | keine |
| 4 · Kopieren | `copy_agent` | Freigegebene Dateien als Kopie in den neuen Cloud-Ordner, SHA-256-verifiziert, mit Statistik | nur Kopien im Ziel |

Erweiterung: `inventory_agent` – installierte Programme, LLM-Lösungen (Ollama, LM Studio, Claude Code, Python-KI-Bibliotheken …) und lokale Modelle je Computer.

## Schnellstart (Demo mit 4 Computern, 6 Festplatten, 2 Cloud-Ordnern)

```bash
./start.sh            # Linux/macOS   (Windows: .\start.ps1)
# → http://localhost:8800
```

`start.sh` installiert die Python-Pakete, baut das Frontend und erzeugt Demo-Daten unter `./demo`. Dann in der Übersicht nacheinander **1 Einlesen → 2 Analysieren → 3 Vorschlag** starten, unter *Vorschlag & Prüfung* Ordner/Dateien freigeben und unter *Kopieren & Statistik* die Kopien erstellen.

Optionale Systemprogramme: **Tesseract** (OCR, Sprachpaket `deu`) und **LibreOffice** (Miniaturen für PPTX/DOCX/XLSX). Ohne sie läuft alles weiter, nur ohne OCR bzw. ohne Office-Miniaturen.

## Eigene Computer & Festplatten

`config/fdv.example.yaml` nach `config/fdv.yaml` kopieren und anpassen:

```yaml
target:
  root: C:/Users/andreas/OneDrive/Future-Dateiverwaltung   # neuer Ordner in der Cloud
  structure: "{group}/{category}/{year}"                     # → 02_Beruf/Projekte/Phoenix/2025/…
computers:
  - id: pc-buero
    name: Büro-PC
    mode: local            # dieser Server liest selbst
    volumes:
      - { id: pc-c, name: "C:", path: "C:/Users/andreas", kind: internal }
      - { id: pc-d, name: "D:", path: "D:/", kind: internal }
  - id: laptop
    name: Laptop
    mode: agent            # Agent auf dem Laptop meldet sich beim Server
    volumes:
      - { id: laptop-c, name: "C:", path: "C:/Users/andreas", kind: internal }
```

### Weitere Computer (Agent)

Auf jedem weiteren Computer das Projekt installieren und den Agenten starten:

```bash
cd backend
python -m app.agent_client --server http://BUERO-PC:8800 --computer laptop --key GEHEIM \
  --target "C:/Users/andreas/OneDrive/Future-Dateiverwaltung" scan inventory copy
```

Der Agent liest nur, sendet Metadaten, Textauszüge, Hashes und Miniaturen an den Server, meldet das Programm-Inventar und führt freigegebene Kopien **lokal** in seinen Cloud-Sync-Ordner aus (`watch` = dauerhaft, alle 10 Min.). Für den Netzbetrieb `server.api_key` setzen (oder `FDV_API_KEY`).

## LLM

In *Einstellungen* wählbar:

- **Claude (Anthropic)** – `ANTHROPIC_API_KEY` auf dem Server setzen; Standardmodell `claude-opus-5-5` (konfigurierbar, z. B. `claude-haiku-5-5` für sehr große Bestände). Datenschutzmodus (Standard): nur Dateiname/Pfad/Metadaten werden gesendet; Inhalte erst nach Aktivierung von *Dateiinhalte senden*.
- **Ollama (lokal)** – Inhalte verlassen den Rechner nicht.
- **Offline-Regeln** – Schlüsselwörter/Endungen, kostenlos; automatischer Fallback bei LLM-Fehlern.

**Claude testen:** `ANTHROPIC_API_KEY` setzen, Server neu starten, dann in *Einstellungen → Verbindung testen* oder per Skript:

```bash
cd backend
python ../scripts/test_llm.py                 # nur Metadaten an Claude (Datenschutzmodus)
python ../scripts/test_llm.py --content       # mit Textauszug – vergleicht Ergebnis mit den Offline-Regeln
python ../scripts/test_llm.py --model claude-haiku-5-5 "C:/Pfad/zur/Datei.pdf"
```

Ist der Key ungültig oder das Modell nicht verfügbar, bricht die App die LLM-Aufrufe für den laufenden Analyse-Job sofort ab (keine tausendfachen Fehlversuche) und nutzt die Offline-Regeln; die Übersicht zeigt dann „⚠ n× Offline-Regeln statt LLM“ mit der Ursache.

Identische Dateien (gleicher SHA-256) werden nur **einmal** analysiert – die Duplikate übernehmen das Ergebnis.

## Architektur

```
backend/app
├── main.py              FastAPI, liefert auch das gebaute Frontend aus
├── middleware.py        NoDelete (HTTP DELETE gesperrt), API-Key, Audit-Log, Timing
├── safety.py            einzige Schreibstelle: safe_copy (nie überschreiben, SHA-256, nur im Ziel)
├── connectors/          local (Festplatten), cloud (Sync-Ordner-Erkennung), Agent-Push über api/agents.py
├── agents/              scan · analysis · organizer · copy · inventory
├── skills/              filetype · extract · ocr · thumbnails · labels · importance · pathsuggest
├── llm/                 anthropic · ollama · rules  (+ 50 Kategorien in categories.py)
├── api/                 files (Explorer) · pipeline (Schritte, Vorschlag, Kopie) · system · agents
└── agent_client.py      Agent für weitere Computer
frontend/                React + TypeScript + Vite
```

Frontend-Ansichten: Übersicht (Pipeline, KPIs) · Explorer (Baum Computer › Festplatte › Ordner, Suche in Name/Inhalt/OCR/Labels, Filter nach Bereich, 50 Kategorien, Dateityp, Label, Speicherdatum, Duplikaten, Prüfstatus; Sortierung nach Wichtigkeit, Datum, Typ …; Liste/Galerie/**Seiten** – in der Seitenansicht sind bei PDF, PPTX, DOCX, XLSX (ein Bild je Tabellenblatt), PNG und JPEG alle Seiten direkt als Miniaturen sichtbar, Klick öffnet die Großansicht mit ←/→; Navigation und Ordnerbaum einklappbar (Strg+B); Detail mit Miniaturen aller Seiten, Labels, OCR, Duplikaten, Zielpfad) · Vorschlag & Prüfung · Kopieren & Statistik · Quellen & Agenten · Programme & LLMs · Einstellungen.

## Entwicklung

```bash
cd backend && python -m uvicorn app.main:app --reload --port 8800
cd frontend && npm run dev          # http://localhost:5173 (Proxy auf :8800)
cd backend && python -m pytest -q   # Tests: Read-only, keine Überschreibung, DELETE gesperrt
```
