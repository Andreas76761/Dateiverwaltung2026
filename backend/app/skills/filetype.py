"""Skill: Dateityp erkennen."""
from __future__ import annotations

import mimetypes

TYPES = {
    "PDF": [".pdf"],
    "Präsentation": [".pptx", ".ppt", ".odp", ".key", ".pps", ".ppsx"],
    "Textdokument": [".docx", ".doc", ".odt", ".rtf", ".pages"],
    "Tabelle": [".xlsx", ".xls", ".xlsm", ".ods", ".csv", ".numbers"],
    "Text & Notizen": [".txt", ".md", ".markdown", ".rst", ".log", ".org"],
    "Bild": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".svg", ".raw", ".cr2", ".nef", ".arw", ".dng"],
    "Video": [".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".webm"],
    "Audio": [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"],
    "E-Mail": [".eml", ".msg"],
    "Quellcode": [".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".go", ".rs", ".cpp", ".c", ".h", ".php", ".rb", ".sql", ".sh", ".ps1", ".html", ".css", ".ipynb"],
    "Daten & Konfiguration": [".json", ".jsonl", ".yaml", ".yml", ".xml", ".toml", ".ini", ".conf", ".parquet", ".env"],
    "KI-Modell": [".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx"],
    "Archiv": [".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".iso"],
    "Programm": [".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".app", ".dll"],
    "E-Book": [".epub", ".mobi", ".azw3"],
}
EXT_TO_TYPE = {e: t for t, exts in TYPES.items() for e in exts}

TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".jsonl", ".yaml", ".yml", ".xml", ".toml",
             ".ini", ".conf", ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".go", ".rs", ".cpp",
             ".c", ".h", ".php", ".rb", ".sql", ".sh", ".ps1", ".html", ".css", ".eml", ".org", ".env"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
OFFICE_PAGED = {".pptx", ".ppt", ".odp", ".pps", ".ppsx", ".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".ods"}


def detect(name: str) -> tuple[str, str, str]:
    """-> (ext, file_type, mime)"""
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return ext, EXT_TO_TYPE.get(ext, "Sonstige"), mime
