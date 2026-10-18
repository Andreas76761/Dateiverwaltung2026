"""Kosten: Schätzung vor dem Lauf, Erfassung tatsächlicher Kosten, Kostenlimit je Lauf."""
from __future__ import annotations

import json
import threading

from .. import db
from ..config import get_settings

CHARS_PER_TOKEN = 3.2          # deutsche Texte (konservativ)
META_CHARS = 450               # Dateiname, Pfad, Computer, Typ, Größe, Datum
TEXT_TYPES = {"PDF", "Präsentation", "Textdokument", "Tabelle", "Text & Notizen", "E-Mail", "Quellcode",
              "Daten & Konfiguration", "Bild", "Video"}  # Bild = OCR-Text, Video = Metadaten


def price(model: str) -> dict:
    prices = get_settings().llm["prices"]
    return prices.get(model) or prices["claude-opus-5-5"]


def cost_usd(model: str, usage: dict, batch: bool = False) -> float:
    p = price(model)
    c = (usage.get("input", 0) * p["input"] + usage.get("cache_write", 0) * p["input"] * 1.25
         + usage.get("cache_read", 0) * p["cache_read"] + usage.get("output", 0) * p["output"]) / 1_000_000
    return c * (0.5 if batch else 1.0)


def system_tokens() -> int:
    from . import SCHEMA, SYSTEM_PROMPT

    return int((len(SYSTEM_PROMPT) + len(json.dumps(SCHEMA))) / CHARS_PER_TOKEN) + 150


def estimate(files: list[dict], model: str | None = None, mode: str | None = None, batch: bool | None = None) -> dict:
    """Kosten-Obergrenze für die Analyse dieser Dateien mit dem Cloud-LLM."""
    from .rules_provider import RulesProvider

    s = get_settings().llm
    model = model or s["anthropic_model"]
    mode = mode or s.get("mode", "alle")
    batch = s.get("batch", False) if batch is None else batch
    send_content = bool(s.get("send_content_to_cloud"))
    max_chars = int(s.get("max_chars", 6000))
    thr = float(s.get("hybrid_min_confidence", 0.6))
    rules = RulesProvider()

    n_llm, n_rules, content_tokens = 0, 0, 0
    for f in files:
        if mode == "unklare":
            conf = f.get("rules_confidence")
            if conf is None:
                conf = rules.analyze(f, f.get("text_excerpt") or "")["confidence"]
            if conf >= thr:
                n_rules += 1
                continue
        n_llm += 1
        if send_content and not f.get("online_only"):
            known = len(f.get("text_excerpt") or "") + len(f.get("ocr_text") or "")
            chars = min(known, max_chars) if known else (int(max_chars * 0.8) if f.get("file_type") in TEXT_TYPES else 0)
            content_tokens += int(chars / CHARS_PER_TOKEN)

    sys_t = system_tokens()
    meta_t = int(META_CHARS / CHARS_PER_TOKEN)
    out_t = int(s.get("est_output_tokens", 450))
    usage = {
        "input": n_llm * meta_t + content_tokens,
        "cache_write": sys_t if n_llm else 0,                 # System-Prompt einmal in den Cache
        "cache_read": max(n_llm - 1, 0) * sys_t,              # danach aus dem Cache gelesen
        "output": n_llm * out_t,
    }
    usd = cost_usd(model, usage, batch)
    alternatives = {m: round(cost_usd(m, usage, batch), 2) for m in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")}
    return {
        "dateien": len(files), "an_llm": n_llm, "nur_regeln": n_rules, "modell": model, "modus": mode, "batch": batch,
        "inhalte_senden": send_content, "tokens": usage, "kosten_usd": round(usd, 2),
        "kosten_eur": round(usd * float(s.get("usd_eur", 0.92)), 2), "kosten_ohne_batch_usd": round(cost_usd(model, usage, False), 2),
        "alternativen_usd": alternatives, "limit_usd": float(s.get("max_cost_usd", 0) or 0),
        "hinweis": "Obergrenze: Textlänge noch nicht analysierter Dateien wird geschätzt; tatsächliche Kosten meist niedriger.",
    }


class CostMeter:
    """Zählt Kosten eines Laufs threadsicher mit und stoppt LLM-Aufrufe beim Limit."""

    def __init__(self, job_id: int | None, limit_usd: float):
        self.job_id = job_id
        self.limit = float(limit_usd or 0)
        self.spent = 0.0
        self.calls = 0
        self.tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return not self.limit or self.spent < self.limit

    @property
    def exhausted(self) -> bool:
        return bool(self.limit) and self.spent >= self.limit

    def add(self, file_id: int | None, model: str, usage: dict | None, batch: bool = False) -> float:
        if not usage:
            return 0.0
        c = cost_usd(model, usage, batch)
        with self._lock:
            self.spent += c
            self.calls += 1
            for k in self.tokens:
                self.tokens[k] += int(usage.get(k, 0) or 0)
        with db.tx() as con:
            con.execute(
                """INSERT INTO llm_usage(job_id, file_id, model, input_tokens, output_tokens, cache_read, cache_write, batch, cost_usd, ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (self.job_id, file_id, model, usage.get("input", 0), usage.get("output", 0), usage.get("cache_read", 0),
                 usage.get("cache_write", 0), int(batch), c, db.now()))
        return c

    def stats(self) -> dict:
        return {"kosten_usd": round(self.spent, 6), "llm_aufrufe": self.calls, "tokens": dict(self.tokens),
                "kostenlimit_usd": self.limit, "kostenlimit_erreicht": self.exhausted}


def totals() -> dict:
    r = db.one("""SELECT COUNT(*) calls, COALESCE(SUM(cost_usd),0) usd, COALESCE(SUM(input_tokens),0) inp,
                  COALESCE(SUM(output_tokens),0) outp, COALESCE(SUM(cache_read),0) cr FROM llm_usage""")
    return {"aufrufe": r["calls"], "kosten_usd": round(r["usd"], 4), "input_tokens": r["inp"], "output_tokens": r["outp"],
            "cache_read_tokens": r["cr"]}
