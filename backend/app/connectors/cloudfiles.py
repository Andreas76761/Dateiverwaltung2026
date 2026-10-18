"""Erkennung von Cloud-Platzhaltern ("Nur online verfügbar").

OneDrive, Google Drive, Dropbox, iCloud und Nextcloud legen für Dateien, die nur in der Cloud liegen,
Platzhalter an. Wer deren INHALT liest (Text, Hash, Miniatur, Kopie), löst den Download aus – bei
großen Cloud-Ablagen im Extremfall alles. Deshalb erkennt die App Platzhalter allein anhand der
Metadaten (stat), die den Download NICHT auslösen, und liest von solchen Dateien nichts.

Erkannt werden:
- Windows (Cloud Files API: OneDrive, Google Drive, Dropbox, iCloud für Windows):
  FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, FILE_ATTRIBUTE_RECALL_ON_OPEN, FILE_ATTRIBUTE_OFFLINE
- macOS (File Provider: iCloud Drive, OneDrive, Google Drive, Dropbox): Flag SF_DATALESS
- iCloud (ältere macOS-Versionen): Platzhalter ".Name.ext.icloud"
- Nextcloud/ownCloud virtuelle Dateien: "Name.ext.nextcloud" / "Name.ext.owncloud"
- optional (Linux, FUSE-Mounts wie rclone): Größe > 0, aber keine belegten Blöcke
"""
from __future__ import annotations

FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
WINDOWS_ONLINE_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
SF_DATALESS = 0x40000000  # macOS <sys/stat.h>

VIRTUAL_SUFFIXES = (".nextcloud", ".owncloud")


def real_name(name: str) -> tuple[str, bool]:
    """Name eines Platzhalters → (echter Dateiname, ist_platzhalter_nach_namen)."""
    low = name.lower()
    for suf in VIRTUAL_SUFFIXES:
        if low.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)], True
    if name.startswith(".") and low.endswith(".icloud") and len(name) > 8:
        return name[1:-7], True
    return name, False


def is_online_only(st, name: str = "", sparse_heuristic: bool = False) -> bool:
    """True, wenn die Datei nur in der Cloud liegt. Nutzt ausschließlich stat()-Daten."""
    if real_name(name)[1]:
        return True
    attrs = getattr(st, "st_file_attributes", 0) or 0
    if attrs & WINDOWS_ONLINE_MASK:
        return True
    flags = getattr(st, "st_flags", 0) or 0
    if flags & SF_DATALESS:
        return True
    if sparse_heuristic and getattr(st, "st_blocks", None) == 0 and st.st_size > 0:
        return True
    return False
