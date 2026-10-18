"""Ähnliche Dateien: Fotos, Versionen, gleicher Inhalt in anderem Format – ohne etwas zu verändern."""
import random
import sys
import time
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.skills import similarity as sim  # noqa: E402

TEXT = ("Angebot für die Muster AG über die Lieferung von Schwerlastregalen für das Lager Süd. Position eins umfasst "
        "achtundvierzig Regalfelder mit Anfahrschutz. Position zwei umfasst die Montage vor Ort durch zwei Monteure an drei "
        "Arbeitstagen inklusive Abnahmeprotokoll. Position drei umfasst die Entsorgung des Verpackungsmaterials und die "
        "Einweisung der Mitarbeiter. Zahlungsziel dreißig Tage netto, Lieferzeit sechs Wochen nach Auftragseingang.")


def picture(p: Path, seed: int, size=(800, 600)):
    rnd = random.Random(seed)
    im = Image.new("RGB", size, tuple(rnd.randint(0, 255) for _ in range(3)))
    dr = ImageDraw.Draw(im)
    for _ in range(12):
        x, y, r = rnd.randint(0, size[0]), rnd.randint(0, size[1]), rnd.randint(30, 160)
        dr.ellipse([x - r, y - r, x + r, y + r], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p, quality=90)
    return im


def test_name_key_and_version_rank():
    assert sim.name_key("Angebot_v2.docx")[0] == sim.name_key("Angebot_final.pdf")[0] == sim.name_key("Angebot (1).docx")[0] == "angebot"
    assert sim.name_key("Rechnung_2023_045.pdf")[0] != sim.name_key("Rechnung_2023_046.pdf")[0]  # verschiedene Rechnungen
    assert sim.name_key("scan.pdf")[0] is None  # Allerweltsname
    ranks = [sim.version_rank(sim.name_key(n)[1]) for n in ("Angebot_Entwurf.docx", "Angebot.docx", "Angebot_v2.docx", "Angebot_v10.docx", "Angebot_final.pdf")]
    assert ranks == sorted(ranks) and len(set(ranks)) == 5


def test_fingerprints():
    a, b = sim.minhash(TEXT), sim.minhash(TEXT.replace("sechs Wochen", "acht Wochen") + " Zusätzlich jährliche Regalprüfung.")
    c = sim.minhash("Urlaub in Portugal mit Strand, Sonne und Meer. " * 3 + "Hotel in Lissabon, Ausflug nach Porto, Essen am Hafen, Fado am Abend.")
    assert sim.jaccard(a, a) == 1.0
    assert sim.jaccard(a, b) > 0.6 > sim.jaccard(a, c)
    assert sim.minhash("zu kurz") is None
    sim_np, sim.np = sim.np, None  # reine Python-Variante liefert dieselben Werte
    try:
        assert sim.minhash(TEXT) == a
    finally:
        sim.np = sim_np


