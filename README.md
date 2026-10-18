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

Optionale Systemprogramme: **Tesseract** (OCR, Sprachpaket `deu`) und **LibreOffice** (Miniaturen für PPTX/DOCX/XLSX). Für Videos wird ffmpeg genutzt – aus dem PATH oder automatisch über das Python-Paket `imageio-ffmpeg`. Ohne sie läuft alles weiter, nur ohne OCR bzw. ohne Office-Miniaturen.

## Cloud-Konten über Schnittstelle

OneDrive/SharePoint (Microsoft Graph) und Google Drive lassen sich zusätzlich direkt anbinden: Einlesen **aller** Cloud-Dateien ohne Download, Duplikate zwischen lokal und Cloud, Deckblatt-Miniaturen von der Cloud und in Schritt 4 **serverseitige Kopien** in einen neuen Cloud-Ordner. Der Cloud-Client kann technisch nur lesen, Ordner anlegen und kopieren – nie löschen, verschieben oder überschreiben. Einrichtung: **[docs/CLOUD-API.md](docs/CLOUD-API.md)**.

## Ähnliche Dateien (nicht identisch)

Zusätzlich zu exakten Duplikaten (gleicher SHA-256) findet die App **zusammengehörige, aber unterschiedliche** Dateien – automatisch am Ende jeder Analyse oder über „Ähnliche Dateien › Neu suchen“:

| Art | Erkennung | Beispiel |
|---|---|---|
| **Versionen** | Dateiname ohne Versionsangaben (`_v2`, `final`, `Entwurf`, `(1)`, `Kopie von` …), bestätigt über den Textinhalt | `Angebot_v1.docx` · `Angebot_v2.docx` · `Angebot_final.pdf` |
| **Formate** | gleicher Text (MinHash ≥ 80 %), andere Endung – auch bei anderem Dateinamen | `Konzept.docx` ↔ `Export_Konzept.pdf` |
| **Ähnlicher Inhalt** | Text zu ≥ 60 % gleich | überarbeitete Fassung unter neuem Namen |
| **Ähnliche Fotos** | Bild-Fingerabdruck (pHash) – robust gegen Verkleinern, Bearbeiten, Neu-Komprimieren | `IMG_4203.jpg` ↔ `IMG_4203_bearbeitet.jpg` ↔ `Strand_klein.png` |

Je Gruppe wird eine Empfehlung markiert (★ höchste Versionsangabe bzw. neuestes Datum, bei Fotos die größte Datei); ältere Versionen erhalten das Label „Ältere Version“ und rutschen in der Wichtigkeit nach unten. Verschiedene Dokumente mit ähnlichem Namen (`Rechnung_045` / `Rechnung_046`, Protokolle mit anderem Datum) und gleichnamige Dateien mit völlig anderem Inhalt werden bewusst **nicht** zusammengefasst. In Schritt 4 lassen sich ältere Versionen auf Wunsch auslassen („Nur neueste Versionen kopieren“). Es wird nichts gelöscht oder zusammengeführt. Der Vergleich läuft über Kandidaten-Bänder (LSH) und schafft im Lasttest 100.000 Dateien in wenigen Sekunden.

## Automatik & Hintergrunddienst

**Zeitplan** (Seite „Automatik“ oder `automation:` in `fdv.yaml`): alle N Stunden, täglich oder wöchentlich zu einer Uhrzeit. Ein Durchgang liest alle Festplatten und Cloud-Konten ein, fordert die Agenten auf den anderen Computern zum Einlesen auf, analysiert neue und geänderte Dateien (inkl. Duplikate und ähnliche Dateien) und frischt das Programm-Inventar auf. Verpasste Termine (Computer war aus) werden einmal nachgeholt; läuft gerade ein anderer Job, wartet die Automatik.

- **Kosten:** Automatisch wird standardmäßig nur mit den Offline-Regeln eingeordnet. Das LLM lässt sich ausdrücklich zuschalten – mit eigenem Kostenlimit je Lauf. Offline eingeordnete Dateien holt die nächste manuelle LLM-Analyse nach.
- **Änderungsprotokoll:** Ab dem zweiten Einlesen einer Festplatte werden neue, geänderte, nicht mehr gefundene und wieder aufgetauchte Dateien protokolliert. Wird eine bereits **freigegebene** Datei geändert, setzt die App die Freigabe auf „offen“ zurück – die Freigabe galt dem alten Inhalt.
- **Kopieren nie automatisch:** Schritt 4 bleibt an die manuelle Prüfung gebunden. Die Automatik löscht, verschiebt und kopiert nichts.

**Als Hintergrunddienst einrichten** (startet bei jeder Anmeldung, ohne Fenster, Neustart bei Fehlern):

```powershell
# Windows (Aufgabenplanung) – Agent auf einem weiteren Computer
.\dienst-einrichten.ps1 agent --server http://BUERO-PC:8800 --computer laptop --key GEHEIM --target "$env:OneDrive\Future-Dateiverwaltung"
.\dienst-einrichten.ps1 server          # zentraler Server mit Oberfläche und Zeitplan
.\dienst-einrichten.ps1 status
.\dienst-einrichten.ps1 entfernen agent # Dienst austragen – Dateien bleiben unberührt
```

macOS (launchd) und Linux (systemd-Benutzerdienst): `./dienst-einrichten.sh …` mit denselben Befehlen; `--nur-anzeigen` zeigt vorher, was eingerichtet würde. Unter Windows wird bewusst die Aufgabenplanung „bei Anmeldung“ statt eines SYSTEM-Dienstes genutzt: So läuft der Agent als angemeldeter Benutzer und sieht dessen OneDrive/Google-Drive-Ordner. Der API-Key steht nicht in der Aufgabe, sondern in einer nur für den Benutzer lesbaren `agent.json`. Der Agent liest alle 24 Stunden (`--interval`) und auf Anforderung des Servers neu ein, meldet sich alle 10 Minuten und führt dabei nur freigegebene Kopien aus. Protokoll: `fdv-agent.log` (Pfad zeigt der Installer an).

