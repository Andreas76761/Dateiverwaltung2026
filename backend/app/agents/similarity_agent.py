"""Ähnlichkeits-Agent: findet ähnliche Fotos, Versionen (Angebot_v2 / Angebot_final) und dasselbe Dokument
in anderem Format (PDF ↔ DOCX). Läuft nach jeder Analyse und kann einzeln gestartet werden.

Ergebnis ist reine Information in der Datenbank (Gruppen, Labels, Empfehlung „neueste Version“) –
an den Dateien selbst wird nichts verändert, nichts gelöscht.
"""
from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from itertools import combinations

from .. import db
from ..jobs import Job
from ..skills import similarity as sim
from .scan_agent import DUPKEY

log = logging.getLogger("fdv.ähnlich")

PHOTO_TYPES = ("Bild", "Video")
PHOTO_MAX_DIST = 6          # pHash: ≤ 6 von 64 Bit verschieden = ähnliches Foto
PHOTO_MAX_DIST_SAME_NAME = 12
TEXT_SIMILAR = 0.6          # ähnlicher Inhalt
TEXT_SAME = 0.8             # gleicher Inhalt (z. B. PDF ↔ DOCX)
TEXT_VERSION_MIN = 0.3      # gleicher Name, aber Inhalt völlig anders → keine Version
MAX_BUCKET = 500            # sehr große Kandidaten-Töpfe (Vorlagen, Logos) begrenzen
MAX_NAME_GROUP = 50         # mehr Dateien mit demselben Namen = Allerweltsname

KIND_ORDER = {"version": 4, "format": 3, "inhalt": 2, "foto": 1}
GROUP_KIND = {"version": "Versionen", "format": "Formate", "inhalt": "Inhalt", "foto": "Fotos"}
SIM_LABELS = ("Neueste Version", "Ältere Version", "Ähnliches Foto", "Ähnlicher Inhalt")


# ---------------------------------------------------------------- 1. Fingerabdrücke

