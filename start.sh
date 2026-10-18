#!/usr/bin/env bash
# Future Dateiverwaltung starten (Linux/macOS)
set -e
cd "$(dirname "$0")"
pip install -q -r backend/requirements.txt
# Frontend liegt fertig gebaut im Repository (frontend/dist) – Node.js nur zum Weiterentwickeln nötig
if [ ! -d frontend/dist ]; then (cd frontend && npm install && npm run build); fi
[ -d demo ] || [ -f config/fdv.yaml ] || python3 scripts/make_demo.py
cd backend && exec python3 -m app.run_server --port "${FDV_PORT:-8800}"   # HTTPS, wenn unter Einstellungen → Zugang eingeschaltet
