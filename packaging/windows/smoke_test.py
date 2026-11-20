"""Prüfung des INSTALLIERTEN Pakets auf einem frischen Windows (GitHub Actions) – mit dem mitgelieferten Python:

    "%LOCALAPPDATA%\\Programs\\Future Dateiverwaltung\\python\\python.exe" smoke_test.py <Installationsordner> <Testordner>

Startet über den Starter (wie das Startmenü), richtet einen Testordner ein, liest ein, analysiert
(inkl. Miniaturen und Texterkennung), erstellt den Vorschlag, beendet geordnet – und prüft, dass im Quellordner
nichts verändert wurde.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

INSTALL = Path(sys.argv[1])
SRC = Path(sys.argv[2])
BASE = "http://localhost:8800"
PY = INSTALL / "python" / "python.exe"
STARTER = INSTALL / "starter.py"


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-FDV-Request": "1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wait_job(job_id: int) -> dict:
    for _ in range(600):
        j = call("GET", f"/api/jobs/{job_id}")
        if j["status"] != "läuft":
            return j
        time.sleep(0.5)
    raise TimeoutError(job_id)


def starter(*args: str) -> str:
    r = subprocess.run([str(PY), str(STARTER), *args], capture_output=True, text=True, timeout=180)
    print(f"starter {' '.join(args)} → {r.returncode} {r.stdout.strip()} {r.stderr.strip()[-500:]}")
    assert r.returncode == 0, r
    return r.stdout


def make_files() -> dict[str, str]:
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont

    (SRC / "Steuern").mkdir(parents=True, exist_ok=True)
    (SRC / "oneSCM").mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page().insert_text((60, 80), f"Steuerbescheid 2025 Finanzamt Seite {i + 1}", fontsize=14)
    doc.save(SRC / "Steuern" / "Steuerbescheid_2025.pdf")
    img = Image.new("RGB", (1400, 500), "white")
    try:
        font = ImageFont.truetype("arial.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((40, 180), "Rechnung Nr. 4711 Betrag 120 EUR", fill="black", font=font)
    img.save(SRC / "Scan_Rechnung.png")
    (SRC / "oneSCM" / "Protokoll_Jour_Fixe.txt").write_text("oneSCM Jour fixe Protokoll Entscheidungen", encoding="utf-8")
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in SRC.rglob("*") if p.is_file()}


def main() -> None:
    before = make_files()
    starter("--hintergrund")
    st = json.loads(starter("--status"))
    assert st["running"], st
    assert call("GET", "/api/health")["ok"]
    setup = call("GET", "/api/setup")
    assert setup["configured"] is False and not setup["demo"], setup  # frische Installation: Willkommen + Assistent
    settings = call("GET", "/api/settings")
    print("Texterkennung:", settings["ocr_available"])

    r = call("POST", "/api/setup/apply", {"computers": [{"name": "Testrechner", "mode": "local", "volumes": [{"path": str(SRC)}]}],
                                          "target_root": str(SRC.parent / "Ziel")})
    assert r["ok"], r
    j = wait_job(call("POST", "/api/pipeline/scan", {})["job_id"])
    assert j["status"] == "fertig", j
    j = wait_job(call("POST", "/api/pipeline/analyze", {"confirmed": True})["job_id"])
    assert j["status"] == "fertig", j
    files = {f["name"]: f for f in call("GET", "/api/files?limit=50")["items"]}
    print({n: (f["category"], f.get("thumb_count")) for n, f in files.items()})
    assert files["Steuerbescheid_2025.pdf"]["category"] == "Steuern"
    assert files["Protokoll_Jour_Fixe.txt"]["category"].startswith("oneSCM")
    detail = call("GET", f"/api/files/{files['Steuerbescheid_2025.pdf']['id']}")
    assert len(detail.get("thumbnails") or []) >= 1, detail.keys()  # Miniaturen (PyMuPDF) funktionieren
    if settings["ocr_available"]:
        scan = call("GET", f"/api/files/{files['Scan_Rechnung.png']['id']}")
        text = json.dumps(scan, ensure_ascii=False)
        assert "4711" in text, "Texterkennung hat die Rechnungsnummer nicht gefunden"
        print("Texterkennung ok")
    call("POST", "/api/pipeline/propose", {})

    starter("--beenden", "--still")
    assert not json.loads(starter("--status"))["running"]
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in SRC.rglob("*") if p.is_file()}
    assert before == after, "Quellordner wurde verändert!"
    assert not (SRC.parent / "Ziel").exists(), "Ohne Freigabe darf nichts kopiert werden"
    print("Installiertes Paket: alles in Ordnung")


if __name__ == "__main__":
    main()
