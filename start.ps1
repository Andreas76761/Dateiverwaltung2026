# Future Dateiverwaltung starten (Windows PowerShell)
Set-Location $PSScriptRoot
pip install -q -r backend\requirements.txt
if (-not (Test-Path frontend\dist)) { Push-Location frontend; npm install; npm run build; Pop-Location }
if (-not (Test-Path demo) -and -not (Test-Path config\fdv.yaml)) { python scripts\make_demo.py }
Set-Location backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8800
