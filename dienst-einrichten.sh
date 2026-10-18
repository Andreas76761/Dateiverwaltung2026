#!/usr/bin/env bash
# Future Dateiverwaltung als Hintergrunddienst einrichten (macOS launchd / Linux systemd, startet bei Anmeldung)
#   ./dienst-einrichten.sh agent --server http://BUERO-PC:8800 --computer macbook --key GEHEIM --target ~/OneDrive/Future-Dateiverwaltung
#   ./dienst-einrichten.sh server                  # zentraler Server mit Oberfläche und Zeitplan
#   ./dienst-einrichten.sh status
#   ./dienst-einrichten.sh entfernen agent         # Dienst austragen – Dateien bleiben unberührt
set -e
cd "$(dirname "$0")"
python3 -m pip install -q -r backend/requirements.txt
cd backend && exec python3 -m app.service_install "$@"
