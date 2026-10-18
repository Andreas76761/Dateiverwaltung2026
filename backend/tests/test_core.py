"""Tests der Kernzusagen: nichts löschen, nichts überschreiben, nur in den Zielordner schreiben."""
import os
import sys
import time
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    src = tmp_path / "pc" / "Dokumente"
    src.mkdir(parents=True)
    (src / "Steuerbescheid_2023.txt").write_text("Finanzamt Steuerbescheid Einkommensteuer 2023 Betrag 1.200,00 EUR", encoding="utf-8")
    (src / "Kopie").mkdir()
    (src / "Kopie" / "Steuerbescheid_2023.txt").write_text("Finanzamt Steuerbescheid Einkommensteuer 2023 Betrag 1.200,00 EUR", encoding="utf-8")
    (src / "prompt.md").write_text("System prompt: Du bist ein KI-Agent mit RAG und embeddings", encoding="utf-8")
    target = tmp_path / "cloud" / "Ziel"
    cfg = {
        "server": {"data_dir": str(tmp_path / "data")},
        "target": {"root": str(target)},
        "analysis": {"ocr": False, "thumbnails": False},
        "computers": [{"id": "pc", "name": "PC", "volumes": [{"id": "pc-c", "name": "C", "path": str(tmp_path / "pc")}]}],
    }
    cfg_file = tmp_path / "fdv.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(cfg_file))
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        yield client, src, target


def wait(client, job_id):
    for _ in range(100):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "läuft":
            return j
        time.sleep(0.1)
    raise TimeoutError


def snapshot(root: Path):
    return {p: (p.stat().st_size, p.stat().st_mtime) for p in root.rglob("*")}


def test_full_pipeline_is_read_only(env):
    client, src, target = env
    before = snapshot(src)

    j = wait(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    assert j["stats"]["dateien"] == 3
    assert j["stats"]["duplikatgruppen"] == 1

    wait(client, client.post("/api/pipeline/analyze", json={}).json()["job_id"])
    files = client.get("/api/files").json()["items"]
    by_name = {f["name"]: f for f in files if f["is_primary"]}
    assert by_name["Steuerbescheid_2023.txt"]["category"] == "Steuern"
    assert by_name["Steuerbescheid_2023.txt"]["group_name"] == "Privat"
    assert by_name["prompt.md"]["group_name"] == "GenAI"
    assert "Steuer" in by_name["Steuerbescheid_2023.txt"]["labels"]

    wait(client, client.post("/api/pipeline/propose").json()["job_id"])
    assert not target.exists(), "Vorschlag darf nichts physisch anlegen"

    # Ohne Freigabe keine Kopie
    assert client.post("/api/pipeline/copy", json={}).status_code == 400

    client.post("/api/review", json={"action": "freigeben", "folder": ""})
    j = wait(client, client.post("/api/pipeline/copy", json={}).json()["job_id"])
    assert j["stats"]["kopiert"] == 2  # Duplikat wird nicht doppelt kopiert
    copied = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert "01_Privat/Steuern/Bescheide/2023/Steuerbescheid_2023.txt" in copied

    # Zweiter Lauf: nichts überschreiben, identische Dateien überspringen
    j = wait(client, client.post("/api/pipeline/copy", json={}).json()["job_id"])
    assert j["stats"]["kopiert"] == 0 and j["stats"]["übersprungen"] == 2

    assert snapshot(src) == before, "Quelldateien wurden verändert!"


def test_delete_is_blocked(env):
    client, src, _ = env
    assert client.delete("/api/files/1").status_code == 405
    assert client.delete("/api/anything").status_code == 405


def test_safe_copy_never_overwrites_and_blocks_traversal(env, tmp_path):
    from app.safety import SafetyError, safe_copy
    _, src, target = env
    f = src / "prompt.md"
    r1 = safe_copy(str(f), "a/prompt.md")
    assert r1["status"] == "kopiert"
    (target / "a" / "prompt.md").write_text("anderer Inhalt")  # Konflikt im Ziel
    r2 = safe_copy(str(f), "a/prompt.md")
    assert r2["status"] == "kopiert" and r2["dst"].endswith("prompt (2).md")
    assert (target / "a" / "prompt.md").read_text() == "anderer Inhalt"
    r3 = safe_copy(str(f), "../../ausbruch/prompt.md")  # '..' wird entfernt
    assert Path(r3["dst"]).resolve().is_relative_to(target.resolve()) or r3["status"] == "übersprungen"
    with pytest.raises(SafetyError):
        safe_copy(str(target / "a" / "prompt.md"), "b/x.md")  # Quelle im Ziel


def test_windows_safe_target_paths():
    from app.safety import sanitize_rel
    assert sanitize_rel("02_Beruf/CON/aux.txt") == "02_Beruf/_CON/_aux.txt"       # reservierte Windows-Namen
    assert sanitize_rel("a/ende. /datei.pdf ") == "a/ende/datei.pdf"            # Punkt/Leerzeichen am Ende
    assert sanitize_rel("Kunde: Müller?/R*.pdf") == "Kunde_ Müller_/R_.pdf"     # verbotene Zeichen
    assert sanitize_rel("../../etc/passwd") == "etc/passwd"                      # kein Ausbruch aus dem Ziel


def test_file_limit_does_not_mark_missing(env, monkeypatch):
    client, src, _ = env
    wait(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    from app.config import get_settings
    get_settings().max_files = 1                     # Probelauf-Limit: nur 1 Datei lesen
    j = wait(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    assert j["stats"]["limit_erreicht"] and j["stats"]["nicht_mehr_gefunden"] == 0
    assert client.get("/api/files").json()["total"] == 3     # nichts fälschlich als "fehlend" markiert