def _image_source(f: dict, local: set[str]) -> str | None:
    """Kleinste verfügbare Bildquelle: vorhandene Miniatur (Video: mittleres Standbild), sonst das Original."""
    thumbs = db.query("SELECT path FROM thumbnails WHERE file_id=? ORDER BY page", (f["id"],))
    if thumbs:
        t = thumbs[len(thumbs) // 2] if f["file_type"] == "Video" else thumbs[0]
        if os.path.isfile(t["path"]):
            return t["path"]
    if f["file_type"] == "Bild" and f["computer_id"] in local and not f["online_only"] and os.path.isfile(f["path"]):
        return f["path"]
    return None


def signatures(job: Job | None = None) -> int:
    """Fingerabdrücke für neu analysierte Dateien berechnen (nur lesend)."""
    from ..config import get_settings

    local = {c["id"] for c in get_settings().computers if c["mode"] == "local"}
    rows = db.query("""SELECT id, computer_id, path, file_type, online_only, text_excerpt, ocr_text FROM files
                       WHERE status='analysiert' AND missing=0 AND (sim_sig_at IS NULL OR sim_sig_at < analyzed_at)""")
    done, pending = 0, []
    for f in rows:
        if job and job.cancelled:
            break
        mh = sim.minhash(f"{f['text_excerpt'] or ''} {f['ocr_text'] or ''}")
        ph = None
        if f["file_type"] in PHOTO_TYPES:
            src = _image_source(f, local)
            if src:
                try:
                    ph = sim.phash(src)
                except Exception as exc:  # beschädigtes Bild o. Ä. – kein Fingerabdruck
                    log.debug("pHash %s: %s", src, exc)
        pending.append((ph, mh, db.now(), f["id"]))
        done += 1
        if len(pending) >= 500:
            _save(pending)
            pending = []
            if job:
                job.update(progress=done, total=len(rows), message=f"Fingerabdrücke: {done}/{len(rows)}")
    _save(pending)
    return done


def _save(pending: list[tuple]) -> None:
    if pending:
        with db.tx() as c:
            c.executemany("UPDATE files SET phash=?, minhash=?, sim_sig_at=? WHERE id=?", pending)


# ---------------------------------------------------------------- 2. Paare finden

def _candidates() -> list[dict]:
    """Je Duplikatgruppe nur das Original – exakt identische Dateien sind Sache der Duplikat-Erkennung."""
    rows = db.query(f"""SELECT id, name, ext, file_type, size, mtime, phash, minhash, {DUPKEY} dk FROM files
                        WHERE missing=0 AND is_primary=1""")
    for r in rows:
        r["key"], r["tag"] = sim.name_key(r["name"])
        r["mh"] = sim._sig(r["minhash"]) if r["minhash"] else None
    return rows


def _pair_kind(a: dict, b: dict, same_name: bool) -> tuple[str, float] | None:
    if a["dk"] and a["dk"] == b["dk"]:
        return None
    diff_ext = (a["ext"] or "") != (b["ext"] or "")
    jac = sim.jaccard(a["mh"], b["mh"]) if a["mh"] and b["mh"] else None
    photos = a["file_type"] == b["file_type"] and a["file_type"] in PHOTO_TYPES and a["phash"] and b["phash"]
    dist = sim.hamming(a["phash"], b["phash"]) if photos else None
    if same_name:
        if jac is not None:
            if jac < TEXT_VERSION_MIN:
                return None  # gleicher Name, aber anderer Inhalt (z. B. zwei verschiedene „Notizen.txt“-Inhalte)
            if diff_ext and jac >= TEXT_SAME and a["tag"] == b["tag"]:
                return "format", jac
            return "version", jac
        if dist is not None:
            return ("foto", 1 - dist / 64) if dist <= PHOTO_MAX_DIST_SAME_NAME else None
        if a["tag"] or b["tag"]:  # ausdrückliche Versionsangabe im Namen, Inhalt nicht vergleichbar
            if diff_ext and a["tag"] == b["tag"]:
                return "format", 0.6
            return "version", 0.6
        return None
    if jac is not None and jac >= TEXT_SIMILAR:
        return ("format", jac) if diff_ext and jac >= TEXT_SAME else ("inhalt", jac)
    if dist is not None and dist <= PHOTO_MAX_DIST:
        return "foto", 1 - dist / 64
    return None


def find_pairs(rows: list[dict]) -> dict[tuple[int, int], tuple[str, float]]:
    pairs: dict[tuple[int, int], tuple[str, float]] = {}
    seen: set[tuple[int, int]] = set()

    def add(a: dict, b: dict, same_name: bool) -> None:
        k = (a["id"], b["id"]) if a["id"] < b["id"] else (b["id"], a["id"])
        if k in seen:
            return
        seen.add(k)
        r = _pair_kind(a, b, same_name)
        if r:
            pairs[k] = (r[0], round(r[1], 3))

    def compare(buckets) -> None:
        for members in buckets.values():
            if 1 < len(members) <= MAX_BUCKET:
                for a, b in combinations(members, 2):
                    add(a, b, a["key"] is not None and a["key"] == b["key"])

    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["key"]:
            by_name[r["key"]].append(r)
    for members in by_name.values():  # Versionen über den Namen
        if 1 < len(members) <= MAX_NAME_GROUP:
            for a, b in combinations(members, 2):
                add(a, b, True)
    del by_name
    # Inhalt bzw. Bild: nur Kandidaten mit einem gemeinsamen Band vergleichen – Band für Band (wenig Speicher)
    texts = [r for r in rows if r["minhash"]]
    width = len(texts[0]["minhash"]) // sim.BANDS if texts else 0
    for i in range(sim.BANDS):
        buckets: dict[bytes, list[dict]] = defaultdict(list)
        for r in texts:
            buckets[r["minhash"][i * width:(i + 1) * width]].append(r)
        compare(buckets)
    photos = [r for r in rows if r["phash"] and r["file_type"] in PHOTO_TYPES]
    for i in range(sim.PHOTO_BANDS):
        buckets = defaultdict(list)
        for r in photos:
            buckets[(r["file_type"], r["phash"][i * 2:i * 2 + 2])].append(r)
        compare(buckets)
    return pairs


# ---------------------------------------------------------------- 3. Gruppen bilden und speichern

def _groups(pairs: dict) -> list[list[int]]:
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    out: dict[int, list[int]] = defaultdict(list)
    for x in parent:
        out[find(x)].append(x)
    return [sorted(m) for m in out.values()]


def refresh(job: Job | None = None) -> dict:
    n_sig = signatures(job)
    if job:
        job.update(message="Ähnliche Dateien werden gesucht …")
    rows = _candidates()
    by_id = {r["id"]: r for r in rows}
    pairs = find_pairs(rows)
    groups = _groups(pairs)

    kind_of: dict[int, str] = {}
    for (a, b), (k, _) in pairs.items():
        for x in (a, b):
            if KIND_ORDER[k] > KIND_ORDER.get(kind_of.get(x, ""), 0):
                kind_of[x] = k

    updates, labels = [], []
    stats = Counter()
    older_bytes = 0
    for members in groups:
        gk = max((kind_of[m] for m in members), key=KIND_ORDER.get)
        kind = GROUP_KIND[gk]
        ms = [by_id[m] for m in members]
        if kind == "Fotos":  # größte Auflösung/Datei = beste Qualität
            best = max(ms, key=lambda r: (r["size"] or 0, r["mtime"] or ""))
        else:  # höchste Versionsangabe (final > v3 > v2 > Entwurf), dann neuestes Datum
            best = max(ms, key=lambda r: (sim.version_rank(r["tag"]), r["mtime"] or "", r["size"] or 0))
        exts = {(r["ext"] or "").lstrip(".").upper() for r in ms}
        for r in ms:
            # sim_best: 1 = Empfehlung, 2 = gleicher Inhalt wie die Empfehlung in anderem Format, 0 = andere Version/ähnlich
            k = (min(r["id"], best["id"]), max(r["id"], best["id"]))
            is_best = 1 if r is best else 2 if pairs.get(k, ("",))[0] == "format" else 0
            updates.append((members[0], len(members), kind, is_best, r["id"]))
            if kind == "Versionen":
                labels.append((r["id"], "Neueste Version" if is_best else "Ältere Version"))
                if not is_best:
                    stats["ältere_versionen"] += 1
                    older_bytes += r["size"] or 0
            elif kind == "Fotos":
                labels.append((r["id"], "Ähnliches Foto"))
            elif kind == "Inhalt":
                labels.append((r["id"], "Ähnlicher Inhalt"))
            for e in sorted(exts - {(r["ext"] or "").lstrip(".").upper()} - {""}) if kind != "Fotos" else ():
                labels.append((r["id"], f"Auch als {e}"))
        stats[f"gruppen_{kind.lower()}"] += 1

    before = {r["id"] for r in db.query("SELECT id FROM files WHERE sim_group IS NOT NULL")}
    with db.tx() as c:  # nur abgeleitete Metadaten – Dateien bleiben unberührt
        c.execute("UPDATE files SET sim_group=NULL, sim_count=1, sim_kind=NULL, sim_best=0 WHERE sim_group IS NOT NULL")
        c.executemany("UPDATE files SET sim_group=?, sim_count=?, sim_kind=?, sim_best=? WHERE id=?", updates)
        c.execute("DELETE FROM similar_pairs")
        c.executemany("INSERT INTO similar_pairs(a, b, kind, score) VALUES (?,?,?,?)",
                      [(a, b, k, s) for (a, b), (k, s) in pairs.items()])
        c.execute(f"""DELETE FROM labels WHERE source!='nutzer' AND (source='ähnlich' OR label LIKE 'Auch als %'
                      OR label IN ({','.join('?' * len(SIM_LABELS))}))""", SIM_LABELS)
        c.executemany("INSERT OR IGNORE INTO labels(file_id, label, source) VALUES (?,?,'ähnlich')", labels)
        changed = before | {u[-1] for u in updates}
        for fid in changed:
            db.fts_update(c, fid)
    _rescore(changed)
    return {"fingerabdrücke": n_sig, "ähnlich_gruppen": len(groups), "ähnlich_dateien": len(updates),
            "ältere_versionen_bytes": older_bytes, **stats}


def _rescore(ids: set[int]) -> None:
    """Wichtigkeit neu berechnen (ältere Versionen rutschen nach unten)."""
    from ..categories import find_category
    from ..skills import importance

    if not ids:
        return
    with db.tx() as c:
        for f in c.execute(f"SELECT * FROM files WHERE status='analysiert' AND id IN ({','.join(str(int(i)) for i in ids)})").fetchall():
            labels = {r["label"] for r in c.execute("SELECT label FROM labels WHERE file_id=?", (f["id"],))}
            score, reason = importance.score(find_category(f["category"]), labels, f["file_type"], f["mtime"],
                                             f["dup_count"], bool(f["is_primary"]), None, bool(f["pinned"]))
            c.execute("UPDATE files SET importance=?, importance_reason=? WHERE id=?", (score, reason, f["id"]))


def run(job: Job, params: dict) -> dict:
    if params.get("force"):
        with db.tx() as c:
            c.execute("UPDATE files SET sim_sig_at=NULL")
    return refresh(job)
