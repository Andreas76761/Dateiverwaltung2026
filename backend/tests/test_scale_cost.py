"""Tests: Cloud-Platzhalter (nur online), Miniaturen-Strategie/Cache-Obergrenze, Claude-Kosten (Schätzung,
Bestätigung, nur unklare Dateien, Kostenlimit, Batch-Modus). Claude wird durch einen Fake-Client ersetzt."""
import builtins
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_env(tmp_path, monkeypatch, llm=None, analysis=None):
    src = tmp_path / "pc"
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "Steuerbescheid_2023.txt").write_text("Finanzamt Steuerbescheid Einkommensteuer 2023", encoding="utf-8")
    (src / "docs" / "Notiz.txt").write_text("irgendwas ohne klare Zuordnung", encoding="utf-8")
    (src / "docs" / "Vertrag_ONLINE.txt").write_text("Mietvertrag Kündigung Vermieter", encoding="utf-8")
    (src / "docs" / "Angebot.pdf.nextcloud").write_bytes(b"")  # Nextcloud-Platzhalter
    import pymupdf
    for name in ("Wichtig_Vertrag_Steuer.pdf", "Flyer.pdf"):
        d = pymupdf.open()
        for i in range(4):
            d.new_page().insert_text((50, 50), f"{name} Seite {i + 1} " + ("Vertrag Steuer Frist Unterschrift" if "Wichtig" in name else ""))
        d.save(src / "docs" / name)
    cfg = {
        "server": {"data_dir": str(tmp_path / "data")},
        "target": {"root": str(tmp_path / "cloud" / "Ziel")},
        "llm": {"provider": "rules", **(llm or {})},
        "analysis": {"ocr": False, **(analysis or {})},
        "computers": [{"id": "pc", "name": "PC", "volumes": [{"id": "pc-c", "name": "C", "path": str(src)}]}],
    }
    f = tmp_path / "fdv.yaml"
    f.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(f))
    monkeypatch.delenv("FDV_DATA_DIR", raising=False)
    from app.config import get_settings
    get_settings.cache_clear()
    # Windows-Attribut "Nur online" für Dateien mit ONLINE im Namen simulieren
    from app.connectors import cloudfiles, local
    orig = cloudfiles.is_online_only
    monkeypatch.setattr(local, "is_online_only", lambda st, name="", sparse=False: "ONLINE" in name or orig(st, name, sparse))
    return src


