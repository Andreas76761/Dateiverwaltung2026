# Cloud-Anbindung über Schnittstellen (OneDrive / SharePoint / Google Drive)

Zusätzlich zu den Sync-Ordnern kann Future Dateiverwaltung Cloud-Konten **direkt über die Schnittstelle** anbinden:

| | Sync-Ordner (bisher) | Schnittstelle (neu) |
|---|---|---|
| Welche Dateien | nur synchronisierte | **alle** Dateien im Konto (bzw. im gewählten Ordner) |
| Einlesen | über die Festplatte | Dateiliste von Microsoft Graph / Google Drive – **kein Download** |
| Duplikate | SHA-256 lokal | SHA-256 bzw. Prüfsumme der Cloud – Duplikate **zwischen lokal und Cloud** |
| Miniatur | aus der Datei | **Deckblatt direkt von der Cloud** (alle Seiten nur bei erlaubtem Download) |
| Schritt 4 (Kopie) | über den Sync-Client | **serverseitig in der Cloud** – nichts wird herunter- oder hochgeladen |
| Google Docs/Tabellen/Präsentationen | nur Verknüpfungsdateien | als Präsentation/Tabelle/Dokument erkannt und kopierbar |

**Sicherheit:** Die App fordert zuerst nur **Lesezugriff** an. Schreibzugriff („Kopieren erlauben“) ist ein eigener Schritt und wird nur für Schritt 4 gebraucht. Auch dann lässt der eingebaute Cloud-Client technisch nur drei Dinge zu: **lesen, Ordner anlegen, Dateien kopieren**. Löschen, Verschieben, Umbenennen, Überschreiben, Papierkorb und Freigaben werden vor dem Senden abgewiesen (getestet). Kopien entstehen in einem eigenen Ordner (`target_folder`, Standard „Future-Dateiverwaltung“); bei Namensgleichheit wird umbenannt, nie ersetzt.

Anmeldedaten (Tokens) liegen nur lokal in `data/cloud_tokens.json` (Dateirechte 600). „Trennen“ entfernt sie; zusätzlich kann der Zugriff jederzeit beim Anbieter widerrufen werden (Microsoft: account.live.com/consent/Manage, Google: myaccount.google.com/permissions).

## 1. App-Registrierung (einmalig)

Die App spricht im Namen deines Kontos mit Microsoft bzw. Google. Dafür braucht sie eine eigene, von dir angelegte **App-Registrierung** – so behältst du die volle Kontrolle, und es gibt keinen fremden Dienst dazwischen.

Rückleitungs-Adresse (Redirect URI) in beiden Fällen: **`http://localhost:8800/api/cloud/callback`**
(bei anderem Port entsprechend; steht auch unter *Quellen → Cloud-Konten*).

### Microsoft (OneDrive privat, OneDrive for Business, SharePoint)

1. https://entra.microsoft.com → *Anwendungen* → *App-Registrierungen* → **Neue Registrierung**
   (privates Microsoft-Konto: über https://portal.azure.com mit dem privaten Konto anmelden).
2. Name: `Future Dateiverwaltung`. Unterstützte Kontotypen:
   - nur privates OneDrive → „Nur persönliche Microsoft-Konten“ (`tenant: consumers`)
   - Firmen-OneDrive/SharePoint → „Nur Konten in diesem Organisationsverzeichnis“ (`tenant: <Verzeichnis-ID>`)
   - beides → „Konten in einem beliebigen Organisationsverzeichnis und persönliche Microsoft-Konten“ (`tenant: common`)
3. Umleitungs-URI: Plattform **„Mobilgeräte- und Desktopanwendungen“** (öffentlicher Client, kein Geheimnis nötig) → `http://localhost:8800/api/cloud/callback`.
4. *API-Berechtigungen* → Microsoft Graph → Delegiert: `Files.Read.All`, `User.Read`, `offline_access` (für „Kopieren erlauben“ zusätzlich `Files.ReadWrite.All`). Bei Firmenkonten ggf. Administrator-Zustimmung.
5. Die **Anwendungs-ID (Client-ID)** kopieren.

### Google Drive

1. https://console.cloud.google.com → Projekt anlegen → *APIs & Dienste* → **Google Drive API aktivieren**.
2. *OAuth-Zustimmungsbildschirm*: Typ „Extern“, dich selbst als Testnutzer eintragen.
3. *Anmeldedaten* → OAuth-Client-ID → Typ **„Webanwendung“**, autorisierte Weiterleitungs-URI `http://localhost:8800/api/cloud/callback`.
4. **Client-ID** und **Clientschlüssel** kopieren.

## 2. Konfiguration (`config/fdv.yaml`)

```yaml
cloud_api:
  # redirect_uri: http://localhost:8800/api/cloud/callback   # nur bei abweichendem Port/Host
  download_content: false      # true = Inhalte für die Analyse vorübergehend laden (Text, OCR, alle Seiten)
  download_max_mb: 25
  accounts:
    - id: onedrive-andreas
      provider: onedrive
      name: OneDrive Andreas
      client_id: "00000000-0000-0000-0000-000000000000"
      tenant: consumers                       # consumers | organizations | common | <Verzeichnis-ID>
      root: /                                 # nur diesen Ordner einlesen, z. B. /Dokumente
      target_folder: Future-Dateiverwaltung   # Schritt 4: serverseitige Kopien hierhin
    - id: gdrive-andreas
      provider: gdrive
      name: Google Drive
      client_id: "1234-abc.apps.googleusercontent.com"
      client_secret: "GOCSPX-…"
      root: /
      target_folder: Future-Dateiverwaltung
```

`client_secret` steht nur in deiner lokalen `config/fdv.yaml` (nicht im Git-Repository, siehe `.gitignore`).

## 3. Verbinden und nutzen

1. Server starten → *Quellen & Agenten* → *Cloud-Konten über Schnittstelle* → **Verbinden (lesen)** → im Fenster bei Microsoft/Google anmelden und zustimmen.
2. **Testen** zeigt die ersten Dateien, **Einlesen** liest das Konto ein (auch Schritt 1 in der Übersicht liest alle verbundenen Konten mit).
3. Analyse, Vorschlag, Freigabe wie gewohnt. Cloud-Dateien erscheinen im Explorer unter *Cloud-Konten (API)*; „In der Cloud öffnen“ springt zu OneDrive/Google Drive.
4. Für Schritt 4 einmal **Kopieren erlauben** (Schreibzugriff) – danach entstehen die Kopien serverseitig im Zielordner des jeweiligen Kontos. Wiederholte Läufe kopieren nichts doppelt.

**Grenzen:** Kopiert wird innerhalb desselben Kontos (OneDrive → OneDrive, Drive → Drive). OneDrive for Business liefert statt SHA-256 nur eine eigene Prüfsumme (quickXor) – Duplikate werden dort innerhalb von OneDrive erkannt, zu lokalen Dateien nur über Name/Größe nicht. Freigegebene Ablagen anderer („Für mich freigegeben“) werden nicht eingelesen.
