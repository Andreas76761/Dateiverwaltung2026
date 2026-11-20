"""Windows-Installationspaket: Erst-Konfiguration des Starters und geordnetes Beenden (nur lokal, nur mit Schlüssel)."""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[2]


def load_starter():
    spec = importlib.util.spec_from_file_location("starter", ROOT / "packaging" / "windows" / "starter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_erst_konfiguration(tmp_path, monkeypatch):
    st = load_starter()
    monkeypatch.setattr(st, "HOME", tmp_path / "Lokal" / "FutureDateiverwaltung")
    monkeypatch.setattr(st, "CONFIG", st.HOME / "fdv.yaml")
    monkeypatch.setenv("OneDrive", str(tmp_path / "C:\\Users\\Andreas Müller\\OneDrive"))  # Backslashes + Leerzeichen + Umlaut
    st.ensure_config()
    raw = yaml.safe_load(st.CONFIG.read_text(encoding="utf-8"))
    assert raw["server"]["data_dir"] == str(st.HOME / "daten")
    assert raw["computers"] == [] and raw["llm"]["provider"] == "rules"
    assert raw["target"]["structure"] == "{group}/{category}/{year}"
    st.CONFIG.write_text("server: {port: 9000}\n", encoding="utf-8")
    st.ensure_config()  # vorhandene Einstellungen werden nie überschrieben
    assert st.settings()["port"] == 9000


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "fdv.yaml").write_text(yaml.safe_dump({"server": {"data_dir": str(tmp_path / "daten")}, "computers": []}), encoding="utf-8")
    monkeypatch.setenv("FDV_CONFIG", str(tmp_path / "fdv.yaml"))
    monkeypatch.setenv("FDV_SHUTDOWN_TOKEN", "richtig")
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c, TestClient(app, client=("192.168.1.50", 5000))


def test_beenden_nur_lokal_mit_schluessel(client, monkeypatch):
    local, net = client
    import threading
    started = []
    monkeypatch.setattr(threading, "Timer", lambda delay, fn: type("T", (), {"start": lambda self: started.append(delay)})())
    assert local.post("/api/system/beenden").status_code == 403
    assert local.post("/api/system/beenden", headers={"X-FDV-Shutdown": "falsch"}).status_code == 403
    assert net.post("/api/system/beenden", headers={"X-FDV-Shutdown": "richtig"}).status_code == 403
    assert not started
    assert local.post("/api/system/beenden", headers={"X-FDV-Shutdown": "richtig"}).json()["ok"]
    assert started == [0.3]
    st = local.get("/api/setup").json()
    assert st["configured"] is False and not st["demo"]
