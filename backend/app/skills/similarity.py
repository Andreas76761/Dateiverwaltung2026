"""Skill: Ähnliche Dateien erkennen – ergänzt die Duplikat-Erkennung (die nur exakt identische Dateien findet).

- Ähnliche Fotos:        Bild-Fingerabdruck (pHash, 64 Bit) – robust gegen Verkleinern, Komprimieren, Helligkeit.
- Versionen:            normalisierter Dateiname (Angebot_v2 / Angebot_final / Angebot (1) → "angebot"),
                         bestätigt über den Inhalt, wenn beide Dateien Text haben.
- Gleicher Inhalt in    Text-Fingerabdruck (MinHash über Wortgruppen) – findet dasselbe Dokument als PDF und DOCX
  anderem Format:        oder stark überarbeitete Fassungen unter anderem Namen.

Nur lesend: Es wird nichts gelöscht, verschoben oder umbenannt.
"""
from __future__ import annotations

import math
import random
import re
from array import array
from hashlib import blake2b

try:
    import numpy as np
except ImportError:  # pragma: no cover – reine Python-Variante liefert identische Werte
    np = None

# ---------------------------------------------------------------- Text-Fingerabdruck (MinHash)

NPERM = 64          # Anzahl Hashfunktionen
BANDS = 16          # LSH: 16 Bänder × 4 Werte → Kandidaten ab ca. 50 % Ähnlichkeit
PHOTO_BANDS = 8     # pHash: 8 Bänder à 8 Bit – bei ≤ 7 abweichenden Bits stimmt mindestens eins überein
SHINGLE = 4         # Wortgruppen à 4 Wörter
MIN_WORDS = 25      # kürzere Texte sind für einen Vergleich zu wenig aussagekräftig
MAX_WORDS = 4000
_M64 = (1 << 64) - 1
_rnd = random.Random(7311)
_SEEDS = [_rnd.getrandbits(64) for _ in range(NPERM)]
_WORD = re.compile(r"[^\W_]+", re.U)


def _h64(s: str) -> int:
    return int.from_bytes(blake2b(s.encode("utf-8", "ignore"), digest_size=8).digest(), "little")


def _mix(z: int) -> int:  # splitmix64-Finalizer
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return z ^ (z >> 31)


def words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())[:MAX_WORDS]


def minhash(text: str) -> bytes | None:
    """64 × 32 Bit = 256 Byte. None, wenn der Text zu kurz ist."""
    w = words(text)
    if len(w) < MIN_WORDS:
        return None
    hs = {_h64(" ".join(w[i:i + SHINGLE])) for i in range(len(w) - SHINGLE + 1)}
    if np is not None:
        x = np.fromiter(hs, dtype=np.uint64, count=len(hs))[None, :] ^ np.array(_SEEDS, dtype=np.uint64)[:, None]
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        x = x ^ (x >> np.uint64(31))
        mins = [int(v) & 0xFFFFFFFF for v in x.min(axis=1)]
    else:
        mins = [min(_mix(h ^ s) for h in hs) & 0xFFFFFFFF for s in _SEEDS]
    return array("I", mins).tobytes()


def _sig(b: bytes | array) -> array:
    return b if isinstance(b, array) else array("I", b)


def jaccard(a: bytes | array, b: bytes | array) -> float:
    """Geschätzte Text-Ähnlichkeit 0..1 (Anteil gemeinsamer Wortgruppen)."""
    a, b = _sig(a), _sig(b)
    return sum(x == y for x, y in zip(a, b)) / len(a)


# ---------------------------------------------------------------- Bild-Fingerabdruck (pHash)

_N = 32
_COS = [[math.cos((2 * x + 1) * u * math.pi / (2 * _N)) for x in range(_N)] for u in range(8)]


