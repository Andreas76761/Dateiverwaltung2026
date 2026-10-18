"""Skill: Videos – Metadaten (Dauer, Auflösung, Codec) und Standbilder über die Laufzeit als Miniaturen.

Nutzt ffmpeg aus dem PATH oder – plattformunabhängig – das mitgelieferte Binary von `imageio-ffmpeg`.
Liest die Videodatei nur.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".webm", ".mpg", ".mpeg", ".3gp", ".mts"}


@lru_cache
def ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def available() -> bool:
    return ffmpeg_exe() is not None


def fmt_time(sec: float) -> str:
    sec = int(round(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def probe(path: str) -> dict:
    """Metadaten aus der ffmpeg-Ausgabe (ohne ffprobe, damit ein einzelnes Binary reicht)."""
    exe = ffmpeg_exe()
    if not exe:
        return {}
    r = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True, errors="ignore", timeout=60)
    out = r.stderr
    info: dict = {}
    if m := re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", out):
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if m := re.search(r"Stream #\S+.*?Video: (\w+).*?, (\d{2,5})x(\d{2,5})", out):
        info["video_codec"], info["width"], info["height"] = m.group(1), int(m.group(2)), int(m.group(3))
    if m := re.search(r"(\d+(?:\.\d+)?) fps", out):
        info["fps"] = float(m.group(1))
    if m := re.search(r"Stream #\S+.*?Audio: (\w+)", out):
        info["audio_codec"] = m.group(1)
    for key in ("title", "comment", "creation_time", "artist", "description"):
        if m := re.search(rf"^\s+{key}\s*:\s*(.+)$", out, re.M):
            info[key] = m.group(1).strip()
    return info


def describe(info: dict) -> str:
    """Kurzer Text für Suche und LLM-Klassifikation."""
    if not info:
        return ""
    parts = ["Video"]
    if "duration" in info:
        parts.append(f"Dauer {fmt_time(info['duration'])}")
    if "width" in info:
        parts.append(f"{info['width']}×{info['height']}")
    if "video_codec" in info:
        parts.append(info["video_codec"])
    if "audio_codec" in info:
        parts.append(f"Audio {info['audio_codec']}")
    text = " · ".join(parts)
    for key, label in (("title", "Titel"), ("description", "Beschreibung"), ("comment", "Kommentar"),
                       ("artist", "Autor"), ("creation_time", "Aufgenommen")):
        if info.get(key):
            text += f"\n{label}: {info[key]}"
    return text


def frames(path: str, out_dir: Path, width: int, count: int = 8) -> list[dict]:
    """Gleichmäßig verteilte Standbilder; Label = Zeitpunkt im Video."""
    exe = ffmpeg_exe()
    if not exe:
        return []
    info = probe(path)
    dur = info.get("duration") or 0
    n = max(1, min(count, int(dur // 2) or 1)) if dur else 1
    times = [dur * (i + 0.5) / n for i in range(n)] if dur else [0]
    res = []
    for i, t in enumerate(times, 1):
        p = out_dir / f"p{i:04d}.jpg"
        # -ss vor -i: schnelles Springen; nur EIN Bild dekodieren
        subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale='min({width},iw)':-2", "-q:v", "4", "-y", str(p)],
                       capture_output=True, timeout=120)
        if p.exists() and p.stat().st_size > 0:
            from PIL import Image

            with Image.open(p) as im:
                res.append({"page": len(res) + 1, "path": str(p), "width": im.width, "height": im.height,
                            "label": fmt_time(t)})
    return res
