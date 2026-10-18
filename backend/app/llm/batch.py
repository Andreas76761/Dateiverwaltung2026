"""Anthropic Message Batches: viele Analysen asynchron zum halben Preis.

Ablauf: Anfragen sammeln → Batch(es) anlegen (≤ 5.000 Anfragen je Batch) → Status abfragen →
Ergebnisse je custom_id (= Datei-ID) übernehmen. Batch-IDs werden in der DB gespeichert, damit ein
Neustart des Servers den Batch weiter abwarten und auswerten kann.
"""
from __future__ import annotations

import json

from .. import db
from ..config import get_settings
from . import FatalLLMError, normalize
from .anthropic_provider import client, request_params, usage_of

CHUNK = 5000


def build(file_id: int, meta: dict, text: str) -> dict:
    s = get_settings().llm
    return {"custom_id": str(file_id),
            "params": request_params(s["anthropic_model"], meta, text, int(s.get("max_chars", 6000)),
                                     bool(s.get("send_content_to_cloud")), batch=True)}


def submit(requests: list[dict], job_id: int | None) -> list[str]:
    """Legt Batches an und speichert sie. -> Liste der Batch-IDs"""
    import anthropic

    ids = []
    model = get_settings().llm["anthropic_model"]
    for i in range(0, len(requests), CHUNK):
        part = requests[i:i + CHUNK]
        try:
            b = client().messages.batches.create(requests=part)
        except anthropic.AuthenticationError:
            raise FatalLLMError("API-Key fehlt oder ist ungültig (ANTHROPIC_API_KEY auf dem Server setzen)") from None
        except TypeError:
            raise FatalLLMError("Kein API-Key gefunden – ANTHROPIC_API_KEY auf dem Server setzen") from None
        with db.tx() as c:
            c.execute("INSERT INTO llm_batches(batch_id, job_id, model, file_ids, status, created_at) VALUES (?,?,?,?, 'läuft', ?)",
                      (b.id, job_id, model, json.dumps([int(r["custom_id"]) for r in part]), db.now()))
        ids.append(b.id)
    return ids


def pending() -> list[dict]:
    return db.query("SELECT * FROM llm_batches WHERE status='läuft' ORDER BY id")


def status(batch_id: str) -> dict:
    b = client().messages.batches.retrieve(batch_id)
    rc = b.request_counts
    return {"status": b.processing_status, "processing": rc.processing, "succeeded": rc.succeeded,
            "errored": rc.errored, "canceled": rc.canceled, "expired": rc.expired}


def results(batch_id: str):
    """-> (file_id, Ergebnis|None, usage|None, Fehlertext|None)"""
    for r in client().messages.batches.results(batch_id):
        fid = int(r.custom_id)
        if r.result.type == "succeeded":
            msg = r.result.message
            if msg.stop_reason in ("refusal", "max_tokens"):
                yield fid, None, usage_of(msg), f"stop_reason={msg.stop_reason}"
                continue
            text = next((b.text for b in msg.content if b.type == "text"), "")
            try:
                yield fid, normalize(json.loads(text)), usage_of(msg), None
            except (ValueError, TypeError) as exc:
                yield fid, None, usage_of(msg), f"Ungültige Antwort: {exc}"
        else:
            yield fid, None, None, r.result.type


def cancel(batch_id: str) -> None:
    try:
        client().messages.batches.cancel(batch_id)
    finally:
        with db.tx() as c:
            c.execute("UPDATE llm_batches SET status='abgebrochen', finished_at=? WHERE batch_id=?", (db.now(), batch_id))


def mark_done(batch_id: str, message: str = "") -> None:
    with db.tx() as c:
        c.execute("UPDATE llm_batches SET status='fertig', finished_at=?, message=? WHERE batch_id=?", (db.now(), message, batch_id))