def wait(client, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "läuft":
            return j
        time.sleep(0.1)
    raise TimeoutError


@pytest.fixture()
def client_factory(tmp_path, monkeypatch):
    clients = []

    def make(**kw):
        make_env(tmp_path, monkeypatch, **kw)
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c
    yield make
    for c in clients:
        c.__exit__(None, None, None)


# ------------------------------------------------------------------ Punkt 2: nur online

def test_online_only_never_read(client_factory, monkeypatch):
    real_open = builtins.open

    def guarded_open(file, *a, **kw):
        if isinstance(file, (str, Path)) and ("ONLINE" in str(file) or str(file).endswith(".nextcloud")):
            raise AssertionError(f"Cloud-Platzhalter wurde gelesen: {file}")
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", guarded_open)
    c = client_factory()
    j = wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
    assert j["stats"]["nur_online"] == 2
    j = wait(c, c.post("/api/pipeline/analyze", json={}).json()["job_id"])
    assert j["status"] == "fertig", j
    files = {f["name"]: f for f in c.get("/api/files").json()["items"]}
    assert "Angebot.pdf" in files, "Nextcloud-Platzhalter wird unter seinem echten Namen geführt"
    for n in ("Vertrag_ONLINE.txt", "Angebot.pdf"):
        assert files[n]["online_only"] == 1 and "Nur online" in files[n]["labels"] and files[n]["thumbs"] == 0
    assert c.get("/api/files?online=ja").json()["total"] == 2
    assert c.post(f"/api/files/{files['Angebot.pdf']['id']}/thumbs/ensure").status_code == 409
    c.post("/api/review", json={"action": "freigeben", "folder": ""})
    j = wait(c, c.post("/api/pipeline/copy", json={}).json()["job_id"])
    assert j["stats"]["nur_online"] == 2 and j["stats"]["kopiert"] == 4


def test_cloudfile_detection():
    from app.connectors.cloudfiles import is_online_only, real_name
    st = lambda **kw: SimpleNamespace(st_size=100, st_blocks=8, **kw)
    assert is_online_only(st(st_file_attributes=0x00400000))           # OneDrive „Nur online“
    assert is_online_only(st(st_file_attributes=0x00001000))           # OFFLINE
    assert not is_online_only(st(st_file_attributes=0x00000020))       # normales Archiv-Attribut
    assert is_online_only(st(st_flags=0x40000000))                      # macOS dataless
    assert real_name(".Bericht.pdf.icloud") == ("Bericht.pdf", True)
    assert real_name("Bericht.pdf.nextcloud") == ("Bericht.pdf", True)
    assert real_name("Bericht.pdf") == ("Bericht.pdf", False)
    assert not is_online_only(SimpleNamespace(st_size=100, st_blocks=0))
    assert is_online_only(SimpleNamespace(st_size=100, st_blocks=0), sparse_heuristic=True)


# ------------------------------------------------------------------ Punkt 3: Miniaturen-Strategie

def test_smart_thumbnails_and_budget(client_factory):
    c = client_factory(analysis={"thumbnails_mode": "smart", "thumbs_all_pages_min_importance": 50})
    wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
    wait(c, c.post("/api/pipeline/analyze", json={}).json()["job_id"])
    files = {f["name"]: f for f in c.get("/api/files").json()["items"]}
    wichtig, flyer = files["Wichtig_Vertrag_Steuer.pdf"], files["Flyer.pdf"]
    assert wichtig["importance"] >= 50 and wichtig["thumbs"] == 4 and wichtig["thumbs_complete"] == 1
    assert flyer["importance"] < 50 and flyer["thumbs"] == 1 and flyer["thumbs_complete"] == 0
    r = c.post(f"/api/files/{flyer['id']}/thumbs/ensure").json()
    assert r == {"pages": 4, "total": 4, "complete": True}

    from app.config import get_settings
    from app.skills import thumbcache
    get_settings().analysis["thumbs_budget_gb"] = 1e-9          # Budget praktisch 0 → Folgeseiten entfernen
    thumbcache.enforce_budget()
    files = {f["name"]: f for f in c.get("/api/files").json()["items"]}
    assert files["Flyer.pdf"]["thumbs"] == 1 and files["Wichtig_Vertrag_Steuer.pdf"]["thumbs"] == 1  # Deckblätter bleiben
    assert files["Flyer.pdf"]["thumbs_complete"] == 0


def test_quick_hash_duplicates(tmp_path, monkeypatch):
    src = make_env(tmp_path, monkeypatch)
    big = bytes(range(256)) * 20000                      # ~5 MB
    (src / "a.bin").write_bytes(big)
    (src / "b.bin").write_bytes(big)
    (src / "c.bin").write_bytes(big[:-1] + b"x")          # gleiche Größe, anders am Ende
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        j = wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
        assert j["stats"]["duplikatgruppen"] == 1
        assert j["stats"]["prüfsummen_berechnet"] == 2     # c.bin wurde nach der Schnellprüfung nicht voll gehasht


# ------------------------------------------------------------------ Punkt 4: Claude-Kosten

class FakeAnthropic:
    def __init__(self, category="b_vertraege"):
        self.calls = 0
        self.category = category
        fake = self

        class Msgs:
            def create(self, **kw):
                fake.calls += 1
                return fake.message()

        class Batches:
            def __init__(self):
                self.reqs = []

            def create(self, requests):
                self.reqs = requests
                return SimpleNamespace(id="msgbatch_test")

            def retrieve(self, bid):
                return SimpleNamespace(processing_status="ended", request_counts=SimpleNamespace(
                    processing=0, succeeded=len(self.reqs), errored=0, canceled=0, expired=0))

            def results(self, bid):
                for r in self.reqs:
                    yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="succeeded", message=fake.message()))

            def cancel(self, bid):
                pass

        self.beta = SimpleNamespace(messages=Msgs())
        self.messages = SimpleNamespace(batches=Batches())

    def message(self):
        body = {"category_id": self.category, "labels": ["Vertrag", "Claude"], "summary": "Von Claude eingeordnet",
                "subfolder": "", "importance": 80, "confidence": 0.95}
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(body))], stop_reason="end_turn",
                               model="claude-opus-5-5", usage=SimpleNamespace(
                                   input_tokens=300, output_tokens=200, cache_read_input_tokens=1300, cache_creation_input_tokens=0))


