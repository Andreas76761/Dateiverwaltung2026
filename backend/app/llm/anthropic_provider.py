"""Claude über das offizielle Anthropic SDK (structured outputs, effort low für Massenklassifikation)."""
from __future__ import annotations

import json
import threading

import anthropic

from ..config import get_settings
from . import SCHEMA, SYSTEM_PROMPT, FatalLLMError, build_user_prompt

_client: anthropic.Anthropic | None = None
_lock = threading.Lock()


def client() -> anthropic.Anthropic:
    """Ein gemeinsamer Client für alle Threads (Zugangsdaten aus ANTHROPIC_API_KEY bzw. `ant auth login`)."""
    global _client
    with _lock:
        if _client is None:
            _client = anthropic.Anthropic(max_retries=4, timeout=120)
        return _client


class AnthropicProvider:
    name = "anthropic"

    def __init__(self):
        cfg = get_settings().llm
        self.model = cfg.get("anthropic_model", "claude-opus-5-5")
        self.max_chars = int(cfg.get("max_chars", 6000))
        self.include_content = bool(cfg.get("send_content_to_cloud", False))
        self.last_usage: dict | None = None

    def analyze(self, meta: dict, text: str) -> dict:
        try:
            c = client()
        except Exception as exc:  # z. B. keine Zugangsdaten auffindbar
            raise FatalLLMError(f"Anthropic-Client nicht nutzbar: {exc}") from None
        try:
            response = c.beta.messages.create(
                model=self.model,
                max_tokens=2000,
                # Bei einer Ablehnung durch Sicherheitsfilter automatisch auf ein passendes Modell ausweichen
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": build_user_prompt(meta, text[: self.max_chars], self.include_content)}],
            )
        except anthropic.AuthenticationError:
            raise FatalLLMError("API-Key fehlt oder ist ungültig (ANTHROPIC_API_KEY auf dem Server setzen)") from None
        except anthropic.PermissionDeniedError:
            raise FatalLLMError("API-Key hat keine Berechtigung für dieses Modell") from None
        except anthropic.NotFoundError:
            raise FatalLLMError(f"Modell '{self.model}' nicht gefunden") from None
        except anthropic.RateLimitError:
            raise RuntimeError("Rate-Limit erreicht – später erneut versuchen oder weniger parallel analysieren") from None
        except anthropic.BadRequestError as exc:
            raise RuntimeError(f"Ungültige Anfrage: {exc.message}") from None
        except anthropic.APIStatusError as exc:
            raise RuntimeError(f"API-Fehler {exc.status_code}: {exc.message}") from None
        except TypeError as exc:  # SDK meldet fehlende Zugangsdaten als TypeError
            raise FatalLLMError("Kein API-Key gefunden – ANTHROPIC_API_KEY auf dem Server setzen") from None
        except anthropic.APIConnectionError:
            raise RuntimeError("Keine Verbindung zur Anthropic-API (Netzwerk/Proxy prüfen)") from None

        if response.stop_reason == "refusal":
            raise RuntimeError("Anfrage vom Modell abgelehnt")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Antwort abgeschnitten (max_tokens)")
        u = response.usage
        self.last_usage = {"input": u.input_tokens, "output": u.output_tokens,
                           "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0, "model": response.model}
        out = next(b.text for b in response.content if b.type == "text")
        return json.loads(out)
