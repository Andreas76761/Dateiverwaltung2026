"""Konfiguration laden (config/fdv.yaml, Fallback config/fdv.example.yaml)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# USD je 1 Mio. Tokens (Anthropic-Listenpreise, Stand 10/2026). In config/fdv.yaml unter llm.prices überschreibbar.
DEFAULT_PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
    "claude-fable-5-1": {"input": 10.00, "output": 50.00, "cache_read": 0.25},
}


def _resolve(p: str) -> str:
    path = Path(os.path.expanduser(p))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


class Settings:
    def __init__(self, raw: dict[str, Any], source: Path):
        self.raw = raw
        self.source = source
        srv = raw.get("server", {})
        self.host = srv.get("host", "0.0.0.0")
        self.port = int(srv.get("port", 8800))
        self.api_key = os.environ.get("FDV_API_KEY", srv.get("api_key", "") or "")
        self.data_dir = Path(_resolve(os.environ.get("FDV_DATA_DIR", srv.get("data_dir", "./data"))))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "thumbs").mkdir(exist_ok=True)

        self.llm = {
            "provider": "rules",
            "anthropic_model": "claude-opus-5-5",
            "ollama_url": "http://localhost:11434",
            "ollama_model": "llama3.1",
            "max_chars": 6000,
            "send_content_to_cloud": False,
            **raw.get("llm", {}),
        }
        if os.environ.get("FDV_LLM_PROVIDER"):
            self.llm["provider"] = os.environ["FDV_LLM_PROVIDER"]

        self.llm.setdefault("mode", "alle")                 # alle | unklare (nur unsichere Dateien an das LLM)
        self.llm.setdefault("hybrid_min_confidence", 0.6)  # ab dieser Regel-Sicherheit kein LLM-Aufruf
        self.llm.setdefault("batch", False)                # Anthropic Message Batches (50 % günstiger, asynchron)
        self.llm.setdefault("max_cost_usd", 25.0)          # Kostenlimit je Analyse-Lauf (0 = kein Limit)
        self.llm.setdefault("confirm_above_usd", 0.0)      # ab diesem Schätzwert Bestätigung (0 = immer bei Cloud-LLM)
        self.llm.setdefault("est_output_tokens", 450)      # Schätzung: JSON-Antwort + Denk-Tokens bei effort=low
        self.llm.setdefault("usd_eur", 0.92)
        self.llm["prices"] = {**DEFAULT_PRICES, **(self.llm.get("prices") or {})}

        self.analysis = {
            "ocr": True,
            "ocr_languages": "deu+eng",
            "thumbnails": True,
            "thumbnail_max_pages": 200,
            "thumbnails_mode": "smart",          # smart | alle | bei_bedarf
            "thumbs_all_pages_min_importance": 50,  # smart: ab dieser Wichtigkeit alle Seiten sofort
            "thumbs_budget_gb": 20,              # Obergrenze für Miniaturen + PDF-Cache
            "video_frames": 8,
            "hash_max_mb": 4096,
            "auto_resume": True,                 # abgebrochene Analyse nach Neustart fortsetzen
            **raw.get("analysis", {}),
        }
        self.cloud = {
            "download_online_only": False,       # Nur-online-Dateien lesen/kopieren (löst Download aus!)
            "sparse_heuristic": False,           # Linux/FUSE: Größe > 0 ohne Blöcke = online
            **raw.get("cloud", {}),
        }
        tgt = raw.get("target", {})
        self.target_root = _resolve(tgt.get("root", "./data/target"))
        self.target_structure = tgt.get("structure", "{group}/{category}/{year}")

        scan = raw.get("scan", {})
        self.exclude_dirs = set(scan.get("exclude_dirs", []))
        self.exclude_ext = {e.lower() for e in scan.get("exclude_ext", [])}
        self.follow_symlinks = bool(scan.get("follow_symlinks", False))
        self.max_files = int(scan.get("max_files", 0) or 0)  # je Festplatte (0 = unbegrenzt) – z. B. für Probeläufe

        self.computers = []
        for c in raw.get("computers", []):
            vols = []
            for v in c.get("volumes", []):
                vols.append({**v, "path": _resolve(v["path"]) if c.get("mode", "local") == "local" else v["path"]})
            self.computers.append({**c, "mode": c.get("mode", "local"), "volumes": vols})

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fdv.sqlite3"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"


@lru_cache
def get_settings() -> Settings:
    cfg = os.environ.get("FDV_CONFIG")
    candidates = [Path(cfg)] if cfg else [PROJECT_ROOT / "config/fdv.yaml", PROJECT_ROOT / "config/fdv.example.yaml"]
    for c in candidates:
        if c.exists():
            with open(c, encoding="utf-8") as fh:
                return Settings(yaml.safe_load(fh) or {}, c)
    return Settings({}, Path("<defaults>"))
