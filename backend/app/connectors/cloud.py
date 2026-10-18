"""Cloud-Connector: erkennt synchronisierte Cloud-Ordner auf diesem Computer.

Cloud-Speicher werden über ihre Desktop-Sync-Clients eingebunden (OneDrive, Google Drive
for Desktop, Dropbox, iCloud Drive, Nextcloud). Das hat zwei Vorteile:
1. Einlesen funktioniert wie bei lokalen Platten (read-only).
2. Schritt 4 kopiert in einen neuen Ordner innerhalb des Sync-Ordners – der Client lädt
   die Kopien automatisch in die Cloud hoch. Es werden keine Zugangsdaten benötigt.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

CANDIDATES = {
    "OneDrive": ["~/OneDrive", "~/OneDrive - *", "~/Library/CloudStorage/OneDrive-*"],
    "Google Drive": ["~/Google Drive", "~/My Drive", "G:/Meine Ablage", "G:/My Drive", "~/Library/CloudStorage/GoogleDrive-*"],
    "Dropbox": ["~/Dropbox", "~/Library/CloudStorage/Dropbox"],
    "iCloud Drive": ["~/Library/Mobile Documents/com~apple~CloudDocs", "~/iCloudDrive"],
    "Nextcloud": ["~/Nextcloud"],
}


def detect() -> list[dict]:
    found = []
    for provider, patterns in CANDIDATES.items():
        for pat in patterns:
            expanded = os.path.expanduser(pat)
            base = Path(expanded).parent
            name = Path(expanded).name
            try:
                matches = list(base.glob(name)) if "*" in name else ([Path(expanded)] if Path(expanded).exists() else [])
            except OSError:
                matches = []
            for m in matches:
                if m.is_dir():
                    found.append({"provider": provider, "path": str(m), "suggested_target": str(m / "Future-Dateiverwaltung")})
    for env, provider in (("OneDrive", "OneDrive"), ("OneDriveCommercial", "OneDrive Business")):
        if os.environ.get(env) and Path(os.environ[env]).is_dir():
            p = os.environ[env]
            if not any(f["path"] == p for f in found):
                found.append({"provider": provider, "path": p, "suggested_target": str(Path(p) / "Future-Dateiverwaltung")})
    return found


def host_info() -> dict:
    return {"hostname": platform.node(), "os": f"{platform.system()} {platform.release()}"}
