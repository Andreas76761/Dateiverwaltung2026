"""SQLite-Datenhaltung. Die DB enthält nur Metadaten – Originaldateien werden nie verändert."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS computers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    os TEXT,
    hostname TEXT,
    mode TEXT DEFAULT 'local',
    last_seen TEXT,
    agent_version TEXT
);
CREATE TABLE IF NOT EXISTS volumes (
    id TEXT PRIMARY KEY,
    computer_id TEXT NOT NULL REFERENCES computers(id),
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT DEFAULT 'internal',      -- internal | external | cloud
    total_bytes INTEGER,
    free_bytes INTEGER,
    last_scan TEXT
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    computer_id TEXT NOT NULL,
    volume_id TEXT NOT NULL,
    path TEXT NOT NULL,                -- absoluter Pfad auf dem jeweiligen Computer
    rel_path TEXT NOT NULL,            -- relativ zur Festplatte/Volume
    name TEXT NOT NULL,
    ext TEXT,
    file_type TEXT,                    -- Dokument, Präsentation, Bild, ...
    mime TEXT,
    size INTEGER,
    mtime TEXT,
    ctime TEXT,
    sha256 TEXT,
    quick_hash TEXT,
    page_count INTEGER,
    text_excerpt TEXT,
    ocr_text TEXT,
    summary TEXT,
    category TEXT,
    group_name TEXT,                   -- Privat | Beruf | GenAI | Sonstiges
    confidence REAL,
    importance INTEGER DEFAULT 0,      -- 0..100
    importance_reason TEXT,
    suggested_path TEXT,               -- Vorschlag relativ zu target.root
    final_path TEXT,                   -- vom Nutzer bestätigter/bearbeiteter Zielpfad
    review_status TEXT DEFAULT 'offen',-- offen | freigegeben | abgelehnt
    dup_group TEXT,                    -- sha256 bei Duplikaten
    dup_count INTEGER DEFAULT 1,
    is_primary INTEGER DEFAULT 1,      -- bestes Exemplar einer Duplikatgruppe
    status TEXT DEFAULT 'eingelesen',  -- eingelesen | analysiert | fehler
    error TEXT,
    llm_provider TEXT,
    pinned INTEGER DEFAULT 0,
    scanned_at TEXT,
    analyzed_at TEXT,
    missing INTEGER DEFAULT 0,
    UNIQUE(volume_id, rel_path)
);
CREATE INDEX IF NOT EXISTS ix_files_hash ON files(sha256);
CREATE INDEX IF NOT EXISTS ix_files_cat ON files(group_name, category);
CREATE INDEX IF NOT EXISTS ix_files_imp ON files(importance DESC);
CREATE INDEX IF NOT EXISTS ix_files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS ix_files_vol ON files(volume_id);

CREATE TABLE IF NOT EXISTS labels (
    file_id INTEGER NOT NULL REFERENCES files(id),
    label TEXT NOT NULL,
    source TEXT DEFAULT 'llm',         -- llm | regel | nutzer | ocr
    PRIMARY KEY (file_id, label)
);
CREATE INDEX IF NOT EXISTS ix_labels_label ON labels(label);

CREATE TABLE IF NOT EXISTS thumbnails (
    file_id INTEGER NOT NULL,
    page INTEGER NOT NULL,
    path TEXT NOT NULL,
    width INTEGER, height INTEGER,
    label TEXT,                        -- z. B. Video-Zeitpunkt "1:23" oder "Anhang: rechnung.pdf"
    PRIMARY KEY (file_id, page)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                -- scan | analyze | propose | copy | inventory
    status TEXT DEFAULT 'wartend',     -- wartend | läuft | fertig | fehler | abgebrochen
    params TEXT,
    progress INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    message TEXT,
    stats TEXT,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS copy_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    file_id INTEGER NOT NULL,
    computer_id TEXT,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    status TEXT DEFAULT 'geplant',     -- geplant | kopiert | übersprungen | fehler
    bytes INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0,
    message TEXT,
    created_at TEXT,
    done_at TEXT
);

CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    computer_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT,
    publisher TEXT,
    kind TEXT DEFAULT 'programm',      -- programm | llm-tool | llm-modell | dev-tool
    category TEXT,
    location TEXT,
    size INTEGER,
    source TEXT,
    seen_at TEXT,
    UNIQUE(computer_id, name, kind, location)
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER, file_id INTEGER, model TEXT,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
    cache_read INTEGER DEFAULT 0, cache_write INTEGER DEFAULT 0,
    batch INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0, ts TEXT
);

CREATE TABLE IF NOT EXISTS llm_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,            -- Anthropic msgbatch_…
    job_id INTEGER,
    model TEXT,
    file_ids TEXT,                     -- JSON-Liste
    status TEXT DEFAULT 'läuft',       -- läuft | fertig | abgebrochen | fehler
    created_at TEXT, finished_at TEXT, message TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, actor TEXT, action TEXT, detail TEXT
);
"""

_lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_local = threading.local()
_version = 0  # wird bei jedem Schreibvorgang erhöht (für Caches)


def _open(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # mit WAL sicher und deutlich schneller als FULL
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA cache_size=-65536")    # 64 MB Seiten-Cache
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")
    return conn


def connect() -> sqlite3.Connection:
    """Eine Verbindung je Thread (statt je Abfrage) – wichtig für Tempo bei großen Beständen."""
    path = str(get_settings().db_path)
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    conn = conns.get(path)
    if conn is None:
        conn = conns[path] = _open(path)
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Schreib-Transaktion (verschachtelbar – committet wird nur auf der äußersten Ebene)."""
    global _version
    with _lock:
        conn = connect()
        depth = getattr(_local, "depth", 0)
        _local.depth = depth + 1
        try:
            yield conn
            if depth == 0:
                conn.commit()
                _version += 1
        except Exception:
            if depth == 0:
                conn.rollback()
            raise
        finally:
            _local.depth = depth


def version() -> int:
    return _version


def query(sql: str, params: tuple | list | dict = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(sql, params).fetchall()]


_cache: dict[str, tuple[int, float, Any]] = {}


def cached(key: str, fn, max_age: float = 15.0):
    """Ergebnis teurer Auswertungen (Statistik, Filterwerte, Vorschlagsbaum) wiederverwenden,
    solange sich nichts geändert hat – bei laufenden Jobs höchstens max_age Sekunden alt."""
    import time

    hit = _cache.get(key)
    now_t = time.monotonic()
    if hit and (hit[0] == _version or now_t - hit[1] < max_age):
        return hit[2]
    val = fn()
    _cache[key] = (_version, now_t, val)
    return val


def one(sql: str, params: tuple | list | dict = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def audit(action: str, detail: Any = None, actor: str = "system") -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO audit(ts, actor, action, detail) VALUES (?,?,?,?)",
            (now(), actor, action, json.dumps(detail, ensure_ascii=False) if detail is not None else None),
        )


MIGRATIONS = [
    "ALTER TABLE thumbnails ADD COLUMN label TEXT",
    "ALTER TABLE thumbnails ADD COLUMN bytes INTEGER DEFAULT 0",
    "ALTER TABLE files ADD COLUMN online_only INTEGER DEFAULT 0",
    "ALTER TABLE files ADD COLUMN thumbs_complete INTEGER DEFAULT 0",
    "ALTER TABLE files ADD COLUMN rules_confidence REAL",
    "ALTER TABLE files ADD COLUMN remote_id TEXT",        # ID der Datei in OneDrive/Google Drive (Cloud-Schnittstelle)
    "ALTER TABLE files ADD COLUMN web_url TEXT",          # Link zum Öffnen in der Cloud
    "ALTER TABLE files ADD COLUMN remote_hash TEXT",      # Prüfsumme der Cloud (quickXor/SHA-1/MD5), falls kein SHA-256
    "CREATE INDEX IF NOT EXISTS ix_files_remote_hash ON files(remote_hash)",
    "CREATE INDEX IF NOT EXISTS ix_files_status ON files(status, missing)",
    "CREATE INDEX IF NOT EXISTS ix_files_size ON files(size)",
    "CREATE INDEX IF NOT EXISTS ix_files_order_imp ON files(pinned DESC, importance DESC)",
    "CREATE INDEX IF NOT EXISTS ix_files_order_mtime ON files(pinned DESC, mtime DESC)",
    "CREATE INDEX IF NOT EXISTS ix_files_type ON files(file_type)",
    "CREATE INDEX IF NOT EXISTS ix_files_missing_size ON files(missing, size)",  # schnelle Summen ohne Tabellenscan
    "CREATE INDEX IF NOT EXISTS ix_files_quick ON files(quick_hash)",
    "CREATE INDEX IF NOT EXISTS ix_files_review ON files(review_status)",
    "CREATE INDEX IF NOT EXISTS ix_thumbs_file ON thumbnails(file_id)",
    # Ähnliche Dateien (Fotos, Versionen, gleicher Inhalt in anderem Format) – siehe skills/similarity.py
    "ALTER TABLE files ADD COLUMN phash TEXT",
    "ALTER TABLE files ADD COLUMN minhash BLOB",
    "ALTER TABLE files ADD COLUMN sim_sig_at TEXT",
    "ALTER TABLE files ADD COLUMN sim_group INTEGER",
    "ALTER TABLE files ADD COLUMN sim_count INTEGER DEFAULT 1",
    "ALTER TABLE files ADD COLUMN sim_kind TEXT",         # Versionen | Formate | Inhalt | Fotos
    "ALTER TABLE files ADD COLUMN sim_best INTEGER DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS ix_files_sim ON files(sim_group)",
    "CREATE TABLE IF NOT EXISTS similar_pairs (a INTEGER NOT NULL, b INTEGER NOT NULL, kind TEXT, score REAL, PRIMARY KEY (a, b))",
    "CREATE INDEX IF NOT EXISTS ix_simpairs_b ON similar_pairs(b)",
    # Automatik: Änderungsprotokoll je Datei und Läufe des Zeitplans
    "ALTER TABLE volumes ADD COLUMN scan_count INTEGER DEFAULT 0",
    "ALTER TABLE computers ADD COLUMN scan_requested_at TEXT",      # Agent soll beim nächsten Abruf einlesen
    """CREATE TABLE IF NOT EXISTS file_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, file_id INTEGER NOT NULL,
       volume_id TEXT, kind TEXT NOT NULL, detail TEXT)""",          # neu | geändert | fehlt | wieder_da
    "CREATE INDEX IF NOT EXISTS ix_events_ts ON file_events(ts)",
    "CREATE INDEX IF NOT EXISTS ix_events_file ON file_events(file_id)",
    """CREATE TABLE IF NOT EXISTS automation_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT, status TEXT,
       started_at TEXT, finished_at TEXT, summary TEXT)""",
    # Programme & LLMs organisieren: normalisierte Namen, Modell-Merkmale, Fingerabdruck, aktueller Stand
    "ALTER TABLE programs ADD COLUMN norm_key TEXT",
    "ALTER TABLE programs ADD COLUMN display TEXT",
    "ALTER TABLE programs ADD COLUMN model_key TEXT",
    "ALTER TABLE programs ADD COLUMN quant TEXT",
    "ALTER TABLE programs ADD COLUMN format TEXT",
    "ALTER TABLE programs ADD COLUMN fingerprint TEXT",
    "ALTER TABLE programs ADD COLUMN active INTEGER DEFAULT 1",
    "CREATE INDEX IF NOT EXISTS ix_programs_norm ON programs(norm_key)",
    "CREATE INDEX IF NOT EXISTS ix_programs_model ON programs(model_key)",
    "CREATE TABLE IF NOT EXISTS program_recs (key TEXT PRIMARY KEY, status TEXT, note TEXT, updated_at TEXT)",
    # Volltextsuche über Name, Pfad, Zusammenfassung, Inhalt, OCR und Labels (rowid = files.id)
    "CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(name, path, body, tokenize='unicode61 remove_diacritics 2')",
]


def fts_update(c, file_id: int) -> None:
    """Suchindex einer Datei aktualisieren (nach Scan/Analyse/Label-Änderung)."""
    r = c.execute("""SELECT f.name, f.rel_path, COALESCE(f.summary,'') || ' ' || COALESCE(f.category,'') || ' ' ||
                     COALESCE(substr(f.text_excerpt,1,8000),'') || ' ' || COALESCE(substr(f.ocr_text,1,4000),'') || ' ' ||
                     COALESCE((SELECT group_concat(label,' ') FROM labels WHERE file_id=f.id),'') AS body
                     FROM files f WHERE f.id=?""", (file_id,)).fetchone()
    c.execute("DELETE FROM files_fts WHERE rowid=?", (file_id,))  # nur Suchindex
    if r:
        c.execute("INSERT INTO files_fts(rowid, name, path, body) VALUES (?,?,?,?)", (file_id, r["name"], r["rel_path"], r["body"]))


def fts_rebuild() -> int:
    with tx() as c:
        c.execute("DELETE FROM files_fts")
        c.execute("""INSERT INTO files_fts(rowid, name, path, body)
                     SELECT f.id, f.name, f.rel_path, COALESCE(f.summary,'') || ' ' || COALESCE(f.category,'') || ' ' ||
                     COALESCE(substr(f.text_excerpt,1,8000),'') || ' ' || COALESCE(substr(f.ocr_text,1,4000),'') || ' ' ||
                     COALESCE((SELECT group_concat(label,' ') FROM labels WHERE file_id=f.id),'') FROM files f""")
        return c.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0]


def fts_query(q: str) -> str:
    """Nutzereingabe → FTS5-Abfrage: jedes Wort als Präfix, alle Wörter müssen vorkommen."""
    import re

    words = [w for w in re.split(r"[^\w]+", q, flags=re.UNICODE) if w]
    return " AND ".join(f'"{w}"*' for w in words)


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        for m in MIGRATIONS:  # bestehende Datenbanken älterer Versionen nachrüsten
            try:
                c.execute(m)
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits
        fts_empty = c.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0] == 0
        has_files = c.execute("SELECT COUNT(*) FROM files").fetchone()[0] > 0
    if fts_empty and has_files:
        fts_rebuild()  # Suchindex für bestehende Datenbanken einmalig aufbauen
    sync_config_to_db()


def sync_config_to_db() -> None:
    """Computer und Festplatten aus der Konfiguration in die DB übernehmen."""
    s = get_settings()
    with tx() as c:
        for comp in s.computers:
            c.execute(
                """INSERT INTO computers(id, name, os, mode) VALUES (?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, os=excluded.os, mode=excluded.mode""",
                (comp["id"], comp["name"], comp.get("os"), comp["mode"]),
            )
            for v in comp["volumes"]:
                c.execute(
                    """INSERT INTO volumes(id, computer_id, name, path, kind) VALUES (?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name, path=excluded.path, kind=excluded.kind""",
                    (v["id"], comp["id"], v["name"], v["path"], v.get("kind", "internal")),
                )
        # Cloud-Konten über Schnittstelle (OneDrive/Google Drive): ein "Computer" mit je einem Laufwerk pro Konto
        from .connectors import cloud_api
        accs = cloud_api.accounts()
        if accs:
            c.execute("""INSERT INTO computers(id, name, os, mode) VALUES ('cloud-api', 'Cloud-Konten (API)', 'Cloud', 'cloud-api')
                         ON CONFLICT(id) DO NOTHING""")
            for a in accs:
                c.execute("""INSERT INTO volumes(id, computer_id, name, path, kind) VALUES (?, 'cloud-api', ?, ?, 'cloud-api')
                             ON CONFLICT(id) DO UPDATE SET name=excluded.name, path=excluded.path""",
                          (a.volume_id, a.name, f"{a.provider}://{a.id}/{a.root.strip('/')}"))