## Probelauf auf einem echten Computer

Vor dem echten Einsatz: **[docs/PROBELAUF.md](docs/PROBELAUF.md)** – ein Ordner, Dateilimit, Trockenlauf, Vorher/Nachher-Nachweis, dass nichts verändert wurde, und ein Bericht zum Zurückmelden:

```powershell
.\probelauf.ps1 --ordner "$HOME\Documents" --max-dateien 2000      # Windows
./probelauf.sh --ordner ~/Documents --max-dateien 2000              # macOS
```

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

## Große Bestände, Cloud-Platzhalter, Kosten

**Cloud-Dateien „nur online“:** OneDrive, Google Drive, iCloud, Dropbox und Nextcloud legen für Dateien, die nur in der Cloud liegen, Platzhalter an. Die App erkennt sie allein über die Dateiattribute (Windows: `RECALL_ON_DATA_ACCESS`/`OFFLINE`, macOS: `SF_DATALESS`, iCloud `.icloud`, Nextcloud `.nextcloud`) und **liest ihren Inhalt nie** – kein Text, kein Hash, keine Miniatur, keine Kopie. Eingeordnet werden sie über Name, Pfad und Metadaten; sie tragen das Label „Nur online“ und lassen sich im Explorer filtern. Herunterladen nur auf ausdrücklichen Wunsch (Einstellungen, Kopier-Seite oder „Trotzdem herunterladen“ in der Detailansicht).

**Miniaturen-Strategie** (`analysis.thumbnails_mode`): `smart` (Standard) erzeugt für alle Dateien das Deckblatt und **alle Seiten sofort nur für wichtige Dateien** (Wichtigkeit ≥ 50); der Rest wird beim ersten Öffnen nachgeladen. `thumbs_budget_gb` begrenzt den Cache – bei Überschreitung werden zuerst Folgeseiten unwichtiger Dateien aus dem Cache entfernt (nie Nutzerdateien).

**Tempo:** Duplikate werden in drei Stufen gesucht (gleiche Größe → Schnell-Prüfsumme über 2 MB → SHA-256), die Suche nutzt einen Volltextindex (SQLite FTS5), Übersicht/Filterwerte werden zwischengespeichert und nach jedem Job vorberechnet. Eine abgebrochene Analyse wird nach einem Neustart **automatisch fortgesetzt**. Lasttest: `python scripts/benchmark.py --files 20000 --rows 500000` (Messwerte im Container: Einlesen ≈ 4.700 Dateien/s, Analyse offline ≈ 180 Dateien/s, Liste/Suche bei 500.000 Dateien 70–1.400 ms, zwischengespeicherte Auswertungen < 10 ms).

**Claude-Kosten:** Vor jeder Analyse mit Claude erscheint eine **Kostenschätzung mit Bestätigung** (Obergrenze, inkl. Vergleich Opus/Sonnet/Haiku). Optionen:
- **Nur unklare Dateien** (`llm.mode: unklare`): Was die Offline-Regeln sicher einordnen, kostet nichts.
- **Batch** (`llm.batch: true`): Anthropic Message Batches, 50 % günstiger, Ergebnis meist innerhalb einer Stunde; laufende Batches überstehen Neustarts.
- **Kostenlimit je Lauf** (`llm.max_cost_usd`): danach werden die restlichen Dateien offline eingeordnet.
Tatsächlich verbrauchte Tokens und Kosten werden je Aufruf gespeichert und in Übersicht und Einstellungen angezeigt. Preise (USD je 1 Mio. Tokens) stehen in `backend/app/config.py` und lassen sich unter `llm.prices` überschreiben.

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

Frontend-Ansichten: Übersicht (Pipeline, KPIs) · Explorer (Baum Computer › Festplatte › Ordner, Suche in Name/Inhalt/OCR/Labels, Filter nach Bereich, 50 Kategorien, Dateityp, Label, Speicherdatum, Duplikaten, Prüfstatus; Sortierung nach Wichtigkeit, Datum, Typ …; Liste/Galerie/**Seiten** – in der Seitenansicht sind bei PDF, PPTX, DOCX, XLSX (ein Bild je Tabellenblatt), PNG und JPEG alle Seiten direkt als Miniaturen sichtbar, bei **Videos** Standbilder über die Laufzeit (mit Zeitmarke, Player im Detail) und bei **E-Mails** (.eml, Outlook .msg) die Mail-Seite plus alle Seiten der Anhänge, Klick öffnet die Großansicht mit ←/→; Navigation und Ordnerbaum einklappbar (Strg+B); Detail mit Miniaturen aller Seiten, Labels, OCR, Duplikaten, ähnlichen Dateien, Zielpfad) · Ähnliche Dateien (Gruppen mit Vorschau, Empfehlung ★) · Vorschlag & Prüfung · Kopieren & Statistik · Quellen & Agenten · Automatik (Zeitplan, Änderungsprotokoll, Agenten) · Programme & LLMs · Einstellungen.

## Entwicklung

```bash
cd backend && python -m uvicorn app.main:app --reload --port 8800
cd frontend && npm run dev          # http://localhost:5173 (Proxy auf :8800)
cd backend && python -m pytest -q   # Tests: Read-only, keine Überschreibung, DELETE gesperrt
```
