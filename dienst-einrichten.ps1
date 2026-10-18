# Future Dateiverwaltung als Hintergrunddienst einrichten (Windows-Aufgabenplanung, startet bei Anmeldung)
#   .\dienst-einrichten.ps1 agent --server http://BUERO-PC:8800 --computer laptop --key GEHEIM --target "$env:OneDrive\Future-Dateiverwaltung"
#   .\dienst-einrichten.ps1 server                 # zentraler Server mit Oberfläche und Zeitplan
#   .\dienst-einrichten.ps1 status
#   .\dienst-einrichten.ps1 entfernen agent        # Dienst austragen – Dateien bleiben unberührt
Set-Location $PSScriptRoot
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
if (-not $py) { Write-Host "Python 3.10+ fehlt: https://www.python.org/downloads/ (bei der Installation 'Add to PATH' anhaken)" -ForegroundColor Red; exit 1 }
& $py -m pip install -q -r backend\requirements.txt
Set-Location backend
& $py -m app.service_install @args
