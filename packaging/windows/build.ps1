# Windows-Installationspaket bauen (läuft in GitHub Actions auf windows-latest, geht aber auch lokal).
#   .\packaging\windows\build.ps1 -Version 1.0.0
# Voraussetzung: Python 3.12 (64 Bit) als „python“ im PATH. Inno Setup 6 wird bei Bedarf über Chocolatey geholt.
# Ergebnis: packaging\windows\build\out\FutureDateiverwaltung-Setup-<Version>.exe
param(
    [string]$Version = "1.0.0",
    [string]$PyEmbed = "3.12.10",          # offizielles „embeddable package“ von python.org (gleiche Hauptversion wie python im PATH)
    [string]$Tesseract = "5.4.0.20240606",  # Texterkennung (UB Mannheim); leer = ohne Texterkennung bauen
    [switch]$NoInstaller                    # nur den Programmordner zusammenstellen
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$here = $PSScriptRoot
$root = (Resolve-Path "$here\..\..").Path
$build = Join-Path $here "build"
$dist = Join-Path $build "dist"
$dl = Join-Path $build "downloads"
Remove-Item $dist -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $dist, $dl, "$dist\app", "$dist\tools" | Out-Null

function Fetch($url, $file) {
    $out = Join-Path $dl $file
    if (-not (Test-Path $out)) { Write-Host "Lade $url"; Invoke-WebRequest $url -OutFile $out -UseBasicParsing }
    return $out
}

# 1) Python (embeddable) – eigenständig, ändert nichts an einer vorhandenen Python-Installation
$zip = Fetch "https://www.python.org/ftp/python/$PyEmbed/python-$PyEmbed-embed-amd64.zip" "python-$PyEmbed-embed-amd64.zip"
Expand-Archive $zip "$dist\python" -Force
$tag = ($PyEmbed.Split(".")[0..1] -join "")
# Suchpfade: Standardbibliothek, Bibliotheken, Programmcode – unabhängig vom Arbeitsordner
Set-Content "$dist\python\python$tag._pth" -Encoding ascii -Value @(
    "python$tag.zip", ".", "Lib\site-packages", "..\app\backend", "import site")

# 2) Bibliotheken (ohne Testwerkzeuge)
$req = Join-Path $build "requirements.txt"
Get-Content "$root\backend\requirements.txt" | Where-Object { $_ -notmatch "^\s*pytest" } | Set-Content $req
$hostVer = (& python -c "import sys; print(f'{sys.version_info[0]}{sys.version_info[1]}')")
if ($hostVer -ne $tag) { throw "python im PATH ist $hostVer, das Paket braucht $tag" }
& python -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: `
    --target "$dist\python\Lib\site-packages" -r $req
if ($LASTEXITCODE) { throw "pip install fehlgeschlagen" }

# 3) Programmcode, fertige Oberfläche, Beispielkonfiguration
robocopy "$root\backend\app" "$dist\app\backend\app" /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
Copy-Item "$root\backend\requirements.txt" "$dist\app\backend\"
robocopy "$root\frontend\dist" "$dist\app\frontend\dist" /E /NFL /NDL /NJH /NJS | Out-Null
New-Item -ItemType Directory -Force "$dist\app\config" | Out-Null
Copy-Item "$root\config\fdv.example.yaml" "$dist\app\config\"
Copy-Item "$here\starter.py", "$here\agent-einrichten.ps1" $dist
Set-Content "$dist\VERSION.txt" $Version

# 4) Texterkennung (optional): Tesseract aus dem Installer der UB Mannheim auspacken + deutsche Sprachdaten
if ($Tesseract) {
    try {
        $exe = Fetch "https://github.com/UB-Mannheim/tesseract/releases/download/v$Tesseract/tesseract-ocr-w64-setup-$Tesseract.exe" "tesseract-$Tesseract.exe"
        & 7z x $exe "-o$dist\tools\tesseract" -y | Out-Null
        Remove-Item "$dist\tools\tesseract\`$PLUGINSDIR", "$dist\tools\tesseract\tesseract-uninstall.exe" -Recurse -Force -ErrorAction SilentlyContinue
        $deu = Fetch "https://github.com/tesseract-ocr/tessdata_fast/raw/main/deu.traineddata" "deu.traineddata"
        Copy-Item $deu "$dist\tools\tesseract\tessdata\"
        # nur Deutsch, Englisch und Schrifterkennung behalten; Trainingsprogramme und Dokumentation weglassen
        $t = "$dist\tools\tesseract"
        Get-ChildItem "$t\tessdata" -Recurse -Filter *.traineddata | Where-Object { $_.BaseName -notin @("deu", "eng", "osd") } | Remove-Item -Force
        Remove-Item "$t\tessdata\script", "$t\doc", "$t\docs" -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem $t -Filter *.exe | Where-Object { $_.Name -ne "tesseract.exe" } | Remove-Item -Force
        Get-ChildItem $t -Filter *.html | Remove-Item -Force
        $langs = & "$dist\tools\tesseract\tesseract.exe" --list-langs 2>&1 | Out-String
        if ($langs -notmatch "deu" -or $langs -notmatch "eng") { throw "Sprachdaten fehlen: $langs" }
        Write-Host "Texterkennung enthalten (deu+eng)"
    } catch {
        Write-Warning "Texterkennung wird nicht mitgeliefert: $_"
        Remove-Item "$dist\tools\tesseract" -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 5) Bytecode vorab erzeugen (schnellerer erster Start; mit dem mitgelieferten Python)
& "$dist\python\python.exe" -m compileall -q -j 0 "$dist\app\backend" "$dist\python\Lib\site-packages" | Out-Null
$env:FDV_DATA_DIR = Join-Path $build "importcheck"  # nichts im Programmordner anlegen
& "$dist\python\python.exe" -c "import app.main, pymupdf, PIL, numpy, cryptography, yaml, pillow_heif, rawpy; print('Import-Prüfung ok')"
if ($LASTEXITCODE) { throw "Import-Prüfung fehlgeschlagen" }
Remove-Item Env:FDV_DATA_DIR
if (Test-Path "$dist\app\data") { throw "Unerwarteter Datenordner im Paket: $dist\app\data" }
$mb = [math]::Round(((Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 0)
Write-Host "Programmordner: $mb MB – größte Bestandteile:"
@(Get-ChildItem "$dist\python\Lib\site-packages" -Directory) + @(Get-ChildItem "$dist\tools" -Directory) + @(Get-Item "$dist\app") |
    ForEach-Object { [pscustomobject]@{ MB = [math]::Round(((Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1); Name = $_.Name } } |
    Sort-Object MB -Descending | Select-Object -First 15 | Format-Table -AutoSize | Out-String | Write-Host
if ($NoInstaller) { exit 0 }

# 6) Installer mit Inno Setup
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    choco install innosetup -y --no-progress | Out-Null
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
Push-Location $here
& $iscc /Q "/DAppVersion=$Version" "/DSourceDir=build\dist" FutureDateiverwaltung.iss
$rc = $LASTEXITCODE
Pop-Location
if ($rc) { throw "Inno Setup fehlgeschlagen ($rc)" }
Get-ChildItem "$build\out\*.exe" | ForEach-Object { Write-Host ("Fertig: {0} ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) }
