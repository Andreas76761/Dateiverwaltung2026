"""Einfacher Hintergrund-Job-Runner mit Fortschritt, Statistik und Abbruch."""
from __future__ import annotations

import json
import logging
import threading
import traceback
from typing import Callable

from . import db

log = logging.getLogger("fdv.jobs")
_cancel: set[int] = set()
_running: dict[str, int] = {}
_lock = threading.Lock()


class Job:
    def __init__(self, job_id: int, kind: str):
        self.id = job_id
        self.kind = kind
        self.stats: dict = {}

    def update(self, progress: int | None = None, total: int | None = None, message: str | None = None, **stats):
        self.stats.update(stats)
        sets, vals = [], []
        for col, v in (("progress", progress), ("total", total), ("message", message)):
            if v is not None:
                sets.append(f"{col}=?")
                vals.append(v)
        sets.append("stats=?")
        vals.append(json.dumps(self.stats, ensure_ascii=False))
        with db.tx() as c:
            c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", (*vals, self.id))

    @property
    def cancelled(self) -> bool:
        return self.id in _cancel


def start(kind: str, fn: Callable[[Job, dict], dict | None], params: dict | None = None) -> int:
    """Startet einen Job im Hintergrund. Pro Job-Art läuft maximal einer gleichzeitig."""
    params = params or {}
    with _lock:
        if kind in _running:
            return _running[kind]
        with db.tx() as c:
            cur = c.execute(
                "INSERT INTO jobs(kind, status, params, created_at, started_at) VALUES (?,?,?,?,?)",
                (kind, "läuft", json.dumps(params, ensure_ascii=False), db.now(), db.now()),
            )
            job_id = cur.lastrowid
        _running[kind] = job_id

    def runner():
        job = Job(job_id, kind)
        status, msg = "fertig", None
        try:
            result = fn(job, params) or {}
            job.stats.update(result)
            if job.cancelled:
                status, msg = "abgebrochen", "Vom Nutzer abgebrochen"
        except Exception as exc:
            log.error("Job %s fehlgeschlagen: %s", job_id, traceback.format_exc())
            status, msg = "fehler", str(exc)
        finally:
            with db.tx() as c:
                c.execute(
                    "UPDATE jobs SET status=?, finished_at=?, stats=?, message=COALESCE(?, message) WHERE id=?",
                    (status, db.now(), json.dumps(job.stats, ensure_ascii=False), msg, job_id),
                )
            with _lock:
                _running.pop(kind, None)
                _cancel.discard(job_id)
            db.audit(f"job.{kind}.{status}", {"job_id": job_id, **job.stats})
            warm_caches()

    threading.Thread(target=runner, name=f"job-{kind}-{job_id}", daemon=True).start()
    return job_id


def warm_caches() -> None:
    """Teure Auswertungen nach einem Job im Hintergrund vorberechnen – die Oberfläche bekommt sie dann sofort."""
    def work():
        try:
            from .api import files, pipeline
            db.cached("stats", pipeline._stats, max_age=0)
            db.cached("facets", files._facets, max_age=0)
            pipeline.proposal_tree(False, None)
        except Exception:
            log.exception("Vorberechnung fehlgeschlagen")
    threading.Thread(target=work, name="warm-caches", daemon=True).start()


def cancel(job_id: int) -> None:
    _cancel.add(job_id)


def recover_stale() -> list[dict]:
    """Nach Neustart hängende Jobs als abgebrochen markieren. -> die betroffenen Jobs (zum Fortsetzen)"""
    stale = db.query("SELECT id, kind, params FROM jobs WHERE status='läuft'")
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='abgebrochen', message='Server neu gestartet – wird fortgesetzt' WHERE status='läuft'")
    return stale
