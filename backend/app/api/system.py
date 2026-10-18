"""API: Quellen/Connectoren, Programme & LLMs, Einstellungen, Skills, Kategorien, Audit."""
from __future__ import annotations

import json
import os
import shutil
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from ..categories import as_dicts
from .. import platform_tools
from ..config import get_settings
from ..connectors import cloud
from ..llm import costs
from ..skills import list_skills, ocr, thumbcache

router = APIRouter(prefix="/api", tags=["System"])


@router.get("/health")
def health():
    return {"ok": True, "app": "Future Dateiverwaltung"}


@router.get("/sources")
def sources():
    s = get_settings()
    comps = db.query("SELECT * FROM computers ORDER BY name")
    vols = db.query("""SELECT v.*, COUNT(f.id) files, COALESCE(SUM(f.size),0) bytes,
                       SUM(f.status='analysiert') analyzed FROM volumes v
                       LEFT JOIN files f ON f.volume_id=v.id AND f.missing=0 GROUP BY v.id""")
    for v in vols:
        v["reachable"] = os.path.isdir(v["path"])
    for c in comps:
        c["volumes"] = [v for v in vols if v["computer_id"] == c["id"]]
    return {
        "computers": comps,
        "cloud_detected": cloud.detect(),
        "this_host": cloud.host_info(),
        "target_root": s.target_root,
        "target_structure": s.target_structure,
        "config_file": str(s.source),
    }


@router.get("/programs")
def programs(computer: Optional[str] = None, kind: Optional[str] = None, q: Optional[str] = None, limit: int = 2000):
    where, args = ["1=1"], []
    if computer:
        where.append("p.computer_id=?")
        args.append(computer)
    if kind:
        where.append("p.kind=?")
        args.append(kind)
    if q:
        where.append("(p.name LIKE ? OR p.publisher LIKE ? OR p.category LIKE ?)")
        args += [f"%{q}%"] * 3
    rows = db.query(f"""SELECT p.*, c.name computer_name FROM programs p LEFT JOIN computers c ON c.id=p.computer_id
                        WHERE {' AND '.join(where)}
                        ORDER BY CASE p.kind WHEN 'llm-modell' THEN 0 WHEN 'llm-tool' THEN 1 WHEN 'dev-tool' THEN 2 ELSE 3 END,
                        p.name COLLATE NOCASE LIMIT ?""", [*args, limit])
    summary = db.query("SELECT computer_id, kind, COUNT(*) n FROM programs GROUP BY 1,2")
    return {"items": rows, "summary": summary}


@router.get("/categories")
def categories():
    counts = {r["category"]: r for r in db.query(
        "SELECT category, COUNT(*) n, SUM(size) bytes FROM files WHERE missing=0 GROUP BY 1")}
    out = as_dicts()
    for c in out:
        r = counts.get(c["name"])
        c["count"] = r["n"] if r else 0
        c["bytes"] = r["bytes"] if r else 0
    return out


@router.get("/skills")
def skills():
    return list_skills()


@router.get("/settings")
def settings():
    s = get_settings()
    return {
        "llm": {**s.llm, "anthropic_key_present": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))},
        "analysis": s.analysis,
        "cloud": s.cloud,
        "cloud_api": {"download_content": bool((s.raw.get("cloud_api") or {}).get("download_content")),
                      "download_max_mb": (s.raw.get("cloud_api") or {}).get("download_max_mb", 25)},
        "cache": thumbcache.usage(),
        "llm_kosten": costs.totals(),
        "target_root": s.target_root,
        "target_structure": s.target_structure,
        "ocr_available": ocr.available(),
        "libreoffice_available": bool(platform_tools.soffice()),
        "api_key_enabled": bool(s.api_key),
        "config_file": str(s.source),
    }


class SettingsIn(BaseModel):
    mode: Optional[str] = None
    batch: Optional[bool] = None
    max_cost_usd: Optional[float] = None
    thumbnails_mode: Optional[str] = None
    thumbs_budget_gb: Optional[float] = None
    download_online_only: Optional[bool] = None
    cloud_download_content: Optional[bool] = None
    provider: Optional[str] = None
    anthropic_model: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    send_content_to_cloud: Optional[bool] = None
    target_structure: Optional[str] = None
    ocr: Optional[bool] = None


@router.post("/settings")
def update_settings(body: SettingsIn):
    s = get_settings()
    upd = body.model_dump(exclude_none=True)
    if "provider" in upd and upd["provider"] not in ("anthropic", "ollama", "rules"):
        raise HTTPException(400, "provider: anthropic | ollama | rules")
    if "target_structure" in upd:
        try:
            upd["target_structure"].format(group="g", category="c", subcategory="s", year=2020, month="01", type="t")
        except (KeyError, IndexError, ValueError) as exc:
            raise HTTPException(400, f"Ungültiger Platzhalter in der Struktur: {exc}")
        s.target_structure = upd.pop("target_structure")
    if "ocr" in upd:
        s.analysis["ocr"] = upd.pop("ocr")
    if upd.get("mode") not in (None, "alle", "unklare"):
        raise HTTPException(400, "mode: alle | unklare")
    if upd.get("thumbnails_mode") not in (None, "smart", "alle", "bei_bedarf"):
        raise HTTPException(400, "thumbnails_mode: smart | alle | bei_bedarf")
    for k in ("thumbnails_mode", "thumbs_budget_gb"):
        if k in upd:
            s.analysis[k] = upd.pop(k)
    if "download_online_only" in upd:
        s.cloud["download_online_only"] = upd.pop("download_online_only")
    if "cloud_download_content" in upd:
        s.raw.setdefault("cloud_api", {})["download_content"] = upd.pop("cloud_download_content")
    s.llm.update(upd)
    _persist_overrides()
    return settings()


class TestLlmIn(BaseModel):
    provider: Optional[str] = None


@router.post("/settings/test-llm")
def test_llm(body: TestLlmIn):
    """Verbindung zum LLM prüfen: analysiert eine Beispieldatei ohne Fallback."""
    from .. import llm
    return llm.test_connection(body.provider)


def _persist_overrides():
    s = get_settings()
    p = s.data_dir / "overrides.json"
    p.write_text(json.dumps({"llm": s.llm, "target_structure": s.target_structure, "ocr": s.analysis.get("ocr"),
                             "thumbnails_mode": s.analysis.get("thumbnails_mode"),
                             "thumbs_budget_gb": s.analysis.get("thumbs_budget_gb"),
                             "download_online_only": s.cloud.get("download_online_only"),
                             "cloud_download_content": (s.raw.get("cloud_api") or {}).get("download_content")},
                            ensure_ascii=False, indent=2), encoding="utf-8")


def load_overrides():
    s = get_settings()
    p = s.data_dir / "overrides.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        s.llm.update(d.get("llm", {}))
        if d.get("target_structure"):
            s.target_structure = d["target_structure"]
        if d.get("ocr") is not None:
            s.analysis["ocr"] = d["ocr"]
        for k in ("thumbnails_mode", "thumbs_budget_gb"):
            if d.get(k) is not None:
                s.analysis[k] = d[k]
        if d.get("download_online_only") is not None:
            s.cloud["download_online_only"] = d["download_online_only"]
        if d.get("cloud_download_content") is not None:
            s.raw.setdefault("cloud_api", {})["download_content"] = d["cloud_download_content"]


@router.get("/audit")
def audit(limit: int = 200):
    return db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
