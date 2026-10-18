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

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, actor TEXT, action TEXT, detail TEXT
);
"""

_lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def query(sql: str, params: tuple | list | dict = ()) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def one(sql: str, params: tuple | list | dict = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def audit(action: str, detail: Any = None, actor: str = "system") -> None:
    with tx() as c:
        c.execute(
            "INSERT INTO audit(ts, actor, action, detail) VALUES (?,?,?,?)",
            (now(), actor, action, json.dumps(detail, ensure_ascii=False) if detail is not None else None),
        )


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
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
