"""Cloud-Schnittstellen (Microsoft Graph / Google Drive) gegen nachgebildete Server (httpx.MockTransport):
Anmeldung mit PKCE, Einlesen ohne Download, Duplikate lokal↔Cloud, Deckblatt, serverseitige Kopie,
und dass nie gelöscht, verschoben oder überschrieben wird."""
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STEUER = b"Finanzamt Steuerbescheid Einkommensteuer 2023 Betrag 1.200,00 EUR" * 20
SHA = hashlib.sha256(STEUER).hexdigest()


def png() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (300, 400), "navy").save(b, "PNG")
    return b.getvalue()


class FakeCloud:
    """Nachbau der benötigten Endpunkte von Microsoft Graph und Google Drive."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.copies: list[dict] = []
        # OneDrive: Ordner und Dateien
        self.od_folders = {"f1": ("Dokumente", "root"), "f2": ("Steuer", "f1"), "ft": ("Future-Dateiverwaltung", "root")}
        self.od_files = [
            {"id": "o1", "name": "Steuerbescheid_2023.pdf", "parent": "f2", "size": len(STEUER), "sha256": SHA.upper()},
            {"id": "o2", "name": "Projektplan_Phoenix.pptx", "parent": "f1", "size": 52000, "quick": "QX1"},
            {"id": "o3", "name": "alte_kopie.pdf", "parent": "ft", "size": 10, "quick": "QX9"},  # im Zielordner → ignorieren
        ]
        # Google Drive
        self.gd = [
            {"id": "g0", "name": "Arbeit", "mimeType": "application/vnd.google-apps.folder", "parents": ["groot"]},
            {"id": "g1", "name": "Angebot_Nordwind.pdf", "mimeType": "application/pdf", "parents": ["g0"], "size": "4000", "md5Checksum": "m1"},
            {"id": "g2", "name": "GenAI Strategie", "mimeType": "application/vnd.google-apps.presentation", "parents": ["g0"]},
            {"id": "g3", "name": "Fremd.pdf", "mimeType": "application/pdf", "parents": ["unbekannt"], "size": "5"},  # „für mich freigegeben“
        ]

    # ------------------------------------------------------------ Graph
    def od_path(self, fid):
        parts = []
        while fid != "root":
            name, fid = self.od_folders[fid]
            parts.append(name)
        return "/".join(reversed(parts))

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, f"{req.url.host}{req.url.path}"))
        assert req.method in ("GET", "POST"), f"verbotene Methode {req.method} wurde gesendet!"
        host, path, q = req.url.host, unquote(req.url.path), parse_qs(req.url.query.decode())
        body = json.loads(req.content) if req.content and req.headers.get("content-type", "").startswith("application/json") else {}
        if host in ("login.microsoftonline.com", "oauth2.googleapis.com"):
            form = parse_qs(req.content.decode())
            assert form["grant_type"][0] in ("authorization_code", "refresh_token")
            if form["grant_type"][0] == "authorization_code":
                assert form["code_verifier"][0], "PKCE fehlt"
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
        if host == "graph.microsoft.com":
            return self.graph(req.method, path.removeprefix("/v1.0"), q, body)
        if host in ("www.googleapis.com", "lh3.googleusercontent.com"):
            return self.drive(req.method, path, q, body, host)
        if host == "monitor.example":
            return httpx.Response(200, json={"status": "completed"})
        return httpx.Response(404)

    def graph(self, m, path, q, body):
        if path == "/me/drive/root/delta":
            items = [{"id": "root", "name": "root", "root": {}, "folder": {}}]
            items += [{"id": k, "name": n, "folder": {}, "parentReference": {"id": p}} for k, (n, p) in self.od_folders.items()]
            files = [{"id": f["id"], "name": f["name"], "size": f["size"], "parentReference": {"id": f["parent"]},
                      "file": {"hashes": {"sha256Hash": f.get("sha256"), "quickXorHash": f.get("quick")}},
                      "fileSystemInfo": {"lastModifiedDateTime": "2024-03-01T10:00:00Z", "createdDateTime": "2024-02-01T10:00:00Z"},
                      "webUrl": f"https://onedrive.live.com/{f['id']}"} for f in self.od_files if not f.get("copy")]
            files.append({"id": "gone", "name": "weg.txt", "deleted": {}})
            if "page" not in str(q):   # zwei Seiten wie bei echtem Graph-Paging
                return httpx.Response(200, json={"value": items, "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/drive/root/delta?page=2"})
            return httpx.Response(200, json={"value": files, "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/drive/root/delta?token=x"})
        if path.endswith("/thumbnails/0/large/content"):
            return httpx.Response(200, content=png())
        if path == "/me/drive/root":
            return httpx.Response(200, json={"id": "root"})
        if path == "/me/drive":
            return httpx.Response(200, json={"id": "drv"})
        if path.startswith("/me/drive/root:/"):
            want = path.removeprefix("/me/drive/root:/")
            for k in self.od_folders:
                if self.od_path(k) == want:
                    return httpx.Response(200, json={"id": k})
            return httpx.Response(404, json={"error": {"code": "itemNotFound"}})
        if path.endswith("/children") and m == "POST":
            assert body["@microsoft.graph.conflictBehavior"] == "fail" and "folder" in body
            fid = f"new{len(self.od_folders)}"
            self.od_folders[fid] = (body["name"], path.split("/")[4])
            return httpx.Response(201, json={"id": fid})
        if path.endswith("/children"):
            folder = path.split("/")[4]
            kids = [{"name": f["name"], "file": {"hashes": {"sha256Hash": f.get("sha256"), "quickXorHash": f.get("quick")}}}
                    for f in self.od_files if f["parent"] == folder]
            return httpx.Response(200, json={"value": kids})
        if path.endswith("/copy") and m == "POST":
            src = next(f for f in self.od_files if f["id"] == path.split("/")[4])
            self.copies.append({"provider": "onedrive", "src": src["id"], "folder": self.od_path(body["parentReference"]["id"]), "name": body["name"]})
            self.od_files.append({**src, "id": f"c{len(self.copies)}", "parent": body["parentReference"]["id"], "name": body["name"], "copy": True})
            return httpx.Response(202, headers={"location": "https://monitor.example/api/v2.0/monitor/1"})
        return httpx.Response(404)

    # ------------------------------------------------------------ Drive
    def drive(self, m, path, q, body, host):
        if host == "lh3.googleusercontent.com":
            return httpx.Response(200, content=png())
        if path == "/drive/v3/files/root":
            return httpx.Response(200, json={"id": "groot"})
        if path == "/drive/v3/files" and m == "GET":
            query = q.get("q", [""])[0]
            if "mimeType = 'application/vnd.google-apps.folder'" in query:   # Ordnersuche
                name = query.split("name = '")[1].split("'")[0]
                parent = query.split("and '")[1].split("'")[0]
                hit = [{"id": f["id"]} for f in self.gd if f["name"] == name and parent in f["parents"] and f["mimeType"].endswith("folder")]
                return httpx.Response(200, json={"files": hit})
            if "in parents" in query:   # Inhalt eines Ordners
                parent = query.split("'")[1]
                return httpx.Response(200, json={"files": [f for f in self.gd if parent in f["parents"]]})
            return httpx.Response(200, json={"files": [f for f in self.gd if not f.get("copy")]})
        if path == "/drive/v3/files" and m == "POST":
            assert body["mimeType"] == "application/vnd.google-apps.folder"
            fid = f"gf{len(self.gd)}"
            self.gd.append({"id": fid, "name": body["name"], "mimeType": body["mimeType"], "parents": body["parents"]})
            return httpx.Response(200, json={"id": fid})
        if path.endswith("/copy") and m == "POST":
            src = next(f for f in self.gd if f["id"] == path.split("/")[4])
            self.copies.append({"provider": "gdrive", "src": src["id"], "folder": body["parents"][0], "name": body["name"]})
            self.gd.append({**src, "id": f"gc{len(self.copies)}", "name": body["name"], "parents": body["parents"], "copy": True})
            return httpx.Response(200, json={"id": "x"})
        if path.startswith("/drive/v3/files/"):
            return httpx.Response(200, json={"thumbnailLink": "https://lh3.googleusercontent.com/abc=s220"})
        return httpx.Response(404)


@pytest.fixture()
def cloud_env(tmp_path, monkeypatch):
    src = tmp_path / "pc"
    src.mkdir()
    (src / "Steuerbescheid_2023_lokal.pdf").write_bytes(STEUER)   # gleicher Inhalt wie in OneDrive
    cfg = {
        "server": {"data_dir": str(tmp_path / "data")},
        "target": {"root": str(tmp_path / "ziel")},
        "llm": {"provider": "rules"},
        "analysis": {"ocr": False},
        "computers": [{"id": "pc", "name": "PC", "volumes": [{"id": "pc-c", "name": "C", "path": str(src)}]}],
        "cloud_api": {"accounts": [
            {"id": "od", "provider": "onedrive", "name": "OneDrive Andreas", "client_id": "azure-app-id", "tenant": "consumers"},
            {"id": "gd", "provider": "gdrive", "name": "Google Drive", "client_id": "x.apps.googleusercontent.com", "client_secret": "s"},
        ]},
    }
    (tmp_path / "fdv.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(tmp_path / "fdv.yaml"))
    from app.config import get_settings
    get_settings.cache_clear()
    from app.connectors import cloud_api
    fake = FakeCloud()
    monkeypatch.setattr(cloud_api, "TRANSPORT", httpx.MockTransport(fake.handle))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c, fake, cloud_api


def wait(c, job_id):
    for _ in range(200):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "läuft":
            return j
        time.sleep(0.05)
    raise TimeoutError


def login(c, acc_id, write=False):
    url = c.post(f"/api/cloud/{acc_id}/connect", json={"write": write}).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"][0]
    r = c.get("/api/cloud/callback", params={"code": "CODE", "state": q["state"][0]})
    assert r.status_code == 200 and "verbunden" in r.text
    return q


def test_cloud_scan_analyze_and_server_side_copy(cloud_env):
    c, fake, cloud_api = cloud_env
    accs = {a["id"]: a for a in c.get("/api/cloud/accounts").json()["accounts"]}
    assert not accs["od"]["connected"] and accs["od"]["configured"]

    q = login(c, "od")
    assert "Files.Read.All" in q["scope"][0] and "ReadWrite" not in q["scope"][0]   # zuerst nur lesen
    login(c, "gd")
    assert c.get("/api/cloud/accounts").json()["accounts"][0]["connected"]

    j = wait(c, c.post("/api/pipeline/scan", json={}).json()["job_id"])
    assert j["stats"]["cloud_konten"] == 2 and j["stats"]["cloud_dateien"] == 4
    files = {f["name"]: f for f in c.get("/api/files?limit=50").json()["items"]}
    assert files["Steuerbescheid_2023.pdf"]["rel_path"] == "Dokumente/Steuer/Steuerbescheid_2023.pdf"
    assert files["GenAI Strategie.gslides"]["file_type"] == "Präsentation"          # Google-Präsentation erkannt
    assert "alte_kopie.pdf" not in files and "Fremd.pdf" not in files and "weg.txt" not in files
    # Duplikat über lokal ↔ OneDrive (gleicher SHA-256)
    assert files["Steuerbescheid_2023.pdf"]["dup_count"] == 2 and files["Steuerbescheid_2023_lokal.pdf"]["dup_count"] == 2

    j = wait(c, c.post("/api/pipeline/analyze", json={}).json()["job_id"])
    assert j["status"] == "fertig", j
    files = {f["name"]: f for f in c.get("/api/files?limit=50").json()["items"]}
    assert files["Angebot_Nordwind.pdf"]["thumbs"] == 1 and files["Angebot_Nordwind.pdf"]["thumbs_complete"] == 0  # Deckblatt aus der Cloud
    assert files["Projektplan_Phoenix.pptx"]["category"] == "Projekte"
    import re
    downloads = [p for _, p in fake.calls if re.search(r"/items/[^/]+/content$|/export$", p)]
    assert not downloads, f"es wurde heruntergeladen: {downloads}"
    assert c.get(f"/api/files/{files['Projektplan_Phoenix.pptx']['id']}/raw", follow_redirects=False).headers["location"] \
        == "https://onedrive.live.com/o2"

    # Schritt 4 ohne Schreibrecht → verständlicher Fehler, keine Kopie
    c.post("/api/review", json={"action": "freigeben", "folder": ""})
    j = wait(c, c.post("/api/pipeline/copy", json={}).json()["job_id"])
    assert j["stats"]["cloud_serverseitig"] == 0 and fake.copies == []
    ops = c.get("/api/copy/ops").json()
    assert any("Schreibzugriff" in o["message"] for o in ops)

    # Mit Schreibrecht: serverseitige Kopien in Future-Dateiverwaltung/…
    q = login(c, "od", write=True)
    assert "Files.ReadWrite.All" in q["scope"][0]
    login(c, "gd", write=True)
    j = wait(c, c.post("/api/pipeline/copy", json={}).json()["job_id"])
    # 2× OneDrive + 2× Google Drive; der lokale Steuerbescheid ist Duplikat der OneDrive-Datei → nicht doppelt kopiert
    assert j["stats"]["cloud_serverseitig"] == 4 and j["stats"]["kopiert"] == 4, j["stats"]
    root = Path(c.get("/api/settings").json()["target_root"])
    # nichts lokal kopiert – nur der Prüfbericht zum Kopiervorgang liegt im Zielordner
    assert not [p for p in root.rglob("*.pdf") if "_Prüfberichte" not in p.parts]
    od_copies = [x for x in fake.copies if x["provider"] == "onedrive"]
    assert all(x["folder"].startswith("Future-Dateiverwaltung/02_Beruf") or x["folder"].startswith("Future-Dateiverwaltung/01_Privat")
               for x in od_copies)
    # Zweiter Lauf: identische Dateien im Ziel → übersprungen, keine neuen Kopien
    assert {x["name"] for x in fake.copies if x["provider"] == "gdrive"} == {"Angebot_Nordwind.pdf", "GenAI Strategie"}
    n = len(fake.copies)
    j = wait(c, c.post("/api/pipeline/copy", json={}).json()["job_id"])
    assert len(fake.copies) == n and j["stats"]["cloud_serverseitig"] == 0
    assert not any(m in ("DELETE", "PATCH", "PUT") for m, _ in fake.calls)


def test_safe_http_blocks_destructive_calls(cloud_env):
    c, fake, cloud_api = cloud_env
    login(c, "od", write=True)
    login(c, "gd", write=True)
    od = cloud_api.provider(cloud_api.account("od"), cloud_api.TRANSPORT)
    gd = cloud_api.provider(cloud_api.account("gd"), cloud_api.TRANSPORT)
    with pytest.raises(cloud_api.CloudSafetyError):
        od.http.delete("https://graph.microsoft.com/v1.0/me/drive/items/o1")
    with pytest.raises(cloud_api.CloudSafetyError):
        od.http.patch("https://graph.microsoft.com/v1.0/me/drive/items/o1")          # Verschieben/Umbenennen
    with pytest.raises(cloud_api.CloudSafetyError):
        od.http.post("https://graph.microsoft.com/v1.0/me/drive/items/o1/invite", {})
    with pytest.raises(cloud_api.CloudSafetyError):
        od.http.post("https://graph.microsoft.com/v1.0/me/drive/items/x/children", {"name": "a.txt", "file": {}})   # keine Dateien anlegen
    with pytest.raises(cloud_api.CloudSafetyError):
        od.http.post("https://graph.microsoft.com/v1.0/me/drive/items/o1/copy",
                     {"name": "a", "@microsoft.graph.conflictBehavior": "replace"})
    with pytest.raises(cloud_api.CloudSafetyError):
        gd.http.post("https://www.googleapis.com/drive/v3/files", {"name": "x.txt", "mimeType": "text/plain"})
    with pytest.raises(cloud_api.CloudSafetyError):
        gd.http.post("https://www.googleapis.com/drive/v3/files/g1/trash", {})
    assert not any(m in ("DELETE", "PATCH", "PUT") for m, _ in fake.calls)


def test_callback_rejects_unknown_state(cloud_env):
    c, _, _ = cloud_env
    r = c.get("/api/cloud/callback", params={"code": "x", "state": "gefälscht"})
    assert "fehlgeschlagen" in r.text
    assert not c.get("/api/cloud/accounts").json()["accounts"][0]["connected"]
