; Future Dateiverwaltung – Windows-Installationspaket (Inno Setup 6)
; Gebaut von packaging\windows\build.ps1 (bzw. GitHub Actions „Windows-Installationspaket“).
;
; - Installation ohne Administratorrechte nach %LOCALAPPDATA%\Programs\Future Dateiverwaltung
; - Python, alle Bibliotheken, Oberfläche und (falls beim Bauen verfügbar) Texterkennung sind enthalten
; - Einstellungen und Daten liegen getrennt unter %LOCALAPPDATA%\FutureDateiverwaltung und bleiben bei
;   Update und Deinstallation erhalten. Das Programm löscht nie Nutzerdateien.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "build\dist"
#endif

[Setup]
AppId={{6F1C2E7A-3B9D-4C55-9A8E-0D7B2F41C9E3}
AppName=Future Dateiverwaltung
AppVersion={#AppVersion}
AppVerName=Future Dateiverwaltung {#AppVersion}
AppPublisher=Future Dateiverwaltung
DefaultDirName={localappdata}\Programs\Future Dateiverwaltung
DefaultGroupName=Future Dateiverwaltung
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=build\out
OutputBaseFilename=FutureDateiverwaltung-Setup-{#AppVersion}
SetupIconFile=fdv.ico
UninstallDisplayIcon={app}\fdv.ico
UninstallDisplayName=Future Dateiverwaltung
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
de.WelcomeLabel2=Dieses Programm installiert [name/ver] auf deinem Computer.%n%nDie App liest deine Dateien nur. Sie löscht und verschiebt nichts. Kopien in die neue Ordnerstruktur entstehen erst, nachdem du sie geprüft und freigegeben hast.%n%nPython und alle benötigten Bestandteile sind enthalten.

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; GroupDescription: "Zusätzlich:"
Name: "autostart"; Description: "Server bei der Anmeldung im Hintergrund starten (für Zeitplan und Agenten)"; GroupDescription: "Zusätzlich:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "fdv.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Future Dateiverwaltung"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\starter.py"""; WorkingDir: "{app}"; IconFilename: "{app}\fdv.ico"; Comment: "Server starten und Oberfläche öffnen"
Name: "{group}\Future Dateiverwaltung beenden"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\starter.py"" --beenden"; WorkingDir: "{app}"; IconFilename: "{app}\fdv.ico"
Name: "{group}\Diesen Computer als Agent einrichten"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\agent-einrichten.ps1"""; WorkingDir: "{app}"; IconFilename: "{app}\fdv.ico"; Comment: "Für die weiteren Computer: Festplatten einlesen und an den Server melden"
Name: "{group}\Einstellungen und Protokolle"; Filename: "{localappdata}\FutureDateiverwaltung"
Name: "{group}\Future Dateiverwaltung deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Future Dateiverwaltung"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\starter.py"""; WorkingDir: "{app}"; IconFilename: "{app}\fdv.ico"; Tasks: desktopicon
Name: "{userstartup}\Future Dateiverwaltung (Hintergrund)"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\starter.py"" --hintergrund"; WorkingDir: "{app}"; IconFilename: "{app}\fdv.ico"; Tasks: autostart

[Dirs]
Name: "{localappdata}\FutureDateiverwaltung"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\starter.py"""; WorkingDir: "{app}"; Description: "Future Dateiverwaltung jetzt starten"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; Server beenden und eingerichtete Hintergrundaufgaben austragen (nur die Aufgaben – keine Dateien)
Filename: "{app}\python\python.exe"; Parameters: """{app}\starter.py"" --beenden --still"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "Beenden"
Filename: "{app}\python\python.exe"; Parameters: "-m app.service_install entfernen agent"; WorkingDir: "{app}\app\backend"; Flags: runhidden waituntilterminated; RunOnceId: "AgentAustragen"
Filename: "{app}\python\python.exe"; Parameters: "-m app.service_install entfernen server"; WorkingDir: "{app}\app\backend"; Flags: runhidden waituntilterminated; RunOnceId: "ServerAustragen"

[UninstallDelete]
; nur die Programmdateien (inkl. zur Laufzeit erzeugter Zwischenspeicher) – Einstellungen und Daten bleiben
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\tools"

[Code]
procedure StopRunningServer();
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\python\python.exe')) then
    Exec(ExpandConstant('{app}\python\python.exe'), '"' + ExpandConstant('{app}\starter.py') + '" --beenden --still',
         ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningServer();  { Update: laufenden Server vorher beenden, damit Dateien ersetzt werden können }
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    MsgBox('Future Dateiverwaltung wurde entfernt.' + #13#10 + #13#10 +
           'Deine Einstellungen, die Datenbank und alle Kopien im Zielordner bleiben erhalten:' + #13#10 +
           ExpandConstant('{localappdata}\FutureDateiverwaltung'), mbInformation, MB_OK);
end;
