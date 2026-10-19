"""Punkt 5 – Anmeldung & HTTPS: lokal vs. Netzwerk, erstes Konto, Rollen, CSRF, Sperre, API-Key, Zertifikate."""
import os
import ssl
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

H = {"X-FDV-Request": "1"}
PW = "sehr-geheim-123"


@pytest.fixture()
def apps(tmp_path, monkeypatch):
    cfg = {"server": {"data_dir": str(tmp_path / "data")}, "target": {"root": str(tmp_path / "ziel")},
           "computers": [{"id": "pc", "name": "PC", "volumes": [{"id": "pc-c", "name": "C", "path": str(tmp_path)}]}]}
    (tmp_path / "fdv.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(tmp_path / "fdv.yaml"))
    from app import auth
    auth._fails.clear()
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as local:  # „testclient“ zählt als dieser Computer (localhost)
        net = TestClient(app, client=("192.168.1.50", 50000))  # Zugriff aus dem Netzwerk
        yield local, net, tmp_path


def test_without_account_only_local(apps):
    local, net, _ = apps
    assert local.get("/api/stats").status_code == 200
    r = net.get("/api/stats")
    assert r.status_code == 401 and r.json()["login"]
    st = net.get("/api/auth/status").json()
    assert st["required"] and not st["can_bootstrap"]
    assert net.post("/api/auth/bootstrap", json={"username": "andreas", "password": PW}).status_code == 403
    assert net.get("/").status_code == 200  # Oberfläche (Anmeldeseite) wird ausgeliefert
    assert "Content-Security-Policy" in net.get("/").headers


def test_bootstrap_login_roles_csrf(apps):
    local, net, _ = apps
    assert local.post("/api/auth/bootstrap", json={"username": "andreas", "password": "kurz"}).status_code == 400
    r = local.post("/api/auth/bootstrap", json={"username": "Andreas", "password": PW})
    assert r.status_code == 200 and r.json()["user"]["username"] == "andreas"
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert local.post("/api/auth/bootstrap", json={"username": "x", "password": PW}).status_code == 409

    # Mit Konto gilt die Anmeldung für alle – auch lokal
    local.cookies.clear()
    assert local.get("/api/stats").status_code == 401
    assert net.post("/api/auth/login", json={"username": "andreas", "password": "falsch-falsch"}).status_code == 401
    assert net.post("/api/auth/login", json={"username": "andreas", "password": PW}).status_code == 200
    assert net.get("/api/stats").status_code == 200
    # CSRF: ändernde Anfrage mit Sitzung ohne Kennung der Oberfläche → abgelehnt
    assert net.post("/api/backup").status_code == 403
    assert net.post("/api/backup", headers=H).status_code == 200

    # Leser darf ansehen, aber nichts ändern
    assert net.post("/api/auth/users", json={"username": "gast", "password": PW, "role": "leser"}, headers=H).status_code == 200
    from fastapi.testclient import TestClient

    from app.main import app
    guest = TestClient(app, client=("192.168.1.51", 50000))
    guest.post("/api/auth/login", json={"username": "gast", "password": PW})
    assert guest.get("/api/files").status_code == 200
    r = guest.post("/api/review", json={"action": "freigeben", "folder": ""}, headers=H)
    assert r.status_code == 403 and "Lesezugriff" in r.json()["detail"]
    assert guest.get("/api/auth/access").status_code == 403

    # Letzter Admin kann nicht entfernt werden; Konten werden deaktiviert statt gelöscht
    r = net.post("/api/auth/users/andreas", json={"active": False}, headers=H)
    assert r.status_code == 400
    assert net.post("/api/auth/users/gast", json={"active": False}, headers=H).status_code == 200
    assert guest.get("/api/files").status_code == 401  # Sitzung des deaktivierten Kontos ist beendet
    assert net.delete("/api/auth/users/gast").status_code == 405  # Löschen bleibt grundsätzlich gesperrt

    net.post("/api/auth/logout", headers=H)
    assert net.get("/api/stats").status_code == 401


def test_lockout_and_api_key(apps):
    local, net, _ = apps
    local.post("/api/auth/bootstrap", json={"username": "andreas", "password": PW})
    for _ in range(5):
        net.post("/api/auth/login", json={"username": "andreas", "password": "falsch-falsch"})
    r = net.post("/api/auth/login", json={"username": "andreas", "password": PW})
    assert r.status_code == 429  # nach 5 Fehlversuchen gesperrt – auch mit richtigem Passwort

    key = local.post("/api/auth/api-key", headers=H).json()["api_key"]
    agent = net
    agent.cookies.clear()
    assert agent.get(f"/api/agents/pc/config").status_code == 401
    assert agent.get(f"/api/agents/pc/config", headers={"X-API-Key": "falsch"}).status_code == 401
    assert agent.get(f"/api/agents/pc/config", headers={"X-API-Key": key}).status_code == 200
    from app import auth
    if os.name != "nt":  # Unix-Dateirechte; unter Windows schützt das Benutzerprofil
        assert (auth._secrets_file().stat().st_mode & 0o777) == 0o600


def test_tls_certificates(apps):
    local, _, tmp = apps
    local.post("/api/auth/bootstrap", json={"username": "andreas", "password": PW})
    info = local.post("/api/auth/tls", headers=H).json()
    assert info["aktiv"] and info["fingerprint"] and "localhost" in info["namen"]
    from app import tls
    p = tls.paths()
    # Serverzertifikat ist von der eigenen CA signiert und für localhost gültig
    ctx = ssl.create_default_context(cafile=str(p["ca"]))
    ctx.load_cert_chain(str(p["cert"]), str(p["key"]))  # Schlüssel passt zum Zertifikat
    # echte TLS-Verbindung im Speicher mit strenger Prüfung (wie Python ≥ 3.13 und httpx im Agenten)
    srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    srv.load_cert_chain(str(p["cert"]), str(p["key"]))
    cli = ssl.create_default_context(cafile=str(p["ca"]))
    cli.verify_flags |= getattr(ssl, "VERIFY_X509_STRICT", 0)
    a_in, a_out, b_in, b_out = ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO(), ssl.MemoryBIO()
    c_sock = cli.wrap_bio(a_in, a_out, server_hostname="localhost")
    s_sock = srv.wrap_bio(b_in, b_out, server_side=True)
    for _ in range(10):
        for sock in (c_sock, s_sock):
            try:
                sock.do_handshake()
            except ssl.SSLWantReadError:
                pass
        b_in.write(a_out.read())
        a_in.write(b_out.read())
    assert c_sock.version() and c_sock.getpeercert()["subjectAltName"]
    from cryptography import x509
    leaf = x509.load_pem_x509_certificate(p["cert"].read_bytes())
    ca = x509.load_pem_x509_certificate(p["ca"].read_bytes())
    leaf.verify_directly_issued_by(ca)
    if os.name != "nt":
        assert (p["key"].stat().st_mode & 0o777) == 0o600
    assert local.get("/api/auth/ca.pem").text.startswith("-----BEGIN CERTIFICATE-----")
    fp_before = tls.fingerprint()
    tls.ensure()
    assert tls.fingerprint() == fp_before  # vorhandene Zertifikate werden nie ersetzt


def test_agent_pins_fingerprint(apps, monkeypatch):
    local, _, tmp = apps
    from app import agent_client, tls
    tls.ensure()
    pem = tls.paths()["ca"].read_text()
    monkeypatch.setattr(agent_client.Path, "home", classmethod(lambda cls: tmp / "agenthome"))
    (tmp / "agenthome").mkdir()

    class R:
        text = pem
        def raise_for_status(self):
            return self
    monkeypatch.setattr(agent_client.httpx, "get", lambda *a, **k: R())
    with pytest.raises(SystemExit) as e:
        agent_client.trusted_ca("https://buero:8800", "AA:BB")
    assert "stimmt nicht" in str(e.value)
    path = agent_client.trusted_ca("https://buero:8800", tls.fingerprint())
    assert Path(path).read_text() == pem
