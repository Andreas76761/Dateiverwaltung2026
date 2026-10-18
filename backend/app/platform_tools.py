"""Betriebssystem-Unterschiede an einer Stelle: Programme finden (LibreOffice, Tesseract) und
Windows-Besonderheiten (lange Pfade, Groß-/Kleinschreibung).

Unter Windows und macOS liegen LibreOffice und Tesseract meist NICHT im PATH – sie werden daher auch an
den üblichen Installationsorten gesucht.
"""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"


def _first_existing(candidates: list[str]) -> str | None:
    for c in candidates:
        for p in ([c] if "*" not in c else sorted(Path(c).parent.glob(Path(c).name), reverse=True)):
            if Path(p).is_file():
                return str(p)
    return None


@lru_cache
def soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    if IS_WINDOWS:
        pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        return _first_existing([rf"{p}\LibreOffice\program\soffice.exe" for p in pf])
    if IS_MAC:
        return _first_existing(["/Applications/LibreOffice.app/Contents/MacOS/soffice"])
    return None


@lru_cache
def tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        return _first_existing([r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                                rf"{local}\Programs\Tesseract-OCR\tesseract.exe"])
    if IS_MAC:
        return _first_existing(["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"])
    return None


def long_path(p: str | Path) -> str:
    """Windows: Pfade über 260 Zeichen nur mit dem Präfix \\\\?\\ nutzbar (Lesen und Kopieren)."""
    s = str(p)
    if IS_WINDOWS and len(s) >= 240 and not s.startswith("\\\\?\\"):
        s = os.path.abspath(s)
        return "\\\\?\\UNC\\" + s[2:] if s.startswith("\\\\") else "\\\\?\\" + s
    return s


def norm(p: str) -> str:
    """Pfadvergleich: unter Windows ohne Groß-/Kleinschreibung."""
    return os.path.normcase(os.path.realpath(p))
