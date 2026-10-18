"""Automatik: Zeitplan, Änderungserkennung, Agent als Dienst, Dienst-Installer – und nie automatisch kopieren."""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import scheduler  # noqa: E402


def test_schedule_slots():
    daily = {"mode": "täglich", "time": "02:30"}
    since = datetime(2026, 10, 1, 12, 0)
    # vor 02:30 noch nichts fällig, danach einmal – auch nachgeholt, wenn der Server nachts aus war
    assert scheduler.slots(daily, datetime(2026, 10, 2, 1, 0), None, since)[0] is None
    due, nxt = scheduler.slots(daily, datetime(2026, 10, 2, 9, 0), None, since)
    assert due == datetime(2026, 10, 2, 2, 30) and nxt == datetime(2026, 10, 3, 2, 30)
    assert scheduler.slots(daily, datetime(2026, 10, 2, 9, 0), datetime(2026, 10, 2, 2, 31), since)[0] is None
    # erst eingeschaltet → kein Lauf für den Termin vor dem Einschalten
    assert scheduler.slots(daily, datetime(2026, 10, 1, 13, 0), None, since)[0] is None
    weekly = {"mode": "wöchentlich", "time": "03:00", "weekday": 6}
    due, nxt = scheduler.slots(weekly, datetime(2026, 10, 14, 8, 0), None, since)  # Mittwoch
    assert due == datetime(2026, 10, 11, 3, 0) and nxt.weekday() == 6
    iv = {"mode": "intervall", "interval_hours": 6}
    assert scheduler.slots(iv, datetime(2026, 10, 1, 17, 0), None, since)[0] is None
    assert scheduler.slots(iv, datetime(2026, 10, 1, 18, 1), None, since)[0] == datetime(2026, 10, 1, 18, 0)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    src = tmp_path / "pc" / "Dokumente"
    src.mkdir(parents=True)
    (src / "Vertrag_Miete.txt").write_text("Mietvertrag Wohnung Kündigungsfrist drei Monate Miete 900 EUR", encoding="utf-8")
    (src / "Notiz.txt").write_text("Einkaufsliste", encoding="utf-8")
    agent_root = tmp_path / "laptop"
    (agent_root / "Docs").mkdir(parents=True)
    (agent_root / "Docs" / "Rechnung_Laptop.txt").write_text("Rechnung Nr. 4711 Betrag 120 EUR", encoding="utf-8")
    target = tmp_path / "cloud" / "Ziel"
    cfg = {
        "server": {"data_dir": str(tmp_path / "data")},
        "target": {"root": str(target)},
        "analysis": {"ocr": False, "thumbnails": False},
        "llm": {"provider": "anthropic"},  # Automatik darf trotzdem nur offline arbeiten (use_llm: false)
        "computers": [
            {"id": "pc", "name": "PC", "volumes": [{"id": "pc-c", "name": "C", "path": str(tmp_path / "pc")}]},
            {"id": "laptop", "name": "Laptop", "mode": "agent", "volumes": [{"id": "lap-c", "name": "C", "path": str(agent_root)}]},
        ],
    }
    (tmp_path / "fdv.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(tmp_path / "fdv.yaml"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as client:
        yield client, src, target, agent_root


def wait_job(client, job_id):
    for _ in range(300):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "läuft":
            return j
        time.sleep(0.1)
    raise TimeoutError


def wait_cycle(client):
    for _ in range(300):
        st = client.get("/api/automation").json()
        if not st["running"] and st["last_run"] and st["last_run"]["status"] != "läuft":
            return st["last_run"]
        time.sleep(0.1)
    raise TimeoutError


def test_change_detection(env):
    client, src, target, _ = env
    wait_job(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    assert client.get("/api/changes").json()["items"] == []  # Erst-Scan erzeugt kein Protokoll
    wait_job(client, client.post("/api/pipeline/analyze", json={"confirmed": True}).json()["job_id"])
    client.post("/api/review", json={"action": "freigeben", "folder": ""})

    (src / "Vertrag_Miete.txt").write_text("Mietvertrag Wohnung – Nachtrag: Miete 950 EUR ab 2027, Kündigungsfrist drei Monate", encoding="utf-8")
    os.utime(src / "Vertrag_Miete.txt", (time.time() + 5, time.time() + 5))
    (src / "Neu_Angebot.txt").write_text("Angebot Fenster", encoding="utf-8")
    (src / "Notiz.txt").rename(src / "Notiz_umbenannt.txt")
    j = wait_job(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    assert j["stats"]["änderungen"] == {"neu": 2, "geändert": 1, "fehlt": 1, "wieder_da": 0}

    ch = client.get("/api/changes").json()
    kinds = {(i["kind"], i["name"]) for i in ch["items"]}
    assert ("geändert", "Vertrag_Miete.txt") in kinds and ("fehlt", "Notiz.txt") in kinds and ("neu", "Neu_Angebot.txt") in kinds
    changed = next(i for i in ch["items"] if i["kind"] == "geändert")
    assert "erneut prüfen" in changed["detail"] and changed["review_status"] == "offen"  # Freigabe galt dem alten Inhalt
    assert ch["recheck"] == 1


def test_cycle_scans_analyzes_never_copies(env):
    client, src, target, _ = env
    r = client.post("/api/automation", json={"enabled": True, "mode": "täglich", "time": "03:15"}).json()
    assert r["enabled"] and r["next_run"].endswith("03:15")
    assert client.post("/api/automation", json={"time": "25:00"}).status_code == 400

    assert client.post("/api/automation/run").json()["ok"]
    run = wait_cycle(client)
    assert run["status"] == "fertig" and run["trigger"] == "manuell"
    assert run["summary"]["einlesen"]["dateien"] == 2
    assert run["summary"]["analyse"]["analysiert"] == 2 and run["summary"]["analyse"]["nur_regeln_auto"]
    assert run["summary"]["agenten_angefordert"] == 1
    files = client.get("/api/files").json()["items"]
    assert all(f["status"] == "analysiert" for f in files)
    detail = client.get(f"/api/files/{files[0]['id']}").json()
    assert detail["llm_provider"] == "regeln (automatisch)"  # keine Cloud-Kosten ohne ausdrückliche Erlaubnis

    # Auch mit freigegebenen Dateien wird automatisch nichts kopiert
    client.post("/api/review", json={"action": "freigeben", "folder": ""})
    client.post("/api/automation/run")
    run = wait_cycle(client)
    assert run["summary"]["analyse"]["status"] == "nicht nötig"
    assert not target.exists()
    assert not any(j["kind"] == "copy" for j in client.get("/api/jobs").json())

    # Einstellungen überstehen einen Neustart
    overrides = json.loads((Path(os.environ["FDV_CONFIG"]).parent / "data" / "overrides.json").read_text(encoding="utf-8"))
    assert overrides["automation"]["enabled"] and overrides["automation"]["time"] == "03:15"


def test_tick_runs_when_due(env, monkeypatch):
    client, *_ = env
    from app.config import get_settings
    cfg = get_settings().automation
    cfg.update({"enabled": True, "mode": "intervall", "interval_hours": 1, "enabled_since": "2020-01-01T00:00:00"})
    assert scheduler.tick() is True
    run = wait_cycle(client)
    assert run["trigger"] == "zeitplan" and run["status"] == "fertig"
    assert scheduler.tick() is False  # nächster Termin erst in einer Stunde


def test_agent_service(env):
    client, _, target, agent_root = env
    from app.agent_client import Agent

    agent = Agent("http://testserver", "laptop", "", None, thumbs=False)
    agent.http = client  # TestClient ist ein httpx-Client
    agent.service(interval_h=0, once=True)  # 0 = nur auf Anforderung → noch nichts gelesen
    assert client.get("/api/files", params={"computer": "laptop"}).json()["total"] == 0
    client.post("/api/agents/laptop/request-scan")
    agent.service(interval_h=0, once=True)
    files = client.get("/api/files", params={"computer": "laptop"}).json()["items"]
    assert [f["name"] for f in files] == ["Rechnung_Laptop.txt"]
    assert agent.scan_due(0) is None  # Anforderung erledigt
    assert agent.scan_due(24) is None  # eigener Zeitplan: gerade erst gelesen
    assert not target.exists()


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_service_install_render(system, tmp_path, monkeypatch, capsys):
    from app import service_install as si
    monkeypatch.setattr(si.platform, "system", lambda: system)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(si.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    calls = []
    monkeypatch.setattr(si.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    si.main(["agent", "--server", "http://buero:8800", "--computer", "laptop", "--key", "GEHEIM", "--target", str(tmp_path / "ziel")])
    out = capsys.readouterr().out
    conf = si.conf_dir() / "agent.json"
    data = json.loads(conf.read_text(encoding="utf-8"))
    assert data["key"] == "GEHEIM" and data["interval_hours"] == 24
    unit = si.target_file("agent").read_text(encoding="utf-16" if system == "Windows" else "utf-8")
    assert "GEHEIM" not in unit and "service" in unit and "app.agent_client" in unit
    marker = {"Windows": "LogonTrigger", "Darwin": "RunAtLoad", "Linux": "Restart=on-failure"}[system]
    assert marker in unit
    assert calls and "agent.json" in out
    if system != "Windows":
        assert (conf.stat().st_mode & 0o777) == 0o600
    calls.clear()
    si.main(["entfernen", "agent"])
    assert calls and not si.target_file("agent").exists()
