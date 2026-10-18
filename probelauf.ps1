# Future Dateiverwaltung – Probelauf unter Windows (PowerShell)
#   .\probelauf.ps1                                  # Dokumente, max. 2.000 Dateien, Trockenlauf
#   .\probelauf.ps1 --ordner "D:\Projekte" --max-dateien 5000
#   .\probelauf.ps1 --claude --limit 1               # mit Claude (vorher: $env:ANTHROPIC_API_KEY="...")
# Falls PowerShell das Skript blockiert:  powershell -ExecutionPolicy Bypass -File .\probelauf.ps1
Set-Location $PSScriptRoot
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
if (-not $py) { Write-Host "Python 3.10+ fehlt: https://www.python.org/downloads/ (bei der Installation 'Add to PATH' anhaken)" -ForegroundColor Red; exit 1 }
& $py -m pip install -q -r backend\requirements.txt
& $py scripts\probelauf.py @args
$bericht = Join-Path $HOME ".future-dateiverwaltung\probelauf\probelauf-bericht.md"
if (Test-Path $bericht) { Write-Host "`nBericht: $bericht" -ForegroundColor Green; notepad $bericht }
