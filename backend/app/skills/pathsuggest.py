"""Skill: Vorschlag für neuen Pfad, Ordnerstruktur und Unterordner (rein virtuell)."""
from __future__ import annotations

from ..categories import GROUP_FOLDERS, Category
from ..config import get_settings
from ..safety import sanitize_rel


def pick_subfolder(cat: Category, name: str, text: str) -> str:
    hay = f"{name} {text[:2000]}".lower()
    for sf in cat.subfolders:
        stem = sf.lower()[:-1] if len(sf) > 5 else sf.lower()  # "Policen" -> "police"
        if stem in hay:
            return sf
    return ""


def suggest(cat: Category, name: str, year: int, month: int, file_type: str, subfolder: str = "") -> str:
    tpl = get_settings().target_structure
    category = cat.folder
    if subfolder and "{subcategory}" not in tpl:
        category = f"{cat.folder}/{subfolder}"
    rel = tpl.format(
        group=GROUP_FOLDERS.get(cat.group, cat.group),
        category=category,
        subcategory=subfolder,
        year=year,
        month=f"{month:02d}",
        type=file_type.replace(" & ", "_").replace(" ", "_"),
    )
    return sanitize_rel(f"{rel}/{name}")
