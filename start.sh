#!/usr/bin/env bash
# Future Dateiverwaltung starten (Linux/macOS)
set -e
cd "$(dirname "$0")"
pip install -q -r backend/requirements.txt
if [ ! -d frontend/dist ]; then (cd frontend && npm install && npm run build); fi
[ -d demo ] || [ -f config/fdv.yaml ] || python3 scripts/make_demo.py
cd backend && exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${FDV_PORT:-8800}"
