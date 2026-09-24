"""Cache de respuestas Foundry KB (topic|intent) — ahorro de latencia/costo.

Activo solo con GENESIS_FOUNDRY_CACHE=1. No cachea personal ni clarificaciones.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any


def cache_enabled() -> bool:
    return os.getenv("GENESIS_FOUNDRY_CACHE", "").strip().lower() in ("1", "true", "yes", "on")


def _ttl_s() -> int:
    try:
        return max(60, int(os.getenv("GENESIS_FOUNDRY_CACHE_TTL_S", "86400").strip() or "86400"))
    except ValueError:
        return 86400


def _cache_dir() -> Path:
    raw = os.getenv("GENESIS_FOUNDRY_CACHE_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "data" / "cache" / "foundry_kb"


def normalize_question(question: str) -> str:
    q = (question or "").strip().lower()
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"[¿?¡!.,;:]+", "", q)
    return q.strip()


def make_cache_key(question: str, *, topic: str | None = None) -> str:
    base = normalize_question(question)
    topic_n = re.sub(r"\s+", " ", (topic or "").strip().lower())
    payload = f"{topic_n}|{base}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_cached(question: str, *, topic: str | None = None) -> dict[str, Any] | None:
    if not cache_enabled():
        return None
    key = make_cache_key(question, topic=topic)
    path = _cache_dir() / f"{key}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expires = float(data.get("expires_at") or 0)
        if expires and time.time() > expires:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        answer = (data.get("answer") or "").strip()
        if not answer:
            return None
        return {
            "ok": True,
            "answer": answer,
            "status": "FOUNDRY_KB_CACHE_HIT",
            "agent": data.get("agent"),
            "version": data.get("version"),
            "cache_key": key,
        }
    except Exception:
        return None


def put_cached(
    question: str,
    result: dict[str, Any],
    *,
    topic: str | None = None,
) -> None:
    if not cache_enabled():
        return
    if not result.get("ok"):
        return
    status = str(result.get("status") or "")
    if status not in ("FOUNDRY_KB_ANSWERED", "FOUNDRY_KB_CACHE_HIT"):
        return
    answer = (result.get("answer") or "").strip()
    if not answer:
        return
    low = answer.lower()
    # No cachear basura / placeholders / saludos
    if any(
        s in low
        for s in (
            "kb_ambiguity",
            "en qué puedo ayudarte",
            "en que puedo ayudarte",
            "no encontré información específica",
            "no encontre informacion especifica",
        )
    ):
        return
    key = make_cache_key(question, topic=topic)
    directory = _cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "key": key,
            "topic": topic,
            "question_norm": normalize_question(question),
            "answer": answer,
            "agent": result.get("agent"),
            "version": result.get("version"),
            "created_at": time.time(),
            "expires_at": time.time() + _ttl_s(),
        }
        (directory / f"{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        return
