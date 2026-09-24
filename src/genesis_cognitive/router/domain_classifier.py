"""Domain classifiers — parallel scoring for own_product, business, ood."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from agent_framework import Agent, ChatOptions, Message

from genesis_cognitive.telemetry.llm_call_timer import LlmCallRecord, time_llm_call


@dataclass(frozen=True)
class DomainScore:
    """Score from a domain classifier."""

    score: float  # 0.0 to 1.0
    rationale: str | None = None


# JSON Schema for classifier output (strict)
_SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score"],
    "properties": {
        "score": {"type": "number"},
    },
}

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "DomainScore",
        "strict": True,
        "schema": _SCORE_SCHEMA,
    },
}


class OwnProductClassifier:
    """Classifies whether the user asks about their own product/portfolio data."""

    def __init__(self, agent: Agent[Any]) -> None:
        self._agent = agent

    async def classify(self, raw_text: str, context_summary: str) -> DomainScore:
        prompt = (
            f"Contexto del cliente: {context_summary}\n"
            f"Mensaje del usuario: {raw_text}\n\n"
            "Responde con un score de 0.0 a 1.0."
        )
        return await _run_classifier(self._agent, prompt)


class BusinessClassifier:
    """Classifies whether the user asks about general bank info/catalog."""

    def __init__(self, agent: Agent[Any]) -> None:
        self._agent = agent

    async def classify(self, raw_text: str, context_summary: str) -> DomainScore:
        prompt = (
            f"Contexto del cliente: {context_summary}\n"
            f"Mensaje del usuario: {raw_text}\n\n"
            "Responde con un score de 0.0 a 1.0."
        )
        return await _run_classifier(self._agent, prompt)


class OodClassifier:
    """Classifies whether the request is functional but non-banking (out of domain)."""

    def __init__(self, agent: Agent[Any]) -> None:
        self._agent = agent

    async def classify(self, raw_text: str, context_summary: str) -> DomainScore:
        prompt = (
            f"Contexto del cliente: {context_summary}\n"
            f"Mensaje del usuario: {raw_text}\n\n"
            "Responde con un score de 0.0 a 1.0."
        )
        return await _run_classifier(self._agent, prompt)


async def _run_classifier(agent: Agent[Any], user_content: str) -> DomainScore:
    """Run a classifier agent and parse the score."""
    messages: list[Message] = [
        Message(role="user", contents=[user_content]),
    ]
    from genesis_cognitive.brain.semantic_mode import azure_chat_options

    options = ChatOptions(**azure_chat_options(response_format=_RESPONSE_FORMAT, temperature=0))

    try:
        response = await agent.run(messages, options=options)
    except Exception:
        return DomainScore(score=0.0, rationale="classifier_error")

    value = response.value
    if value is None:
        return DomainScore(score=0.0, rationale="null_response")

    if isinstance(value, dict):
        raw_score = value.get("score", 0.0)
        score = max(0.0, min(1.0, float(raw_score)))
        return DomainScore(score=score)

    return DomainScore(score=0.0, rationale="invalid_format")


async def _run_classifier_timed(
    agent: Agent[Any],
    user_content: str,
    call_name: str,
    deployment: str = "gpt-4o-mini",
) -> tuple[DomainScore, LlmCallRecord]:
    """Run a classifier agent with timing. Returns (score, call_record)."""
    import time as _time_mod

    messages: list[Message] = [
        Message(role="user", contents=[user_content]),
    ]
    from genesis_cognitive.brain.semantic_mode import azure_chat_options

    options = ChatOptions(
        **azure_chat_options(response_format=_RESPONSE_FORMAT, temperature=0, deployment=deployment)
    )

    start = _time_mod.perf_counter()
    try:
        record, response = await time_llm_call(
            name=call_name,
            coro=agent.run(messages, options=options),
            deployment=deployment,
        )
    except Exception:
        elapsed_ms = round((_time_mod.perf_counter() - start) * 1000)
        from genesis_cognitive.telemetry.llm_call_timer import _classify_error
        import sys
        exc = sys.exc_info()[1]
        error_type = _classify_error(exc) if exc else "Other"
        fail_record = LlmCallRecord(
            name=call_name, duration_ms=elapsed_ms, deployment=deployment,
            ok=False, error_type=error_type,
        )
        return DomainScore(score=0.0, rationale="classifier_error"), fail_record

    value = response.value
    if value is None:
        return DomainScore(score=0.0, rationale="null_response"), record

    if isinstance(value, dict):
        raw_score = value.get("score", 0.0)
        score = max(0.0, min(1.0, float(raw_score)))
        return DomainScore(score=score), record

    return DomainScore(score=0.0, rationale="invalid_format"), record


async def classify_domain(
    raw_text: str,
    context_summary: str,
    own_classifier: OwnProductClassifier,
    business_classifier: BusinessClassifier,
    ood_classifier: OodClassifier,
) -> tuple[DomainScore, DomainScore, DomainScore]:
    """Run all three classifiers in parallel and return scores."""
    own, biz, ood = await asyncio.gather(
        own_classifier.classify(raw_text, context_summary),
        business_classifier.classify(raw_text, context_summary),
        ood_classifier.classify(raw_text, context_summary),
    )
    return own, biz, ood


async def classify_domain_timed(
    raw_text: str,
    context_summary: str,
    own_classifier: OwnProductClassifier,
    business_classifier: BusinessClassifier,
    ood_classifier: OodClassifier,
    deployment: str = "gpt-4o-mini",
) -> tuple[DomainScore, DomainScore, DomainScore, list[LlmCallRecord]]:
    """Run all three classifiers in parallel with per-call timing.

    Returns (own_score, biz_score, ood_score, call_records).
    """
    prompt_own = (
        f"Contexto del cliente: {context_summary}\n"
        f"Mensaje del usuario: {raw_text}\n\n"
        "Responde con un score de 0.0 a 1.0."
    )
    prompt_biz = prompt_own  # same prompt, different agent instructions
    prompt_ood = prompt_own

    results = await asyncio.gather(
        _run_classifier_timed(own_classifier._agent, prompt_own, "capa0.own_product", deployment),
        _run_classifier_timed(business_classifier._agent, prompt_biz, "capa0.business", deployment),
        _run_classifier_timed(ood_classifier._agent, prompt_ood, "capa0.ood", deployment),
    )

    own_score, own_rec = results[0]
    biz_score, biz_rec = results[1]
    ood_score, ood_rec = results[2]

    return own_score, biz_score, ood_score, [own_rec, biz_rec, ood_rec]
