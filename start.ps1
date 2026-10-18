# Future Dateiverwaltung starten (Windows PowerShell) – danach http://localhost:8800
Set-Location $PSScriptRoot
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
if (-not $py) { Write-Host "Python 3.10+ fehlt: https://www.python.org/downloads/ (bei der Installation 'Add to PATH' anhaken)" -ForegroundColor Red; exit 1 }
& $py -m pip install -q -r backend\requirements.txt
# Frontend liegt fertig gebaut bei (frontend\dist) – Node.js nur zum Weiterentwickeln nötig
if (-not (Test-Path frontend\dist)) { Push-Location frontend; npm install; npm run build; Pop-Location }
if (-not (Test-Path demo) -and -not (Test-Path config\fdv.yaml)) { & $py scripts\make_demo.py }
Set-Location backend
& $py -m uvicorn app.main:app --host 0.0.0.0 --port 8800
