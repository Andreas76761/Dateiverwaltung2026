"""Connectoren liefern Datei-Einträge aus unterschiedlichen Quellen.

- local:  lokale Festplatten / externe Platten / Netzlaufwerke dieses Rechners
- cloud:  synchronisierte Cloud-Ordner (OneDrive, Google Drive, Dropbox, iCloud, Nextcloud)
- agent:  andere Computer – der Agent dort pusht seine Einträge an diesen Server (siehe agent_client.py)
"""
from dataclasses import dataclass


@dataclass
class FileEntry:
    path: str
    rel_path: str
    name: str
    size: int
    mtime: str
    ctime: str
    online_only: bool = False  # Cloud-Platzhalter: Inhalt liegt nur online → nie lesen
