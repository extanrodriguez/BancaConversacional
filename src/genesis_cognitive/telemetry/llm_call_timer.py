"""LLM call timing — wraps individual Azure OpenAI calls with telemetry.

Each call record contains:
  name:              stable identifier (e.g. "capa0.own_product", "proposer")
  duration_ms:       wall-clock time for the call
  deployment:        Azure model deployment name
  ok:                True if call succeeded
  error_type:        None | "Timeout" | "RateLimit" | "Auth" | "Other"
  prompt_tokens:     int | None
  completion_tokens: int | None

Usage:
    from genesis_cognitive.telemetry.llm_call_timer import time_llm_call, LlmCallRecord

    record, result = await time_llm_call(
        name="capa0.own_product",
        coro=agent.run(messages, options=options),
        deployment="gpt-4o-mini",
    )
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")

_logger = logging.getLogger("genesis.latency")

# Default threshold for SLOW_CALL warning (ms)
_SLOW_CALL_MS_DEFAULT = 3000


def _get_slow_call_threshold() -> int:
    """Read GENESIS_SLOW_CALL_MS from env (default 3000)."""
    try:
        return int(os.getenv("GENESIS_SLOW_CALL_MS", str(_SLOW_CALL_MS_DEFAULT)))
    except (ValueError, TypeError):
        return _SLOW_CALL_MS_DEFAULT


@dataclass(frozen=True)
class LlmCallRecord:
    """Timing record for a single LLM inference call."""

    name: str
    duration_ms: int
    deployment: str
    ok: bool
    error_type: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for decision_trace inclusion."""
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "deployment": self.deployment,
            "ok": self.ok,
            "error_type": self.error_type,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


def _classify_error(exc: Exception) -> str:
    """Classify an exception into a stable error_type string."""
    exc_type = type(exc).__name__.lower()
    exc_msg = str(exc).lower()

    if "timeout" in exc_type or "timeout" in exc_msg:
        return "Timeout"
    if "ratelimit" in exc_type or "429" in exc_msg or "rate" in exc_msg:
        return "RateLimit"
    if "auth" in exc_type or "401" in exc_msg or "403" in exc_msg or "credential" in exc_msg:
        return "Auth"
    return "Other"


async def time_llm_call(
    *,
    name: str,
    coro: Any,  # Awaitable[T]
    deployment: str = "gpt-4o-mini",
) -> tuple[LlmCallRecord, Any]:
    """Time a single LLM call coroutine.

    Returns (record, result). On failure, result is None and record.ok=False.
    Raises the original exception after recording timing.
    """
    start = time.perf_counter()
    try:
        result = await coro
        elapsed_ms = round((time.perf_counter() - start) * 1000)

        # Try to extract token usage if available
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        if hasattr(result, "usage") and result.usage is not None:
            usage = result.usage
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)

        record = LlmCallRecord(
            name=name,
            duration_ms=elapsed_ms,
            deployment=deployment,
            ok=True,
            error_type=None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        # Log SLOW_CALL if threshold exceeded
        threshold = _get_slow_call_threshold()
        if elapsed_ms >= threshold:
            _logger.warning(
                "SLOW_CALL name=%s duration_ms=%d deployment=%s",
                name,
                elapsed_ms,
                deployment,
            )

        return record, result

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        error_type = _classify_error(exc)

        record = LlmCallRecord(
            name=name,
            duration_ms=elapsed_ms,
            deployment=deployment,
            ok=False,
            error_type=error_type,
            prompt_tokens=None,
            completion_tokens=None,
        )

        # Log SLOW_CALL even on failure
        threshold = _get_slow_call_threshold()
        if elapsed_ms >= threshold:
            _logger.warning(
                "SLOW_CALL name=%s duration_ms=%d deployment=%s error_type=%s",
                name,
                elapsed_ms,
                deployment,
                error_type,
            )

        raise
