"""Punkt 14 – Offline-Einordnung: Trefferquote auf Prüf- und Kontrollsatz, Sicherheit, Ordner-Kontext, Lernen aus Korrekturen."""
import importlib.util
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("regeln_bewerten", ROOT.parent / "scripts" / "regeln_bewerten.py")
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)


def run(cases: str):
    rb.CASES = ROOT / "tests" / "data" / cases
    return rb.evaluate()


def test_pruefsatz():
    acc, rows = run("einordnung.yaml")
    assert acc >= 0.95, [r for r in rows if not r["ok"]]


def test_kontrollsatz_und_sicherheit():
    """Kontrollsatz wurde beim Abstimmen nicht verwendet – misst die Übertragbarkeit auf unbekannte Dateien."""
    acc, rows = run("einordnung_kontrolle.yaml")
    assert acc >= 0.85
    ok = [r["conf"] for r in rows if r["ok"]]
    bad = [r["conf"] for r in rows if not r["ok"]]
    # Falsche Einordnungen sollen unsicher sein → im Modus „unklare“ gehen sie an das LLM
    assert sum(bad) / len(bad) < sum(ok) / len(ok) - 0.1


@pytest.fixture()
def client(tmp_path, monkeypatch):
    root = tmp_path / "pc"
    steuer = root / "Dokumente" / "Ablage_2023"
    steuer.mkdir(parents=True)
    for i, t in enumerate(["Finanzamt Steuerbescheid Einkommensteuer 2023 festgesetzt", "Lohnsteuerbescheinigung 2023 Finanzamt",
                           "Einkommensteuererklärung 2023 Anlage N Finanzamt Steuer-ID"]):
        (steuer / f"Steuer_Dokument_{i}.txt").write_text(t, encoding="utf-8")
    (steuer / "scan0001.pdf").write_bytes(b"%PDF-1.4 kaputt")  # kein lesbarer Inhalt
    misc = root / "Dokumente" / "Diverses"
    misc.mkdir()
    for n in ("Unterlagen_A.txt", "Unterlagen_B.txt", "Unterlagen_C.txt"):
        (misc / n).write_text("Notiz", encoding="utf-8")
    cfg = {"server": {"data_dir": str(tmp_path / "data")}, "target": {"root": str(tmp_path / "ziel")},
           "analysis": {"ocr": False, "thumbnails": False},
           "computers": [{"id": "pc", "name": "PC", "volumes": [{"id": "pc-c", "name": "C", "path": str(root)}]}]}
    (tmp_path / "fdv.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(tmp_path / "fdv.yaml"))
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def wait(c, job_id):
    for _ in range(200):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "läuft":
            return j
        time.sleep(0.1)
    raise TimeoutError


def test_ordner_kontext_und_korrektur(client):
    c = client
    wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
    j = wait(c, c.post("/api/pipeline/analyze", json={}).json()["job_id"])
    files = {f["name"]: f for f in c.get("/api/files", params={"limit": 50}).json()["items"]}
    scan = c.get(f"/api/files/{files['scan0001.pdf']['id']}").json()
    assert scan["category"] == "Steuern" and scan["llm_provider"] == "regeln (Ordner)"  # Nachbarn sind Steuerunterlagen
    assert j["stats"]["ordner_kontext"] >= 1

    # Aus der Korrektur lernen: eine Datei im Ordner manuell einordnen → unsichere Nachbarn folgen
    a = files["Unterlagen_A.txt"]
    assert a["category"] != "Versicherungen"
    c.post(f"/api/files/{a['id']}/update", json={"category": "Versicherungen"})
    after = {f["name"]: f for f in c.get("/api/files", params={"limit": 50}).json()["items"]}
    assert after["Unterlagen_B.txt"]["category"] == after["Unterlagen_C.txt"]["category"] == "Versicherungen"

    # Manuelle Korrektur übersteht eine erneute Analyse
    wait(c, c.post("/api/pipeline/analyze", json={"force": True}).json()["job_id"])
    assert c.get(f"/api/files/{a['id']}").json()["category"] == "Versicherungen"


def test_kapitel_onescm():
    """oneSCM ist ein eigenes Kapitel unter Beruf: eigener Zielordner, greift nur bei erkennbarem Bezug."""
    from app.categories import BY_ID, CATEGORIES, CHAPTERS
    from app.llm.rules_provider import RulesProvider
    from app.skills import pathsuggest

    onescm = [c for c in CATEGORIES if c.chapter == "oneSCM"]
    assert len(onescm) == 10 and all(c.group == "Beruf" for c in onescm)
    assert CHAPTERS["oneSCM"]["default"] in {c.id for c in onescm}
    assert pathsuggest.suggest(BY_ID["o_test"], "UAT.xlsx", 2026, 3, "Tabelle").startswith("02_Beruf/oneSCM/Test_Rollout/")

    rp = RulesProvider()
    def cat(name, path, text=""):
        return rp.analyze({"name": name, "path": f"{path}/{name}", "ext": Path(name).suffix, "file_type": "Dokument"}, text)["category_id"]
    assert cat("Testfälle.xlsx", "D:/Arbeit/oneSCM") == "o_test"
    assert cat("Notiz.txt", "D:/Arbeit/oneSCM") == "o_programm"  # ohne genaueres Thema: Auffangkategorie im Kapitel
    assert cat("Testfälle.xlsx", "D:/Arbeit/Projekt_X").startswith("b_")  # ohne oneSCM: allgemeine Kategorien
    # Randnotiz im Text reicht nicht
    assert not cat("Budget.xlsx", "D:/Arbeit", "Budget Kostenstelle " + "x " * 300 + "Lizenz oneSCM").startswith("o_")
    # Lebenslauf bleibt Bewerbungsunterlage
    assert cat("Lebenslauf.pdf", "C:/Users/a/Documents", "Erfahrung: oneSCM-Einführung, Rollout, Key User") == "b_personal"