def phash(path: str) -> str | None:
    """Perceptual Hash als 16-stellige Hex-Zahl. None bei (fast) einfarbigen Bildern."""
    from PIL import Image

    with Image.open(path) as im:
        im.draft("L", (_N * 4, _N * 4))  # JPEG: schnell verkleinert dekodieren
        g = im.convert("L").resize((_N, _N), Image.LANCZOS)
        px = list(g.tobytes())
    mean = sum(px) / len(px)
    if math.sqrt(sum((p - mean) ** 2 for p in px) / len(px)) < 4:
        return None
    rows = [px[i * _N:(i + 1) * _N] for i in range(_N)]
    # 2D-DCT, nur die 8×8 niedrigsten Frequenzen
    t = [[sum(_COS[u][x] * rows[x][y] for x in range(_N)) for y in range(_N)] for u in range(8)]
    d = [sum(t[u][y] * _COS[v][y] for y in range(_N)) for u in range(8) for v in range(8)]
    ac = sorted(d[1:])
    med = (ac[31] + ac[32]) / 2
    bits = 0
    for i, val in enumerate(d):
        if i and val > med:
            bits |= 1 << i
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


# ---------------------------------------------------------------- Versionen über den Dateinamen

_VERSION_RE = re.compile(
    r"(?<![a-z0-9äöüß])(?:v|ver|version|rev|revision|stand)[\s._-]?\d+(?:[._]\d+)*(?![a-z0-9äöüß])"
    r"|\(\d+\)|\[\d+\]", re.I)
VERSION_WORDS = {
    "final", "finale", "finalversion", "endgültig", "endgueltig", "entwurf", "draft", "korrigiert", "korrektur", "korr",
    "überarbeitet", "ueberarbeitet", "update", "updated", "aktuell", "neu", "new", "alt", "old", "kopie", "copy", "backup",
    "sicherung", "version", "fertig", "freigabe", "freigegeben", "signed", "unterschrieben", "edit", "bearbeitet", "von",
    "of", "ok", "rev", "wip", "vorlage",
}
GENERIC = {
    "dokument", "document", "unbenannt", "untitled", "neu", "bild", "image", "img", "scan", "foto", "photo", "datei", "file",
    "readme", "index", "test", "notizen", "notes", "liste", "tabelle", "präsentation", "presentation", "mappe", "mappe1",
    "dokument1", "screenshot", "download", "export", "data", "daten", "output", "main", "setup", "install", "license",
}


def name_key(name: str) -> tuple[str | None, str]:
    """-> (Schlüssel ohne Versionsangaben, entfernte Versionsangabe). Schlüssel None = zu allgemein."""
    stem = name.rsplit(".", 1)[0] if "." in name.strip(".") else name
    stem = stem.lower()
    tags = [m.group(0) for m in _VERSION_RE.finditer(stem)]
    stem = _VERSION_RE.sub(" ", stem)
    toks = [t for t in re.split(r"[^a-z0-9äöüß]+", stem) if t]
    kept = [t for t in toks if t not in VERSION_WORDS]
    tags += [t for t in toks if t in VERSION_WORDS]
    key = " ".join(kept)
    tag = " ".join(sorted(re.sub(r"\s+", "", t) for t in tags))
    if len(key.replace(" ", "")) < 4 or key in GENERIC or key.replace(" ", "").isdigit():
        return None, tag
    return key, tag


_FINAL = {"final", "finale", "finalversion", "endgültig", "endgueltig", "freigabe", "freigegeben", "signed", "unterschrieben", "fertig"}
_DRAFT = {"entwurf", "draft", "wip", "alt", "old", "vorlage"}


def version_rank(tag: str) -> float:
    """Rangfolge aus der Versionsangabe: Entwurf < ohne Angabe < v1 < v2 < … < final."""
    parts = set(tag.split())
    if parts & _FINAL:
        return 1e6
    m = re.search(r"(?:v|ver|version|rev|revision|stand)(\d+(?:[._]\d+)*)", tag)
    if m:
        nums = [int(x) for x in re.split(r"[._]", m.group(1))[:3]]
        return sum(n / 1000 ** i for i, n in enumerate(nums))
    if parts & _DRAFT:
        return -1
    return 0
