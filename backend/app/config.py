"""Konfiguration laden (config/fdv.yaml, Fallback config/fdv.example.yaml)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

        self.analysis = {
            "ocr": True,
            "ocr_languages": "deu+eng",
            "thumbnails": True,
            "thumbnail_max_pages": 200,
            "hash_max_mb": 2048,
            **raw.get("analysis", {}),
        }
        tgt = raw.get("target", {})
        self.target_root = _resolve(tgt.get("root", "./data/target"))
        self.target_structure = tgt.get("structure", "{group}/{category}/{year}")

        scan = raw.get("scan", {})
        self.exclude_dirs = set(scan.get("exclude_dirs", []))
        self.exclude_ext = {e.lower() for e in scan.get("exclude_ext", [])}
        self.follow_symlinks = bool(scan.get("follow_symlinks", False))

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
