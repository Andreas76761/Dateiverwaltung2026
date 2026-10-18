"""Sicherheitsschicht: Quellbereiche sind READ-ONLY.

Diese Datei ist die EINZIGE Stelle der Anwendung, die schreibend auf das
Dateisystem außerhalb des Datenverzeichnisses zugreift – und zwar nur zum
Anlegen von Ordnern und Kopieren von Dateien innerhalb von `target.root`.
Eine Lösch-, Verschiebe- oder Umbenennungsfunktion existiert bewusst nicht.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from .config import get_settings
from .platform_tools import long_path


class SafetyError(Exception):
    pass


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def target_root() -> Path:
    return Path(get_settings().target_root)


def assert_in_target(p: Path, root: Path | None = None) -> Path:
    root = root or target_root()
    if not _inside(p, root):
        raise SafetyError(f"Schreibzugriff außerhalb des Zielordners verweigert: {p}")
    return p


# Unter Windows verbotene Namen (auch mit Endung, z. B. "CON.txt")
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize_rel(rel: str) -> str:
    """Zielpfad bereinigen – gültig unter Windows, macOS und Linux:
    keine absoluten Pfade, kein '..', keine verbotenen Zeichen/Namen, keine Punkte/Leerzeichen am Ende."""
    bad = '<>:"|?*'
    parts = []
    for part in rel.replace("\\", "/").split("/"):
        part = "".join("_" if ch in bad or ord(ch) < 32 else ch for ch in part).strip().rstrip(". ")
        if part in ("", ".", ".."):
            continue
        if part.split(".")[0].upper() in WIN_RESERVED:
            part = "_" + part
        parts.append(part[:120])
    return "/".join(parts)


def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(long_path(path), "rb") as fh:
        while b := fh.read(chunk):
            h.update(b)
    return h.hexdigest()


def safe_copy(src: str, rel_dst: str, expected_hash: str | None = None, root: Path | None = None) -> dict:
    """Kopiert src nach root/rel_dst. Überschreibt NIE. Verifiziert per SHA-256.

    Rückgabe: {status: kopiert|übersprungen, dst, bytes, verified, message}
    """
    root = root or target_root()
    src_p = Path(src)
    if not src_p.is_file():
        raise SafetyError(f"Quelle nicht gefunden: {src}")
    if _inside(src_p, root):
        raise SafetyError("Quelle liegt bereits im Zielordner")
    dst = assert_in_target(root / sanitize_rel(rel_dst), root)
    src_hash = expected_hash or sha256_file(src_p)

    if dst.exists():
        if dst.is_file() and sha256_file(dst) == src_hash:
            return {"status": "übersprungen", "dst": str(dst), "bytes": 0, "verified": True,
                    "message": "Identische Datei existiert bereits im Ziel"}
        stem, suf, i = dst.stem, dst.suffix, 2
        while (cand := dst.with_name(f"{stem} ({i}){suf}")).exists():
            if cand.is_file() and sha256_file(cand) == src_hash:
                return {"status": "übersprungen", "dst": str(cand), "bytes": 0, "verified": True,
                        "message": "Identische Datei existiert bereits im Ziel"}
            i += 1
        dst = cand

    os.makedirs(long_path(dst.parent), exist_ok=True)
    tmp = dst.with_name(dst.name + ".fdv-partial")
    shutil.copy2(long_path(src_p), long_path(tmp))  # Inhalt + Zeitstempel übernehmen (Windows: auch > 260 Zeichen)
    ok = sha256_file(tmp) == src_hash
    if not ok:
        # nur unsere eigene, unvollständige Temp-Datei im Zielordner wird entfernt
        assert_in_target(tmp, root)
        tmp.unlink(missing_ok=True)
        raise SafetyError("Prüfsumme nach Kopie stimmt nicht überein")
    os.replace(long_path(tmp), long_path(dst))
    return {"status": "kopiert", "dst": str(dst), "bytes": src_p.stat().st_size, "verified": True, "message": ""}
