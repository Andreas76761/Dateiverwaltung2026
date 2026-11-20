# Future Dateiverwaltung – diesen Computer als Agent einrichten (Startmenü „Als Agent einrichten“).
# Der Agent liest hier die Festplatten ein (nur lesend) und meldet die Ergebnisse an den zentralen Server.
# Er startet bei jeder Anmeldung im Hintergrund. Die fertigen Angaben zeigt der Server unter Einrichtung → Agenten.
#
# Auch ohne Fragen nutzbar:
#   .\agent-einrichten.ps1 --server https://BUERO-PC:8800 --computer laptop --key GEHEIM --fingerprint AA:BB:…
#   .\agent-einrichten.ps1 status
#   .\agent-einrichten.ps1 entfernen agent      # Agent austragen – Dateien bleiben unberührt
$ErrorActionPreference = "Stop"
$py = Join-Path $PSScriptRoot "python\python.exe"
Set-Location (Join-Path $PSScriptRoot "app\backend")

if ($args.Count -gt 0) {
    if ($args[0] -in @("status", "entfernen")) { & $py -m app.service_install @args }
    else { & $py -m app.service_install agent @args }
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Future Dateiverwaltung – Agent einrichten" -ForegroundColor Cyan
Write-Host "Die Angaben findest du auf dem Server-Computer unter Einrichtung -> Agenten." -ForegroundColor Gray
Write-Host ""
$server = Read-Host "Adresse des Servers (z. B. https://BUERO-PC:8800)"
$computer = Read-Host "Kennung dieses Computers (z. B. laptop)"
$key = Read-Host "API-Schlüssel (leer lassen, wenn keiner vergeben ist)"
$fp = ""
if ($server -like "https*") { $fp = Read-Host "CA-Fingerabdruck des Servers (Einstellungen -> Zugang & Sicherheit)" }
$target = Read-Host "Zielordner für freigegebene Kopien auf diesem Computer (leer = keiner)"

$cmd = @("agent", "--server", $server, "--computer", $computer)
if ($key) { $cmd += @("--key", $key) }
if ($fp) { $cmd += @("--fingerprint", $fp) }
if ($target) { $cmd += @("--target", $target) }
& $py -m app.service_install @cmd
Write-Host ""
if ($LASTEXITCODE -eq 0) { Write-Host "Fertig. Der Agent startet ab jetzt bei jeder Anmeldung." -ForegroundColor Green }
else { Write-Host "Das hat nicht geklappt – Meldung oben beachten." -ForegroundColor Red }
Read-Host "Enter zum Schließen"
