"""Lokales LLM über Ollama – Inhalte verlassen den Rechner nicht."""
from __future__ import annotations

import httpx

from ..config import get_settings
from . import SCHEMA, SYSTEM_PROMPT, build_user_prompt, parse_json


class OllamaProvider:
    name = "ollama"

    def __init__(self):
        cfg = get_settings().llm
        self.url = cfg.get("ollama_url", "http://localhost:11434").rstrip("/")
        self.model = cfg.get("ollama_model", "llama3.1")
        self.max_chars = int(cfg.get("max_chars", 6000))

    def analyze(self, meta: dict, text: str) -> dict:
        r = httpx.post(
            f"{self.url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "format": SCHEMA,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(meta, text[: self.max_chars], True)},
                ],
            },
            timeout=180,
        )
        r.raise_for_status()
        return parse_json(r.json()["message"]["content"])
