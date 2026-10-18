"""Automatik: regelmäßig einlesen → neue und geänderte Dateien analysieren (inkl. ähnlicher Dateien) → Inventar.

- Zeitplan: alle N Stunden, täglich oder wöchentlich zu einer Uhrzeit (Ortszeit des Servers).
- Verpasste Läufe (Server war aus) werden beim nächsten Start einmal nachgeholt.
- Läuft gerade ein anderer Job, wartet die Automatik, bis er fertig ist.
- Kosten: automatisch nur Offline-Regeln, außer das LLM ist ausdrücklich erlaubt (dann mit eigenem Kostenlimit).
- Kopiert wird NIE automatisch – Schritt 4 bleibt an die manuelle Prüfung gebunden. Gelöscht wird nichts.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from . import db, jobs
from .config import get_settings

log = logging.getLogger("fdv.automatik")
TICK_S = 30
MODES = ("intervall", "täglich", "wöchentlich")
_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()
_enabled_since: datetime | None = None   # Bezugszeitpunkt für den ersten Lauf
_current: dict | None = None             # laufender Automatik-Durchgang


def _local(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None) if iso else None


def _hm(cfg: dict) -> tuple[int, int]:
    try:
        h, m = (int(x) for x in str(cfg.get("time", "02:30")).split(":")[:2])
        return min(max(h, 0), 23), min(max(m, 0), 59)
    except ValueError:
        return 2, 30


def last_run() -> dict | None:
    return db.one("SELECT * FROM automation_runs WHERE trigger='zeitplan' ORDER BY id DESC LIMIT 1")


def slots(cfg: dict, now: datetime, last: datetime | None, since: datetime) -> tuple[datetime | None, datetime]:
    """-> (fälliger Termin oder None, nächster Termin). Alle Zeiten naiv in Ortszeit."""
    mode = cfg.get("mode", "täglich")
    if mode == "intervall":
        step = timedelta(hours=max(float(cfg.get("interval_hours", 6) or 6), 0.25))
        nxt = (last or since) + step
        return (nxt if nxt <= now else None), (nxt if nxt > now else now)
    h, m = _hm(cfg)
    prev = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if mode == "wöchentlich":
        prev -= timedelta(days=(prev.weekday() - int(cfg.get("weekday", 6))) % 7)
        if prev > now:
            prev -= timedelta(days=7)
        nxt = prev + timedelta(days=7)
    else:
        if prev > now:
            prev -= timedelta(days=1)
        nxt = prev + timedelta(days=1)
    # fällig, wenn der letzte Termin noch nicht bedient wurde – auch nachträglich, z. B. wenn der Server nachts aus war
    due = prev if prev > (last or since) else None
    return due, nxt


def status() -> dict:
    cfg = get_settings().automation
    lr = last_run()
    now = datetime.now()
    due, nxt = slots(cfg, now, _local(lr["started_at"]) if lr else None, _since(cfg))
    runs = db.query("SELECT * FROM automation_runs ORDER BY id DESC LIMIT 15")
    for r in runs:
        r["summary"] = json.loads(r["summary"]) if r.get("summary") else {}
    return {"settings": cfg, "enabled": bool(cfg.get("enabled")), "running": _current,
            "next_run": (due or nxt).isoformat(timespec="minutes") if cfg.get("enabled") else None,
            "last_run": runs[0] if runs else None, "runs": runs, "thread_alive": bool(_thread and _thread.is_alive())}


def set_enabled_since(ts: datetime | None = None) -> None:
    global _enabled_since
    _enabled_since = ts or datetime.now()


def _since(cfg: dict) -> datetime:
    """Seit wann die Automatik aktiv ist (gespeichert beim Einschalten, sonst Serverstart)."""
    try:
        if cfg.get("enabled_since"):
            return datetime.fromisoformat(cfg["enabled_since"])
    except ValueError:
        pass
    return _enabled_since or datetime.now()


# ---------------------------------------------------------------- Durchgang

def _wait(job_id: int) -> dict:
    while not _stop.is_set():
        j = db.one("SELECT status, stats FROM jobs WHERE id=?", (job_id,))
        if j and j["status"] != "läuft":
            return {"status": j["status"], **(json.loads(j["stats"]) if j["stats"] else {})}
        time.sleep(1)
    return {"status": "abgebrochen"}


def busy() -> bool:
    return bool(jobs._running)


def run_cycle(trigger: str = "zeitplan") -> dict:
    """Einen Durchgang ausführen (blockierend). Startet nur, wenn gerade kein anderer Job läuft."""
    global _current
    from .agents import analysis_agent, inventory_agent, scan_agent

    with _lock:
        if _current or busy():
            return {"status": "übersprungen", "grund": "Es läuft bereits ein Job"}
        with db.tx() as c:
            run_id = c.execute("INSERT INTO automation_runs(trigger, status, started_at) VALUES (?, 'läuft', ?)",
                               (trigger, db.now())).lastrowid
        _current = {"id": run_id, "schritt": "Einlesen", "trigger": trigger}
    cfg = get_settings().automation
    summary: dict = {}
    status_ = "fertig"
    try:
        db.audit("automatik.start", {"run": run_id, "trigger": trigger})
        with db.tx() as c:  # Agenten auf anderen Computern lesen beim nächsten Abruf ebenfalls neu ein
            agents = c.execute("UPDATE computers SET scan_requested_at=? WHERE mode='agent'", (db.now(),)).rowcount
        summary["agenten_angefordert"] = agents
        sc = _wait(jobs.start("scan", scan_agent.run, {"auto": True}))
        summary["einlesen"] = {k: sc.get(k) for k in ("status", "dateien", "änderungen", "nicht_mehr_gefunden", "duplikatgruppen", "fehler")}
        if sc["status"] != "fertig":
            status_ = sc["status"]
        open_files = db.one("SELECT COUNT(*) n FROM files WHERE missing=0 AND status IN ('eingelesen', 'fehler')")["n"]
        if cfg.get("analyze", True) and open_files and status_ == "fertig":
            _current["schritt"] = "Analyse"
            params = analyze_params()
            use_llm = not params["nur_regeln"]
            an = _wait(jobs.start("analyze", analysis_agent.run, params))
            summary["analyse"] = {k: an.get(k) for k in ("status", "analysiert", "llm", "nur_regeln", "kosten_usd", "fehler")}
            summary["analyse"]["ähnliche_gruppen"] = (an.get("ähnlich") or {}).get("ähnlich_gruppen")
            summary["analyse"]["nur_regeln_auto"] = not use_llm
            if an["status"] != "fertig":
                status_ = an["status"]
        else:
            summary["analyse"] = {"status": "nicht nötig" if not open_files else "aus"}
        if cfg.get("inventory", True) and status_ == "fertig":
            _current["schritt"] = "Inventar"
            inv = _wait(jobs.start("inventory", inventory_agent.run, {"auto": True}))
            summary["inventar"] = {"status": inv["status"], "einträge": inv.get("einträge")}
        summary["kopieren"] = "nie automatisch – nur nach manueller Prüfung (Schritt 4)"
    except Exception as exc:  # Automatik darf den Server nie mitreißen
        log.exception("Automatik-Durchgang fehlgeschlagen")
        status_, summary["fehler"] = "fehler", str(exc)
    finally:
        with db.tx() as c:
            c.execute("UPDATE automation_runs SET status=?, finished_at=?, summary=? WHERE id=?",
                      (status_, db.now(), json.dumps(summary, ensure_ascii=False), run_id))
        _current = None
        db.audit("automatik.ende", {"run": run_id, "status": status_})
    return {"status": status_, "run_id": run_id, **summary}


def analyze_params() -> dict:
    cfg = get_settings().automation
    use_llm = bool(cfg.get("use_llm")) and get_settings().llm["provider"] != "rules"
    return {"auto": True, "nur_regeln": not use_llm, "confirmed": True,
            "max_cost_usd": float(cfg.get("max_cost_usd", 2.0) or 0) if use_llm else 0}


def after_agent_scan() -> None:
    """Ein Agent hat eine Festplatte fertig gemeldet → bei aktiver Automatik die neuen Dateien analysieren."""
    from .agents import analysis_agent

    cfg = get_settings().automation
    if cfg.get("enabled") and cfg.get("analyze", True) and not _current:
        jobs.start("analyze", analysis_agent.run, analyze_params())  # läuft schon eine Analyse, wird keine zweite gestartet


def tick(now: datetime | None = None) -> bool:
    """Prüft den Zeitplan; startet bei Fälligkeit einen Durchgang. -> True, wenn gestartet."""
    cfg = get_settings().automation
    if not cfg.get("enabled") or _current or busy():
        return False
    lr = last_run()
    due, _ = slots(cfg, now or datetime.now(), _local(lr["started_at"]) if lr else None, _since(cfg))
    if not due:
        return False
    threading.Thread(target=run_cycle, args=("zeitplan",), name="automatik", daemon=True).start()
    return True


def _loop() -> None:
    while not _stop.wait(TICK_S):
        try:
            tick()
        except Exception:
            log.exception("Automatik: Zeitplanprüfung fehlgeschlagen")


def start() -> None:
    global _thread
    _stop.clear()
    if _enabled_since is None:
        set_enabled_since()
    if not (_thread and _thread.is_alive()):
        _thread = threading.Thread(target=_loop, name="automatik-zeitplan", daemon=True)
        _thread.start()


def stop() -> None:
    _stop.set()
