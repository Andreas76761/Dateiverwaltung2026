# Probelauf auf einem echten Computer

Ziel: Auf **einem** Computer mit **einem überschaubaren Ordner** prüfen, ob Einlesen, Analyse, Vorschlag und Kopie mit echten Daten funktionieren – ohne Risiko.

**Sicher, weil:**
- Quellordner werden nur gelesen. Der Probelauf vergleicht vorher/nachher Größe und Änderungsdatum **aller** gelesenen Dateien und meldet jede Abweichung.
- Standard ist ein **Trockenlauf**: Es wird nichts kopiert und kein Zielordner angelegt. Nur mit `--kopieren` entstehen Kopien – in einem eigenen Probe-Ordner.
- Cloud-Dateien „nur online“ werden erkannt und **nicht heruntergeladen**.
- Der Probelauf hat eine eigene Datenbank unter `~/.future-dateiverwaltung/probelauf` und berührt eine spätere echte Installation nicht.
- Claude wird nur mit `--claude` genutzt – mit Kostenschätzung, Bestätigung und Kostenlimit (Standard 1 $).

## 1. Vorbereitung (einmalig, ca. 10 Minuten)

| | Windows | macOS |
|---|---|---|
| Python 3.10+ (Pflicht) | [python.org](https://www.python.org/downloads/) – beim Installieren **„Add python.exe to PATH“** anhaken | `brew install python` oder python.org |
| Projekt | [ZIP herunterladen](https://github.com/Andreas76761/Dateiverwaltung2026/archive/refs/heads/main.zip) und entpacken, oder `git clone https://github.com/Andreas76761/Dateiverwaltung2026.git` | genauso |
| LibreOffice (optional – Miniaturen für PPTX/DOCX/XLSX) | [libreoffice.org](https://www.libreoffice.org/download/) | `brew install --cask libreoffice` |
| Tesseract (optional – OCR für Scans/Fotos) | [UB-Mannheim-Installer](https://github.com/UB-Mannheim/tesseract/wiki), dabei Sprache **German** auswählen | `brew install tesseract tesseract-lang` |

ffmpeg für Video-Standbilder wird automatisch über Python mitinstalliert. Node.js ist **nicht** nötig – die Oberfläche liegt fertig gebaut bei.

## 2. Probelauf starten

**Windows** – PowerShell im entpackten Projektordner öffnen (im Explorer: Adresszeile → `powershell` eintippen):

```powershell
.\probelauf.ps1                                     # Ordner "Dokumente", max. 2.000 Dateien
.\probelauf.ps1 --ordner "D:\Projekte\2025" --max-dateien 5000
```

Falls „Ausführung von Skripts deaktiviert“ erscheint: `powershell -ExecutionPolicy Bypass -File .\probelauf.ps1`

**macOS** – Terminal im Projektordner:

```bash
./probelauf.sh
./probelauf.sh --ordner ~/Projekte --max-dateien 5000
```

Empfehlung für den ersten Lauf: ein Ordner mit gemischten Dateien (PDFs, Office, Fotos, ein paar E-Mails) und – wenn vorhanden – zusätzlich ein OneDrive-Ordner mit „Nur online“-Dateien:

```powershell
.\probelauf.ps1 --ordner "$HOME\Documents\Steuer" --ordner "$HOME\OneDrive\Dokumente" --max-dateien 3000
```

### Optionen

| Option | Bedeutung |
|---|---|
| `--ordner PFAD` | Zu lesender Ordner, mehrfach möglich |
| `--max-dateien N` | Höchstens N Dateien je Ordner (Standard 2.000, `0` = alle) |
| `--claude --limit 1` | Zusätzlich Claude für unklare Dateien, max. 1 $ (vorher `$env:ANTHROPIC_API_KEY="sk-ant-…"` bzw. `export ANTHROPIC_API_KEY=…`) |
| `--inhalte` | Mit `--claude` auch Textauszüge senden (sonst nur Name/Pfad/Metadaten) |
| `--kopieren` | Kopien wirklich anlegen – im Probe-Ordner `…\OneDrive\Future-Dateiverwaltung-Probelauf` (oder `--ziel PFAD`) |
| `--anonym` | Bericht ohne Datei-/Ordnernamen (zum Teilen) |
| `--neu` | Probelauf-Datenbank vorher leeren |

## 3. Ergebnis ansehen

Der Bericht öffnet sich am Ende automatisch: `~/.future-dateiverwaltung/probelauf/probelauf-bericht.md`. Er enthält u. a.:
- ✅/❌ ob Quelldateien unverändert blieben
- Anzahl Dateien, Fehler, Nur-online-Dateien, Duplikate, Zeiten
- gefundene Programme (LibreOffice, Tesseract, ffmpeg) und Cloud-Ordner
- Verteilung Privat/Beruf/GenAI/Sonstiges, Top-Kategorien, Dateitypen
- die wichtigsten Dateien mit vorgeschlagenem neuen Pfad, unsichere Einordnungen

Die Oberfläche mit den Probelauf-Daten:

```powershell
cd backend
$env:FDV_CONFIG="$HOME\.future-dateiverwaltung\probelauf\probelauf.yaml"
py -m uvicorn app.main:app --port 8800          # dann http://localhost:8800
```

## 4. Zurückmelden

Den Bericht (`probelauf-bericht.md`, bei Bedarf mit `--anonym` erzeugt) in den Chat kopieren oder hochladen. Daraus werden Ausschlüsse, Kategorien, Wichtigkeit und die Konfiguration für den echten Lauf über alle 4 Computer abgestimmt.

**Alternativ** in einer Claude-Code-Session auf diesem Computer (Claude-Desktop-App oder `claude remote-control` im Projektordner): Dann kann Claude den Probelauf selbst ausführen und den Bericht direkt auswerten.
