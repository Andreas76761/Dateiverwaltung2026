#!/usr/bin/env bash
# Future Dateiverwaltung – Probelauf unter macOS/Linux
#   ./probelauf.sh                                    # Dokumente, max. 2.000 Dateien, Trockenlauf
#   ./probelauf.sh --ordner ~/Projekte --max-dateien 5000
#   ANTHROPIC_API_KEY=... ./probelauf.sh --claude --limit 1
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Python 3.10+ fehlt (macOS: brew install python)"; exit 1; }
"$PY" -m pip install -q -r backend/requirements.txt 2>/dev/null || "$PY" -m pip install -q --user -r backend/requirements.txt
"$PY" scripts/probelauf.py "$@"
B="$HOME/.future-dateiverwaltung/probelauf/probelauf-bericht.md"
[ -f "$B" ] && { echo; echo "Bericht: $B"; command -v open >/dev/null && open "$B" || true; }
