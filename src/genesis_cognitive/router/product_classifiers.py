"""Product-level classifiers — read vs mutation scoring (Capa 1)."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_framework import Agent, ChatOptions, Message

from genesis_cognitive.router.domain_classifier import DomainScore, _RESPONSE_FORMAT, _run_classifier, _run_classifier_timed
from genesis_cognitive.telemetry.llm_call_timer import LlmCallRecord


class ProductReadClassifier:
    """Scores whether the user wants to READ/QUERY a personal product datum."""

    def __init__(self, agent: Agent[Any]) -> None:
        self._agent = agent

    async def classify(self, raw_text: str, context_summary: str) -> DomainScore:
        prompt = (
            f"Contexto del cliente: {context_summary}\n"
            f"Mensaje del usuario: {raw_text}\n\n"
            "Responde con un score de 0.0 a 1.0."
        )
        return await _run_classifier(self._agent, prompt)


class ProductMutationClassifier:
    """Scores whether the user wants to EXECUTE an operation that changes state."""

    def __init__(self, agent: Agent[Any]) -> None:
        self._agent = agent

    async def classify(self, raw_text: str, context_summary: str) -> DomainScore:
        prompt = (
            f"Contexto del cliente: {context_summary}\n"
            f"Mensaje del usuario: {raw_text}\n\n"
            "Responde con un score de 0.0 a 1.0."
        )
        return await _run_classifier(self._agent, prompt)


async def classify_product_intent(
    raw_text: str,
    context_summary: str,
    read_classifier: ProductReadClassifier,
    mutation_classifier: ProductMutationClassifier,
) -> tuple[DomainScore, DomainScore]:
    """Run read and mutation classifiers in parallel."""
    read_score, mutation_score = await asyncio.gather(
        read_classifier.classify(raw_text, context_summary),
        mutation_classifier.classify(raw_text, context_summary),
    )
    return read_score, mutation_score


async def classify_product_intent_timed(
    raw_text: str,
    context_summary: str,
    read_classifier: ProductReadClassifier,
    mutation_classifier: ProductMutationClassifier,
    deployment: str = "gpt-4o-mini",
) -> tuple[DomainScore, DomainScore, list[LlmCallRecord]]:
    """Run read and mutation classifiers in parallel with per-call timing.

    Returns (read_score, mutation_score, call_records).
    """
    prompt = (
        f"Contexto del cliente: {context_summary}\n"
        f"Mensaje del usuario: {raw_text}\n\n"
        "Responde con un score de 0.0 a 1.0."
    )

    results = await asyncio.gather(
        _run_classifier_timed(read_classifier._agent, prompt, "capa1.read", deployment),
        _run_classifier_timed(mutation_classifier._agent, prompt, "capa1.mutation", deployment),
    )

    read_score, read_rec = results[0]
    mutation_score, mutation_rec = results[1]

    return read_score, mutation_score, [read_rec, mutation_rec]
