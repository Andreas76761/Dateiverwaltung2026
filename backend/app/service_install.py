"""Future Dateiverwaltung als Hintergrunddienst einrichten – Agent oder zentraler Server.

    # Agent auf einem weiteren Computer (startet bei jeder Anmeldung, läuft im Hintergrund):
    python -m app.service_install agent --server http://BUERO-PC:8800 --computer laptop \
        --key GEHEIM --target "C:/Users/andreas/OneDrive/Future-Dateiverwaltung" --interval 24

    # Zentraler Server (Oberfläche + Zeitplan):
    python -m app.service_install server --config ../config/fdv.yaml

    python -m app.service_install status            # eingerichtete Dienste anzeigen
    python -m app.service_install entfernen agent   # Dienst wieder austragen (Dateien bleiben unberührt)
    … --nur-anzeigen                                # nur zeigen, was eingerichtet würde

Umsetzung je Betriebssystem:
- Windows: Aufgabenplanung („bei Anmeldung“, ohne Konsolenfenster, Neustart bei Fehler). Bewusst kein
  SYSTEM-Dienst: Der Agent läuft als angemeldeter Benutzer und sieht so OneDrive/Google Drive des Benutzers.
- macOS:  LaunchAgent (~/Library/LaunchAgents), startet bei Anmeldung, wird bei Absturz neu gestartet.
- Linux:  systemd-Benutzerdienst (~/.config/systemd/user), Restart=on-failure.

Der Dienst selbst ändert keine Nutzerdateien – er liest ein und kopiert nur freigegebene Dateien in den Cloud-Ordner.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

BACKEND = Path(__file__).resolve().parents[1]
LABEL = {"agent": "de.future-dateiverwaltung.agent", "server": "de.future-dateiverwaltung.server"}
TITLE = {"agent": "Future Dateiverwaltung Agent", "server": "Future Dateiverwaltung Server"}


def conf_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "FutureDateiverwaltung"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "FutureDateiverwaltung"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "future-dateiverwaltung"


def log_dir() -> Path:
    return Path.home() / "Library" / "Logs" if platform.system() == "Darwin" else conf_dir()


def python_exe(background: bool) -> str:
    """Unter Windows pythonw.exe (kein Konsolenfenster)."""
    exe = Path(sys.executable)
    if background and platform.system() == "Windows":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def command(role: str, conf_file: Path | None, server_config: str | None, port: int) -> tuple[list[str], dict]:
    """-> (Befehlszeile, Umgebungsvariablen)"""
    py = python_exe(True)
    if role == "agent":
        return [py, "-m", "app.agent_client", "--config", str(conf_file), "service"], {}
    cmd = [py, "-m", "app.run_server", "--port", str(port), "--log", str(log_dir() / "fdv-server.log")]
    if server_config:
        cmd += ["--config", str(Path(server_config).resolve())]
    return cmd, {}


def write_agent_config(a) -> Path:
    """Zugangsdaten nicht in die Aufgabe/Unit schreiben, sondern in eine nur für den Benutzer lesbare Datei."""
    d = conf_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "agent.json"
    data = {"server": a.server, "computer": a.computer, "key": a.key or "", "target": a.target,
            "interval_hours": a.interval, "poll_minutes": a.poll, "download_online_only": a.download_online_only,
            "log": str(log_dir() / "fdv-agent.log")}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


# ---------------------------------------------------------------- Dateien je Betriebssystem

def windows_task_xml(role: str, cmd: list[str], env: dict) -> str:
    args = " ".join(f'"{c}"' if " " in c else c for c in cmd[1:])
    prog = cmd[0]  # Einstellungen kommen über Argumente/Konfigurationsdatei – kein cmd.exe-Fenster nötig
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(TITLE[role])} – liest Dateien ein (nur lesend) und kopiert nur freigegebene Dateien.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><Delay>PT2M</Delay></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT5M</Interval><Count>999</Count></RestartOnFailure>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(prog)}</Command><Arguments>{escape(args)}</Arguments>
    <WorkingDirectory>{escape(str(BACKEND))}</WorkingDirectory></Exec></Actions>
</Task>
"""


def launchd_plist(role: str, cmd: list[str], env: dict) -> str:
    items = "".join(f"<string>{escape(c)}</string>" for c in cmd)
    envs = "".join(f"<key>{escape(k)}</key><string>{escape(v)}</string>" for k, v in env.items())
    log = log_dir() / f"fdv-{role}.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL[role]}</string>
  <key>ProgramArguments</key><array>{items}</array>
  <key>WorkingDirectory</key><string>{escape(str(BACKEND))}</string>
  <key>EnvironmentVariables</key><dict>{envs}</dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>{escape(str(log))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log))}</string>
</dict></plist>
"""


def systemd_unit(role: str, cmd: list[str], env: dict) -> str:
    q = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    envs = "".join(f'Environment="{k}={v}"\n' for k, v in env.items())
    return f"""[Unit]
Description={TITLE[role]}
After=network-online.target

[Service]
Type=simple
WorkingDirectory={BACKEND}
{envs}ExecStart={q}
Restart=on-failure
RestartSec=60
Nice=10
IOSchedulingClass=idle

