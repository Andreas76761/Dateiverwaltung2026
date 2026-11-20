# Windows-Installationspaket

| Datei | Zweck |
|---|---|
| `build.ps1` | Stellt den Programmordner zusammen (Python „embeddable“, Bibliotheken, Programmcode, Oberfläche, Tesseract) und baut mit Inno Setup die `Setup.exe` |
| `FutureDateiverwaltung.iss` | Inno-Setup-Skript: Installation ohne Adminrechte nach `%LOCALAPPDATA%\Programs\Future Dateiverwaltung`, Startmenü, optional Desktop und Autostart |
| `starter.py` | Startmenü-Starter: legt beim ersten Start `%LOCALAPPDATA%\FutureDateiverwaltung\fdv.yaml` an, startet den Server ohne Konsolenfenster, öffnet den Browser, beendet geordnet (`--beenden`) |
| `agent-einrichten.ps1` | Startmenü „Diesen Computer als Agent einrichten“ (fragt Server, Kennung, Schlüssel, Fingerabdruck ab) |
| `smoke_test.py` | Prüft das installierte Paket (wird in GitHub Actions ausgeführt) |

**Bauen:** GitHub Actions → *Windows-Installationspaket* → *Run workflow*, oder einen Tag `v1.2.3` pushen (dann als Release veröffentlicht). Lokal auf Windows: `.\packaging\windows\build.ps1 -Version 1.2.3` (braucht Python 3.12 im PATH).

**Trennung Programm / Daten:** Programmdateien liegen unter `Programs\Future Dateiverwaltung` und werden bei Update/Deinstallation ersetzt bzw. entfernt. Einstellungen, Datenbank, Miniaturen und Protokolle liegen unter `%LOCALAPPDATA%\FutureDateiverwaltung` und werden **nie** gelöscht.
