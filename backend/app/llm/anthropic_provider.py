"""Claude über das offizielle Anthropic SDK (structured outputs, effort low für Massenklassifikation)."""
from __future__ import annotations

import json

import anthropic

from ..config import get_settings
from . import SCHEMA, SYSTEM_PROMPT, build_user_prompt


class AnthropicProvider:
    name = "anthropic"

    def __init__(self):
        cfg = get_settings().llm
        self.model = cfg.get("anthropic_model", "claude-opus-5-5")
        self.max_chars = int(cfg.get("max_chars", 6000))
        self.include_content = bool(cfg.get("send_content_to_cloud", False))
        # Zugangsdaten aus ANTHROPIC_API_KEY bzw. `ant auth login`
        self.client = anthropic.Anthropic(max_retries=4)

    def analyze(self, meta: dict, text: str) -> dict:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=2000,
            # Bei einer Ablehnung durch Sicherheitsfilter automatisch auf ein passendes Modell ausweichen
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": build_user_prompt(meta, text[: self.max_chars], self.include_content)}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Anfrage vom Modell abgelehnt")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Antwort abgeschnitten (max_tokens)")
        out = next(b.text for b in response.content if b.type == "text")
        return json.loads(out)