@pytest.fixture()
def fake_claude(monkeypatch):
    fake = FakeAnthropic()
    from app.llm import anthropic_provider, batch
    monkeypatch.setattr(anthropic_provider, "client", lambda: fake)
    monkeypatch.setattr(batch, "client", lambda: fake)
    return fake


def test_estimate_confirmation_and_costs(client_factory, fake_claude):
    c = client_factory(llm={"provider": "anthropic", "mode": "alle", "max_cost_usd": 0})
    wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
    est = c.post("/api/llm/estimate", json={}).json()
    assert est["dateien"] == 6 and est["an_llm"] == 6 and est["kosten_usd"] >= 0
    assert set(est["alternativen_usd"]) == {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}
    r = c.post("/api/pipeline/analyze", json={})
    assert r.status_code == 409 and "estimate" in r.json()["detail"]        # ohne Bestätigung kein Start
    assert fake_claude.calls == 0
    j = wait(c, c.post("/api/pipeline/analyze", json={"confirmed": True}).json()["job_id"])
    assert fake_claude.calls == 6 and j["stats"]["llm"] == 6
    # 300 in × $4 + 1300 cache × $0.20 + 200 out × $20 je 1 Mio → 0,00546 $ je Aufruf
    assert j["stats"]["kosten_usd"] == pytest.approx(6 * 0.00546, rel=1e-3)
    assert c.get("/api/stats").json()["llm_kosten"]["aufrufe"] == 6


def test_only_unclear_files_and_cost_limit(client_factory, fake_claude):
    c = client_factory(llm={"provider": "anthropic", "hybrid_min_confidence": 0.6})
    wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
    est_all = c.post("/api/llm/estimate", json={"mode": "alle"}).json()
    est_unclear = c.post("/api/llm/estimate", json={"mode": "unklare"}).json()
    assert est_unclear["an_llm"] < est_all["an_llm"] and est_unclear["kosten_usd"] <= est_all["kosten_usd"]
    j = wait(c, c.post("/api/pipeline/analyze", json={"confirmed": True, "mode": "unklare"}).json()["job_id"])
    assert j["stats"]["nur_regeln"] >= 1 and j["stats"]["llm"] == fake_claude.calls < 6
    # Kostenlimit: nach dem ersten Aufruf ist das Limit erreicht → Rest offline
    calls_before = fake_claude.calls
    j = wait(c, c.post("/api/pipeline/analyze", json={"confirmed": True, "force": True, "mode": "alle",
                                                      "max_cost_usd": 0.001}).json()["job_id"])
    assert fake_claude.calls - calls_before <= 6 and j["stats"]["kostenlimit_erreicht"] and j["stats"]["kostenlimit"] >= 1


def test_batch_mode(client_factory, fake_claude):
    c = client_factory(llm={"provider": "anthropic"})
    wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
    j = wait(c, c.post("/api/pipeline/analyze", json={"confirmed": True, "batch": True}).json()["job_id"])
    assert j["status"] == "fertig" and j["stats"]["batches"] == 1 and j["stats"]["llm"] == 6
    assert fake_claude.calls == 0                                         # keine Einzelaufrufe
    assert j["stats"]["kosten_usd"] == pytest.approx(6 * 0.00546 / 2, rel=1e-3)  # 50 % Batch-Rabatt
    req = fake_claude.messages.batches.reqs[0]["params"]
    assert "fallbacks" not in req and req["output_config"]["format"]["type"] == "json_schema"
    files = c.get("/api/files").json()["items"]
    assert all(f["status"] == "analysiert" for f in files)
    from app import db
    assert db.query("SELECT status FROM llm_batches")[0]["status"] == "fertig"
    assert db.one("SELECT llm_provider FROM files WHERE online_only=0 LIMIT 1")["llm_provider"] == "anthropic (Batch)"
