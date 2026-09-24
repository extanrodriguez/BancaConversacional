"""Tipos del Intent Packet (salida del cerebro Azure)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IntentPacket:
    """Intención estructurada — Azure entiende; el ejecutor no improvisa hechos."""

    family: str  # personal | knowledge | process | ood | greeting | chitchat | clarify
    product: str  # account | credit_card | debit_card | loan | term_deposit | mixed | none
    field: str  # ver grounded_executor FACT_* + presence|correction|thanks|ack|smalltalk
    scope: str = "single"  # single | all | compare
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_question: str | None = None
    product_hint_digits: str | None = None
    rewritten_question: str | None = None
    rationale: str | None = None
    source: str = "azure"  # azure | heuristic | fallback

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroundedResult:
    """Respuesta grounded lista para el canal."""

    status: str  # VALID_CONTRACT | CLARIFICATION_REQUIRED | NON_OPERATIONAL | UNSUPPORTED
    text: str
    intent_id: str
    account_ref: str | None = None
    suggestions: list[dict] | None = None
    options: list[dict] | None = None
    actions: list[dict] = field(default_factory=list)
    route: str = "personal"  # personal | knowledge | process | none
    knowledge_question: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)
