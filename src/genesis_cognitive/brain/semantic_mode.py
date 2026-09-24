"""Selector de ruta semántica V4.

GENESIS_SEMANTIC_MODE=legacy|azure_plan

- legacy: comportamiento V3.1 (heuristic_multi primero).
- azure_plan: interpretación canónica vía resolve_full → TurnPlan → execute_turn_plan.
"""

from __future__ import annotations

import os
from typing import Literal

SemanticMode = Literal["legacy", "azure_plan"]


def get_semantic_mode() -> SemanticMode:
    raw = (os.getenv("GENESIS_SEMANTIC_MODE") or "legacy").strip().lower()
    if raw in ("azure_plan", "azure", "v4", "semantic"):
        return "azure_plan"
    return "legacy"


def is_azure_plan_mode() -> bool:
    return get_semantic_mode() == "azure_plan"


def azure_deployment_name(default: str = "gpt-4o-mini") -> str:
    """Deployment efectivo — no hardcodear en telemetría."""
    return (
        os.getenv("GENESIS_AZURE_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or os.getenv("GENESIS_AZURE_MODEL")
        or default
    ).strip()


def azure_supports_custom_temperature(deployment: str | None = None) -> bool:
    """Algunos deployments (p. ej. gpt-6-astra) solo aceptan temperature por defecto."""
    name = (deployment or azure_deployment_name()).strip().lower()
    if not name:
        return True
    if "gpt-6" in name or "astra" in name:
        return False
    if name.startswith(("o1", "o3")) or "reasoner" in name:
        return False
    override = (os.getenv("GENESIS_AZURE_TEMPERATURE_MODE") or "").strip().lower()
    if override in ("default_only", "fixed", "omit"):
        return False
    return True


def azure_chat_options(
    *,
    response_format: object | None = None,
    temperature: float = 0.0,
    deployment: str | None = None,
) -> dict:
    """Kwargs seguros para ChatOptions según el deployment efectivo."""
    opts: dict = {}
    if response_format is not None:
        opts["response_format"] = response_format
    if azure_supports_custom_temperature(deployment):
        opts["temperature"] = temperature
    return opts
