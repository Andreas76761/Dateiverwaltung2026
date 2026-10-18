"""Connector für lokale Dateisysteme (rein lesend: os.scandir + stat)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..config import get_settings
from . import FileEntry
from .cloudfiles import is_online_only, real_name


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _under(path: str, parent: str) -> bool:
    path, parent = os.path.normcase(path), os.path.normcase(parent)  # Windows: C:\Users == c:\users
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def iter_files(root: str, errors: list[str] | None = None) -> Iterator[FileEntry]:
    s = get_settings()
    target = str(Path(s.target_root).resolve())
    data_dir = str(s.data_dir.resolve())
    root_p = Path(root)
    stack = [root_p]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except (PermissionError, FileNotFoundError, OSError) as exc:
            if errors is not None:
                errors.append(f"{current}: {exc}")
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=s.follow_symlinks):
                    full = os.path.realpath(e.path)
                    # Zielordner und eigenes Datenverzeichnis nie mit einlesen
                    if e.name in s.exclude_dirs or _under(full, target) or _under(full, data_dir):
                        continue
                    stack.append(Path(e.path))
                elif e.is_file(follow_symlinks=s.follow_symlinks):
                    if os.path.splitext(e.name)[1].lower() in s.exclude_ext or e.name.endswith(".fdv-partial"):
                        continue
                    # stat() liest nur Metadaten – löst bei Cloud-Platzhaltern KEINEN Download aus
                    st = e.stat(follow_symlinks=s.follow_symlinks)
                    name, _ = real_name(e.name)
                    rel = os.path.relpath(e.path, root_p).replace("\\", "/")
                    rel = rel[: len(rel) - len(e.name)] + name
                    yield FileEntry(
                        path=e.path,
                        rel_path=rel,
                        name=name,
                        size=st.st_size,
                        mtime=_iso(st.st_mtime),
                        ctime=_iso(getattr(st, "st_birthtime", st.st_ctime)),
                        online_only=is_online_only(st, e.name, s.cloud["sparse_heuristic"]),
                    )
            except OSError as exc:
                if errors is not None:
                    errors.append(f"{e.path}: {exc}")
