"""Einrichtungs-Assistent und Datensicherung."""
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    demo = tmp_path / "demo" / "pc"
    demo.mkdir(parents=True)
    (demo / "Demo.txt").write_text("Demo-Datei Rechnung", encoding="utf-8")
    real = tmp_path / "Echt" / "Dokumente"
    real.mkdir(parents=True)
    (real / "Steuerbescheid_2024.txt").write_text("Finanzamt Steuerbescheid Einkommensteuer 2024", encoding="utf-8")
    (real / "Unter").mkdir()
    (real / "Unter" / "Notiz.md").write_text("Notiz", encoding="utf-8")
    cfg = {"server": {"data_dir": str(tmp_path / "data")}, "target": {"root": str(tmp_path / "cloud" / "Ziel")},
           "llm": {"provider": "rules"}, "analysis": {"ocr": False, "thumbnails": False},
           "computers": [{"id": "demo-pc", "name": "Demo-PC", "volumes": [{"id": "demo-c", "name": "C", "path": str(demo)}]}]}
    (tmp_path / "cloud").mkdir()
    conf = tmp_path / "config" / "fdv.yaml"
    conf.parent.mkdir()
    conf.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(conf))
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as client:
        yield client, tmp_path, real, conf


def wait(client, job_id):
    for _ in range(200):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "läuft":
            return j
        time.sleep(0.1)
    raise TimeoutError


def test_wizard(env):
    client, tmp, real, conf = env
    st = client.get("/api/setup").json()
    assert st["demo"] and st["detected"]["computer"]["name"] and st["detected"]["server_url"].startswith("http")
    b = client.post("/api/setup/browse", json={"path": str(real)}).json()
    assert [d["name"] for d in b["dirs"]] == ["Unter"] and b["parent"]
    chk = client.post("/api/setup/check", json={"paths": [str(real), str(tmp / "fehlt")]}).json()
    assert chk[0]["files"] == 2 and chk[0]["readable"] and chk[1]["warnings"] == ["Ordner nicht gefunden"]

    bad = client.post("/api/setup/apply", json={"computers": [{"name": "Büro-PC", "volumes": [{"path": str(tmp / "fehlt")}]}],
                                                "target_root": str(tmp / "cloud" / "Ziel")}).json()
    assert not bad["ok"] and "Ordner nicht gefunden" in bad["errors"][0]
    assert yaml.safe_load(conf.read_text())["computers"][0]["id"] == "demo-pc"  # bei Fehlern nichts geschrieben

    body = {"computers": [
        {"name": "Büro-PC", "os": "Windows 11", "mode": "local", "volumes": [{"name": "Dokumente", "path": str(real)}]},
        {"name": "Laptop", "mode": "agent", "volumes": [{"name": "C:", "path": "C:/Users/andreas"}]}],
        "target_root": str(tmp / "cloud" / "Ziel")}
    r = client.post("/api/setup/apply", json=body).json()
    assert r["ok"] and r["new_database"] and r["backup"]
    assert Path(r["backup"]).is_file()  # vorherige Konfiguration bleibt erhalten
    written = yaml.safe_load(conf.read_text())
    assert [c["id"] for c in written["computers"]] == ["buero-pc", "laptop"]
    assert written["computers"][1]["volumes"][0]["path"] == "C:/Users/andreas"  # Agent-Pfad wird nicht lokal geprüft
    assert "Program Files" in written["scan"]["exclude_dirs"] and written["llm"]["provider"] == "rules"
    assert written["server"]["data_dir"] == str(tmp / "daten")
    assert (tmp / "data" / "fdv.sqlite3").exists()  # Demo-Datenbank bleibt

    comps = {c["id"] for c in client.get("/api/sources").json()["computers"]}
    assert comps == {"buero-pc", "laptop"}  # neue, eigene Datenbank ohne Demo-Einträge
    j = wait(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    assert j["stats"]["dateien"] == 2
    assert (real / "Steuerbescheid_2024.txt").read_text(encoding="utf-8").startswith("Finanzamt")


def test_backup_and_restore(env):
    client, tmp, real, conf = env
    wait(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    fid = client.get("/api/files").json()["items"][0]["id"]
    client.post("/api/review", json={"action": "freigeben", "file_ids": [fid]})

    m = client.post("/api/backup").json()
    assert m["geprüft"] and m["inhalt"]["freigegeben"] == 1 and Path(m["datei"]).is_file()
    assert Path(m["cloud_datei"]).parent == tmp / "cloud" / "Ziel" / "_Sicherung"  # Kopie im Zielordner
    with zipfile.ZipFile(m["datei"]) as z:
        assert {"fdv.sqlite3", "manifest.json", "konfiguration.yaml"} <= set(z.namelist())
        assert not any("token" in n for n in z.namelist())

    client.post("/api/review", json={"action": "ablehnen", "file_ids": [fid]})
    assert client.get(f"/api/files/{fid}").json()["review_status"] == "abgelehnt"
    r = client.post("/api/backup/restore", json={"name": Path(m["datei"]).name}).json()
    assert r["ok"] and Path(r["vorher_gesichert"]).is_file()
    assert client.get(f"/api/files/{fid}").json()["review_status"] == "freigegeben"  # Stand der Sicherung
    assert client.post("/api/backup/restore", json={"name": "../../fdv.yaml"}).status_code == 404
    assert client.get(f"/api/backup/download/{Path(m['datei']).name}").content[:2] == b"PK"

    # Aufräumen: nur automatische Sicherungen im eigenen Ordner, die Kopien im Zielordner bleiben alle
    from app import backup
    client.post("/api/backup/settings", json={"keep": 2})
    for _ in range(4):
        backup.create("automatisch", to_target=False)
        time.sleep(1.05)
    items = client.get("/api/backup").json()["items"]
    local = [i for i in items if i["ort"] == "lokal"]
    assert sum(1 for i in local if i["grund"] == "automatisch") == 2
    assert any(i["grund"] == "manuell" for i in local) and any(i["ort"] == "Zielordner (Cloud)" for i in items)
    assert client.post("/api/backup/settings", json={"to_target": "stündlich"}).status_code == 400
    assert json.loads((tmp / "data" / "overrides.json").read_text())["backup"]["keep"] == 2