def test_phash_robust(tmp_path):
    im = picture(tmp_path / "a.jpg", 1)
    im.resize((400, 300)).point(lambda v: min(255, int(v * 1.1))).save(tmp_path / "a_klein.png")
    picture(tmp_path / "b.jpg", 2)
    Image.new("RGB", (300, 300), (250, 250, 250)).save(tmp_path / "leer.png")
    h1, h2, h3 = (sim.phash(str(tmp_path / n)) for n in ("a.jpg", "a_klein.png", "b.jpg"))
    assert sim.hamming(h1, h2) <= 6
    assert sim.hamming(h1, h3) > 12
    assert sim.phash(str(tmp_path / "leer.png")) is None  # einfarbig → kein Vergleich


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "pc"
    d = root / "Dokumente"
    d.mkdir(parents=True)
    (d / "Angebot_Regale_v1.txt").write_text(TEXT, encoding="utf-8")
    (d / "Angebot_Regale_v2.txt").write_text(TEXT.replace("sechs Wochen", "acht Wochen") + " Rabatt drei Prozent.", encoding="utf-8")
    (d / "Export").mkdir()
    (d / "Export" / "Regalangebot_Muster.md").write_text(TEXT + " Rabatt drei Prozent.", encoding="utf-8")  # anderer Name, gleicher Inhalt
    (d / "Notizen_Projekt.txt").write_text("Einkaufsliste Milch Brot Eier Käse Tomaten Gurken Paprika Zwiebeln Knoblauch "
                                          "Nudeln Reis Mehl Zucker Salz Pfeffer Öl Essig Butter Joghurt Äpfel Bananen Orangen Kaffee Tee", encoding="utf-8")
    (root / "Alt").mkdir()
    (root / "Alt" / "Notizen_Projekt.txt").write_text("Völlig anderer Inhalt über Steuererklärung Belege Werbungskosten Fahrtkosten "
                                                      "Arbeitszimmer Spenden Versicherungen Kinderbetreuung Handwerkerleistungen Zinsen Dividenden", encoding="utf-8")
    im = picture(root / "Bilder" / "IMG_1001.jpg", 5)
    im.resize((400, 300)).save(root / "Bilder" / "Strand_klein.png")
    picture(root / "Bilder" / "IMG_1002.jpg", 6)
    cfg = {
        "server": {"data_dir": str(tmp_path / "data")},
        "target": {"root": str(tmp_path / "cloud" / "Ziel")},
        "analysis": {"ocr": False},
        "computers": [{"id": "pc", "name": "PC", "volumes": [{"id": "pc-c", "name": "C", "path": str(root)}]}],
    }
    (tmp_path / "fdv.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(tmp_path / "fdv.yaml"))
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as client:
        yield client, root, tmp_path / "cloud" / "Ziel"


def wait(client, job_id):
    for _ in range(300):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "läuft":
            return j
        time.sleep(0.1)
    raise TimeoutError


def test_similar_files_pipeline(env):
    client, root, target = env
    before = {p: (p.stat().st_size, p.stat().st_mtime) for p in root.rglob("*")}
    wait(client, client.post("/api/pipeline/scan", json={}).json()["job_id"])
    j = wait(client, client.post("/api/pipeline/analyze", json={}).json()["job_id"])
    assert j["stats"]["ähnlich"]["ähnlich_gruppen"] == 2

    groups = client.get("/api/similar").json()["groups"]
    by_kind = {g["kind"]: g for g in groups}
    names = {k: {m["name"]: m["sim_best"] for m in g["members"]} for k, g in by_kind.items()}
    # v1/v2 per Name, das Markdown-Export per Inhalt in dieselbe Gruppe
    # sim_best 2 = gleicher Inhalt wie die neueste Version, nur anderes Format
    assert names["Versionen"] == {"Angebot_Regale_v2.txt": 1, "Angebot_Regale_v1.txt": 0, "Regalangebot_Muster.md": 2}
    assert set(names["Fotos"]) == {"IMG_1001.jpg", "Strand_klein.png"}  # anderes Motiv IMG_1002 nicht
    assert names["Fotos"]["IMG_1001.jpg"] == 1  # größte Auflösung
    # gleicher Name, aber völlig anderer Inhalt → keine Version
    assert not any("Notizen_Projekt.txt" in n for n in names.values())

    files = {f["name"]: f for f in client.get("/api/files", params={"limit": 100}).json()["items"]}
    v1, v2 = files["Angebot_Regale_v1.txt"], files["Angebot_Regale_v2.txt"]
    assert "Ältere Version" in v1["labels"] and "Neueste Version" in v2["labels"]
    assert "Auch als TXT" in files["Regalangebot_Muster.md"]["labels"]
    assert v1["importance"] < v2["importance"]
    older = client.get("/api/files", params={"similar": "ältere"}).json()["items"]
    assert {f["name"] for f in older} == {"Angebot_Regale_v1.txt"}
    detail = client.get(f"/api/files/{v1['id']}").json()
    assert {s["name"] for s in detail["similar"]} == {"Angebot_Regale_v2.txt", "Regalangebot_Muster.md"}
    assert any(s["pair_kind"] == "version" for s in detail["similar"])

    # Kopieren: ältere Versionen auf Wunsch auslassen
    client.post("/api/review", json={"action": "freigeben", "folder": ""})
    assert client.get("/api/copy/preview").json()["older_versions"] == 1
    j = wait(client, client.post("/api/pipeline/copy", json={"skip_older_versions": True}).json()["job_id"])
    assert j["stats"]["ältere_versionen_ausgelassen"] == 1
    copied = {p.name for p in target.rglob("*") if p.is_file()}
    assert "Angebot_Regale_v2.txt" in copied and "Angebot_Regale_v1.txt" not in copied

    # Erneut suchen ist stabil; Quelldateien unverändert
    j = wait(client, client.post("/api/pipeline/similar", json={"force": True}).json()["job_id"])
    assert j["stats"]["ähnlich_gruppen"] == 2 and j["stats"]["fingerabdrücke"] == 8
    after = {p: (p.stat().st_size, p.stat().st_mtime) for p in root.rglob("*")}
    assert before == after