[Install]
WantedBy=default.target
"""


def target_file(role: str) -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{LABEL[role]}.plist"
    if system == "Windows":
        return conf_dir() / f"{role}-aufgabe.xml"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user" / f"fdv-{role}.service"


def render(role: str, cmd: list[str], env: dict) -> str:
    system = platform.system()
    return windows_task_xml(role, cmd, env) if system == "Windows" else launchd_plist(role, cmd, env) if system == "Darwin" \
        else systemd_unit(role, cmd, env)


def _run(args: list[str], dry: bool) -> None:
    print("  $", " ".join(args))
    if not dry:
        subprocess.run(args, check=False)


def install(role: str, cmd: list[str], env: dict, dry: bool = False) -> Path:
    system = platform.system()
    path = target_file(role)
    text = render(role, cmd, env)
    print(f"{TITLE[role]} → {path}")
    if dry:
        print(text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-16" if system == "Windows" else "utf-8")
        log_dir().mkdir(parents=True, exist_ok=True)
    if system == "Windows":
        _run(["schtasks", "/Create", "/TN", TITLE[role], "/XML", str(path), "/F"], dry)
        _run(["schtasks", "/Run", "/TN", TITLE[role]], dry)
    elif system == "Darwin":
        uid = str(os.getuid())
        _run(["launchctl", "bootout", f"gui/{uid}/{LABEL[role]}"], dry)  # evtl. alte Version beenden
        _run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], dry)
    else:
        if shutil.which("systemctl"):
            _run(["systemctl", "--user", "daemon-reload"], dry)
            _run(["systemctl", "--user", "enable", "--now", f"fdv-{role}.service"], dry)
            print("  Tipp: Damit der Dienst auch ohne Anmeldung läuft: loginctl enable-linger $USER")
        else:
            print("  systemd nicht gefunden – bitte den Befehl aus ExecStart per Autostart/cron @reboot starten.")
    return path


def uninstall(role: str, dry: bool = False) -> None:
    """Nur den Dienst austragen – Nutzerdateien, Datenbank und Protokolle bleiben erhalten."""
    system = platform.system()
    path = target_file(role)
    if system == "Windows":
        _run(["schtasks", "/End", "/TN", TITLE[role]], dry)
        _run(["schtasks", "/Delete", "/TN", TITLE[role], "/F"], dry)
    elif system == "Darwin":
        _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL[role]}"], dry)
    elif shutil.which("systemctl"):
        _run(["systemctl", "--user", "disable", "--now", f"fdv-{role}.service"], dry)
    if path.exists() and not dry:
        path.rename(path.with_suffix(path.suffix + ".deaktiviert"))  # Dienstdefinition aufheben statt löschen
        print(f"  Dienstdefinition deaktiviert: {path}.deaktiviert")


def show_status() -> None:
    system = platform.system()
    for role in ("agent", "server"):
        p = target_file(role)
        print(f"{TITLE[role]}: {'eingerichtet' if p.exists() else 'nicht eingerichtet'} ({p})")
        if p.exists():
            if system == "Windows":
                _run(["schtasks", "/Query", "/TN", TITLE[role]], False)
            elif system == "Darwin":
                _run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL[role]}"], False)
            elif shutil.which("systemctl"):
                _run(["systemctl", "--user", "--no-pager", "status", f"fdv-{role}.service"], False)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Future Dateiverwaltung als Hintergrunddienst einrichten")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ag = sub.add_parser("agent", help="Agent auf diesem Computer einrichten")
    ag.add_argument("--server", required=True)
    ag.add_argument("--computer", required=True)
    ag.add_argument("--key", default=os.environ.get("FDV_API_KEY", ""))
    ag.add_argument("--target", help="Lokaler Cloud-Sync-Ordner für freigegebene Kopien")
    ag.add_argument("--interval", type=float, default=24, help="alle N Stunden einlesen (0 = nur auf Anforderung des Servers)")
    ag.add_argument("--poll", type=float, default=10, help="alle N Minuten beim Server melden / Kopieraufgaben abholen")
    ag.add_argument("--download-online-only", action="store_true")
    ag.add_argument("--nur-anzeigen", action="store_true")
    sv = sub.add_parser("server", help="Zentralen Server (Oberfläche + Zeitplan) einrichten")
    sv.add_argument("--config", help="Pfad zur fdv.yaml")
    sv.add_argument("--port", type=int, default=8800)
    sv.add_argument("--nur-anzeigen", action="store_true")
    rm = sub.add_parser("entfernen", help="Dienst austragen (Dateien bleiben unberührt)")
    rm.add_argument("rolle", choices=["agent", "server"])
    rm.add_argument("--nur-anzeigen", action="store_true")
    sub.add_parser("status", help="eingerichtete Dienste anzeigen")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        show_status()
    elif a.cmd == "entfernen":
        uninstall(a.rolle, a.nur_anzeigen)
    elif a.cmd == "agent":
        conf = conf_dir() / "agent.json" if a.nur_anzeigen else write_agent_config(a)
        cmd, env = command("agent", conf, None, 0)
        install("agent", cmd, env, a.nur_anzeigen)
        print(f"Konfiguration: {conf}\nProtokoll:     {log_dir() / 'fdv-agent.log'}")
    else:
        cmd, env = command("server", None, a.config, a.port)
        install("server", cmd, env, a.nur_anzeigen)
        print(f"Oberfläche: http://localhost:{a.port}  ·  Protokoll: {log_dir() / 'fdv-server.log'}")


if __name__ == "__main__":
    main()
