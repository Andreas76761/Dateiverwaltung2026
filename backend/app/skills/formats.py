"""Skill: weitere Formate – Vorschau, Inhalt und Metadaten.

- HEIC/HEIF/AVIF (iPhone-Fotos): über pillow-heif; ohne das Paket unter macOS über `sips`.
- RAW-Kamerabilder (CR2/CR3, NEF, ARW, DNG, RAF, ORF, RW2 …): eingebettete JPEG-Vorschau (rawpy oder ohne
  Zusatzpaket direkt aus der Datei), notfalls vollständig entwickelt (rawpy).
- Mehrseitige TIFF-Dateien (Faxe, Scans): jede Seite als Miniatur und für die OCR.
- Fotos allgemein: EXIF (Aufnahmedatum, Kamera, Ort vorhanden) als Text für Suche und Einordnung.
- Archive (ZIP, TAR/TGZ, 7z/RAR mit 7-Zip): Inhaltsverzeichnis, Text enthaltener Dokumente, Vorschau enthaltener
  Bilder/PDFs/Office-Dateien – ausgepackt nur in den Speicher bzw. einen temporären Ordner, mit Größenlimits.
- Keynote, Pages, Numbers: über LibreOffice (alle Seiten + Text), sonst die im Dokument gespeicherte Vorschau.
- Audio (MP3, M4A, FLAC, WAV, OGG, Opus, WMA, AIFF): Titel/Interpret/Album/Jahr/Dauer, eingebettetes Cover
  und eine Wellenform als Miniatur.

Alle Funktionen lesen die Quelldatei nur.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # optional
    HEIF_OK = False
try:
    import mutagen  # noqa: F401

    MUTAGEN_OK = True
except Exception:  # optional – ohne mutagen: Dauer über ffmpeg, kein Cover
    MUTAGEN_OK = False

HEIC_EXTS = {".heic", ".heif", ".avif", ".hif"}
RAW_EXTS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".raf", ".orf", ".rw2", ".pef",
            ".srw", ".3fr", ".erf", ".kdc", ".mrw", ".x3f", ".raw", ".rwl", ".iiq"}
TIFF_EXTS = {".tif", ".tiff"}
ARCHIVE_EXTS = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar"}
IWORK_EXTS = {".key", ".pages", ".numbers"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif", ".alac", ".amr"}

MAX_MEMBER = 100 * 1024 * 1024     # größere Archiv-Einträge werden nicht ausgepackt (Schutz vor „Zip-Bomben“)
MAX_UNPACK_TOTAL = 300 * 1024 * 1024
MAX_MEMBERS_PREVIEW = 12
MAX_LIST = 400


# ---------------------------------------------------------------- Bilder

def _embedded_jpeg(path: str, limit: int = 40 * 1024 * 1024):
    """Größte eingebettete JPEG-Vorschau einer RAW-Datei – ohne Zusatzpaket (die meisten Kameras speichern eine)."""
    from PIL import Image

    with open(path, "rb") as fh:
        data = fh.read(limit)
    best, best_px = None, 0
    pos = 0
    tries = 0
    while tries < 40 and (pos := data.find(b"\xff\xd8\xff", pos)) != -1:
        tries += 1
        end = data.find(b"\xff\xd9", pos + 3)
        while end != -1:
            chunk = data[pos:end + 2]
            try:
                with Image.open(io.BytesIO(chunk)) as im:
                    im.load()
                    if im.width * im.height > best_px:
                        best, best_px = im.copy(), im.width * im.height
                break
            except Exception:
                end = data.find(b"\xff\xd9", end + 2)  # verschachtelte Marker: weiter bis zum passenden Ende
                if end - pos > 30 * 1024 * 1024:
                    break
        pos += 3
    return best


def _sips(path: str):
    """macOS-Bordmittel als Ausweg für HEIC ohne pillow-heif."""
    from PIL import Image

    if not shutil.which("sips"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "x.jpg"
        subprocess.run(["sips", "-s", "format", "jpeg", path, "--out", str(out)], capture_output=True, timeout=60)
        if out.exists():
            with Image.open(out) as im:
                im.load()
                return im.copy()
    return None


def open_image(path: str):
    """PIL-Bild für jedes unterstützte Bildformat (inkl. HEIC und RAW) oder None."""
    from PIL import Image

    ext = Path(path).suffix.lower()
    if ext in RAW_EXTS:
        try:
            import rawpy

            with rawpy.imread(path) as raw:
                try:
                    th = raw.extract_thumb()
                    if th.format == rawpy.ThumbFormat.JPEG:
                        return Image.open(io.BytesIO(th.data))
                    return Image.fromarray(th.data)
                except Exception:
                    return Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))
        except Exception:
            return _embedded_jpeg(path)
    if ext in HEIC_EXTS and not HEIF_OK:
        return _sips(path)
    return Image.open(path)


def image_frames(path: str, max_pages: int = 50):
    """Seiten eines Bildes – bei mehrseitigen TIFF-Dateien jede Seite (für Miniaturen und OCR)."""
    from PIL import ImageSequence

    im = open_image(path)
    if im is None:
        return
    with im:
        if getattr(im, "n_frames", 1) > 1 and Path(path).suffix.lower() in TIFF_EXTS:
            for i, frame in enumerate(ImageSequence.Iterator(im)):
                if i >= max_pages:
                    break
                yield frame.copy()
        else:
            yield im.copy()


def page_count(path: str) -> int:
    try:
        im = open_image(path)
        if im is None:
            return 0
        with im:
            return getattr(im, "n_frames", 1) if Path(path).suffix.lower() in TIFF_EXTS else 1
    except Exception:
        return 0


def photo_meta(path: str) -> dict:
    """EXIF: Aufnahmedatum, Kamera, Objektiv, Ort vorhanden, Größe."""
    from PIL import ExifTags

    meta: dict = {}
    try:
        im = open_image(path)
        if im is None:
            return meta
        with im:
            meta["width"], meta["height"] = im.size
            exif = im.getexif()
            if not exif and Path(path).suffix.lower() in RAW_EXTS:
                return meta
            tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            sub = exif.get_ifd(0x8769) if hasattr(exif, "get_ifd") else {}
            tags.update({ExifTags.TAGS.get(k, k): v for k, v in sub.items()})
            dt = tags.get("DateTimeOriginal") or tags.get("DateTime")
            if dt and re.match(r"\d{4}:\d\d:\d\d", str(dt)):
                d = str(dt)
                meta["taken"] = f"{d[8:10]}.{d[5:7]}.{d[0:4]} {d[11:16]}".strip()
                meta["year"] = int(d[:4])
            make, model = str(tags.get("Make", "")).strip(" \x00"), str(tags.get("Model", "")).strip(" \x00")
            if model and make and model.lower().startswith(make.split()[0].lower()):
                meta["camera"] = model  # „NIKON CORPORATION“ + „NIKON Z 6II“ → „NIKON Z 6II“
            elif make or model:
                meta["camera"] = f"{make} {model}".strip()
            if tags.get("LensModel"):
                meta["lens"] = str(tags["LensModel"]).strip()
            gps = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else {}
            if gps:
                meta["gps"] = True
    except Exception:
        pass
    return meta


def describe_photo(meta: dict, ext: str) -> str:
    if not meta or not (meta.get("taken") or meta.get("camera")):
        return ""  # ohne Kameradaten (z. B. Scan, Grafik) kein „Foto“-Text
    kind = "RAW-Foto" if ext in RAW_EXTS else "iPhone-/HEIC-Foto" if ext in HEIC_EXTS else "Foto"
    parts = [kind]
    if meta.get("taken"):
        parts.append(f"aufgenommen {meta['taken']}")
    if meta.get("camera"):
        parts.append(meta["camera"])
    if meta.get("lens"):
        parts.append(meta["lens"])
    if meta.get("width"):
        parts.append(f"{meta['width']}×{meta['height']}")
    if meta.get("gps"):
        parts.append("mit GPS-Position")
    return f"[{' · '.join(parts)}]" if len(parts) > 1 else ""  # Klammern: Regeln erkennen es als Metadaten, nicht als Text


# ---------------------------------------------------------------- Archive

def is_archive(name: str) -> bool:
    n = name.lower()
    return Path(n).suffix in ARCHIVE_EXTS or n.endswith((".tar.gz", ".tar.bz2", ".tar.xz"))


def _seven_zip() -> str | None:
    for exe in ("7z", "7zz", "7za"):
        if p := shutil.which(exe):
            return p
    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if os.path.isfile(p):
            return p
    return None


def archive_entries(path: str) -> list[dict]:
    """Inhaltsverzeichnis: [{name, size, packed, dir, encrypted}] – ohne auszupacken."""
    n = path.lower()
    out: list[dict] = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                name = _zip_name(i)
                out.append({"name": name, "size": i.file_size, "packed": i.compress_size, "dir": i.is_dir(),
                            "encrypted": bool(i.flag_bits & 0x1)})
    elif n.endswith((".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz")) or (n.endswith((".gz", ".bz2", ".xz")) and tarfile.is_tarfile(path)):
        with tarfile.open(path) as t:
            for m in t:
                out.append({"name": m.name, "size": m.size, "packed": None, "dir": m.isdir(), "encrypted": False})
                if len(out) > 100000:
                    break
    elif n.endswith((".7z", ".rar")) and (exe := _seven_zip()):
        r = subprocess.run([exe, "l", "-slt", "-ba", path], capture_output=True, text=True, errors="ignore", timeout=120)
        cur: dict = {}
        for line in r.stdout.splitlines() + [""]:
            if not line.strip():
                if cur.get("Path"):
                    out.append({"name": cur["Path"].replace("\\", "/"), "size": int(cur.get("Size") or 0),
                                "packed": int(cur.get("Packed Size") or 0) if (cur.get("Packed Size") or "").isdigit() else None,
                                "dir": "D" in cur.get("Attributes", "")[:1] or cur.get("Folder") == "+",
                                "encrypted": cur.get("Encrypted") == "+"})
                cur = {}
            elif " = " in line:
                k, v = line.split(" = ", 1)
                cur[k.strip()] = v.strip()
    return out


def _zip_name(i: zipfile.ZipInfo) -> str:
    """Umlaute in alten ZIPs (cp437 statt UTF-8) korrekt anzeigen."""
    if i.flag_bits & 0x800:
        return i.filename
    try:
        return i.filename.encode("cp437").decode("cp850")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return i.filename


def _read_member(path: str, name: str, size: int) -> bytes | None:
    if size > MAX_MEMBER:
        return None
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if _zip_name(i) == name and not i.flag_bits & 0x1:
                    with z.open(i) as fh:
                        return fh.read(MAX_MEMBER + 1)[:MAX_MEMBER]
        return None
    try:
        with tarfile.open(path) as t:
            m = t.getmember(name)
            if not m.isfile():  # keine Links/Geräte
                return None
            fh = t.extractfile(m)
            return fh.read(MAX_MEMBER) if fh else None
    except (tarfile.TarError, KeyError, OSError):
        return None


def describe_archive(entries: list[dict]) -> str:
    files = [e for e in entries if not e["dir"]]
    total = sum(e["size"] or 0 for e in files)
    exts: dict[str, int] = {}
    for e in files:
        x = Path(e["name"]).suffix.lower() or "(ohne Endung)"
        exts[x] = exts.get(x, 0) + 1
    top = ", ".join(f"{n}× {x}" for x, n in sorted(exts.items(), key=lambda kv: -kv[1])[:8])
    head = f"Archiv mit {len(files)} {'Datei' if len(files) == 1 else 'Dateien'} ({_fmt(total)} entpackt)" + (f": {top}" if top else "")
    if any(e["encrypted"] for e in files):
        head += " · teilweise verschlüsselt"
    names = "\n".join(e["name"] for e in files[:MAX_LIST])
    return f"{head}\nInhalt:\n{names}"


def _fmt(n: int) -> str:
    v = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if v < 1024 or u == "GB":
            return f"{v:.0f} {u}" if u == "B" else f"{v:.1f} {u}".replace(".", ",")
        v /= 1024
    return ""


def archive_text(path: str, max_chars: int = 20000) -> str:
    """Inhaltsverzeichnis + Text der ersten enthaltenen Dokumente (für Suche und Einordnung)."""
    from . import extract
    from .filetype import TEXT_EXTS

    entries = archive_entries(path)
    text = describe_archive(entries)
    docs = [e for e in entries if not e["dir"] and not e["encrypted"] and e["size"] <= MAX_MEMBER
            and Path(e["name"]).suffix.lower() in TEXT_EXTS | {".pdf", ".docx", ".pptx", ".xlsx", ".odt", ".eml"}]
    budget = MAX_UNPACK_TOTAL
    with tempfile.TemporaryDirectory() as tmp:
        for i, e in enumerate(docs[:10]):
            if len(text) >= max_chars or budget <= 0:
                break
            data = _read_member(path, e["name"], e["size"])
            if not data:
                continue
            budget -= len(data)
            ext = Path(e["name"]).suffix.lower()
            f = Path(tmp) / f"m{i}{ext}"  # eigener Name – Pfade aus dem Archiv werden nie verwendet
            f.write_bytes(data)
            try:
                t, _ = extract.extract_text(str(f), ext)
            except Exception:
                continue
            if t:
                text += f"\n--- {e['name']} ---\n{t[:4000]}"
    return text[:max_chars]


# ---------------------------------------------------------------- Keynote / Pages / Numbers

IWORK_PREVIEWS = ("QuickLook/Preview.pdf", "preview.jpg", "QuickLook/Thumbnail.jpg", "preview-web.jpg", "Preview.pdf",
                  "QuickLook/Thumbnail.png", "preview-micro.jpg")


def is_iwork(path: str) -> bool:
    """Keynote/Pages/Numbers sind ZIP-Pakete. Eine „.key“-Datei ohne ZIP ist meist ein Schlüssel (z. B. TLS) –
    die wird bewusst NICHT an LibreOffice gegeben und nicht als Vorschau gezeigt."""
    return zipfile.is_zipfile(path)


def iwork_preview(path: str) -> tuple[bytes, str] | None:
    """Im Dokument gespeicherte Vorschau (PDF bei älteren, JPEG bei neueren Versionen)."""
    if not zipfile.is_zipfile(path):
        return None
    with zipfile.ZipFile(path) as z:
        names = {n.lower(): n for n in z.namelist()}
        for want in IWORK_PREVIEWS:
            if want.lower() in names:
                info = z.getinfo(names[want.lower()])
                if info.file_size <= MAX_MEMBER:
                    return z.read(info), Path(want).suffix.lower()
    return None


def iwork_text(path: str) -> str:
    """Text aus älteren iWork-Dateien (XML); neuere Dateien liest LibreOffice (siehe Miniaturen/PDF-Text)."""
    if not zipfile.is_zipfile(path):
        return ""
    import gzip

    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n in ("index.xml", "index.apxl", "Index/Document.xml") or n.endswith((".apxl", "index.xml.gz")):
                raw = z.read(n)
                if n.endswith(".gz"):
                    raw = gzip.decompress(raw)
                txt = re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "ignore"))
                return " ".join(txt.split())[:20000]
    return ""


# ---------------------------------------------------------------- Audio

def audio_meta(path: str) -> dict:
    meta: dict = {}
    try:
        import mutagen

        f = mutagen.File(path, easy=True)
        if f is not None:
            if f.info and getattr(f.info, "length", None):
                meta["duration"] = float(f.info.length)
            if getattr(f.info, "bitrate", None):
                meta["bitrate"] = int(f.info.bitrate)
            if getattr(f.info, "sample_rate", None):
                meta["sample_rate"] = int(f.info.sample_rate)
            for k in ("title", "artist", "album", "albumartist", "date", "genre", "tracknumber", "composer", "comment"):
                v = (f.tags or {}).get(k) if f.tags else None
                if v:
                    meta[k] = str(v[0] if isinstance(v, list) else v).strip()
    except Exception:
        pass
    if "duration" not in meta:  # ohne mutagen bzw. unbekanntes Format: ffmpeg
        from . import video
        info = video.probe(path)
        if info.get("duration"):
            meta["duration"] = info["duration"]
        for k in ("title", "artist"):
            if info.get(k) and k not in meta:
                meta[k] = info[k]
        if info.get("audio_codec"):
            meta["codec"] = info["audio_codec"]
    return meta


def describe_audio(meta: dict) -> str:
    if not meta:
        return ""
    from .video import fmt_time

    head = "Audio"
    if meta.get("duration"):
        head += f" · Dauer {fmt_time(meta['duration'])}"
    if meta.get("bitrate"):
        head += f" · {meta['bitrate'] // 1000} kbit/s"
    lines = [head]
    for k, label in (("title", "Titel"), ("artist", "Interpret"), ("album", "Album"), ("date", "Jahr"), ("genre", "Genre"),
                     ("composer", "Komponist"), ("comment", "Kommentar")):
        if meta.get(k):
            lines.append(f"{label}: {meta[k]}")
    return "\n".join(lines)


def audio_cover(path: str) -> bytes | None:
    """Eingebettetes Cover (ID3 APIC, MP4 covr, FLAC picture)."""
    try:
        import mutagen

        f = mutagen.File(path)
        if f is None:
            return None
        tags = f.tags or {}
        for k in list(getattr(tags, "keys", lambda: [])()):
            if str(k).startswith("APIC"):
                return tags[k].data
        if "covr" in tags and tags["covr"]:
            return bytes(tags["covr"][0])
        pics = getattr(f, "pictures", None)
        if pics:
            return pics[0].data
        for k in ("metadata_block_picture",):
            if k in tags:
                import base64

                from mutagen.flac import Picture
                return Picture(base64.b64decode(tags[k][0])).data
    except Exception:
        return None
    return None


def audio_waveform(path: str, out: Path, width: int = 900) -> bool:
    """Wellenform als Bild (ffmpeg showwavespic)."""
    from . import video

    exe = video.ffmpeg_exe()
    if not exe:
        return False
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-i", path, "-t", "1800", "-filter_complex",
                    f"[0:a]aformat=channel_layouts=mono,showwavespic=s={width}x260:colors=#4f46e5:scale=sqrt:draw=full[w];"
                    f"color=c=white:s={width}x260[bg];[bg][w]overlay=format=auto", "-frames:v", "1", "-q:v", "3", "-y", str(out)],
                   capture_output=True, timeout=180)
    if not out.exists() or out.stat().st_size == 0:
        return False
    return True
