"""TurnPlan — plan semántico multi-tarea (V3).

Conserva IntentPacket como adaptador para casos simples.
El LLM no emite IDs personales autoritativos: el resolutor servidor valida.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from genesis_cognitive.brain.intent_types import IntentPacket

ScopeDomain = Literal["personal", "catalog", "institutional", "process", "none"]
Cardinality = Literal["single", "all", "compare"]
TaskStatus = Literal["ready", "needs_clarification", "unsupported", "error"]
Transition = Literal[
    "none",
    "selection",
    "correction",
    "topic_change",
    "compare_expand",
    "continue",
]


@dataclass
class PlanTask:
    """Una unidad ejecutable del turno."""

    id: str
    domain: ScopeDomain
    action: str  # read_field | list | define | compare | clarify | refuse | …
    object: str  # account | loan | credit_card | bank | none | …
    fields: list[str] = field(default_factory=list)
    scope: ScopeDomain = "personal"
    cardinality: Cardinality = "single"
    entity_ref: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    unresolved_slots: list[str] = field(default_factory=list)
    status: TaskStatus = "ready"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TurnPlan:
    """Plan interno del turno — múltiples tareas ordenadas."""

    tasks: list[PlanTask] = field(default_factory=list)
    transition: Transition = "none"
    source: str = "adapter"  # adapter | azure | heuristic
    correlation_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "transition": self.transition,
            "source": self.source,
            "correlation_hint": self.correlation_hint,
        }

    @property
    def primary(self) -> PlanTask | None:
        return self.tasks[0] if self.tasks else None


def intent_packet_to_turn_plan(packet: IntentPacket) -> TurnPlan:
    """Adaptador temporal: un IntentPacket → TurnPlan de una tarea."""
    family = (packet.family or "clarify").lower()
    field = (packet.field or "").lower()
    # knowledge + process (fallecidos, guías) → dominio process, no glosario
    if family in ("knowledge",) and field in ("process", "procedure", "howto"):
        domain: ScopeDomain = "process"
        action = "process"
    elif family in ("knowledge",):
        domain = "institutional"
        action = "define"
    elif family in ("process",):
        domain = "process"
        action = "process"
    elif family in ("personal",):
        domain = "personal"
        action = "read_field"
    elif family in ("greeting", "chitchat"):
        domain = "none"
        action = "chitchat"
    else:
        domain = "none"
        action = "clarify"

    card: Cardinality = "single"
    if packet.scope == "all":
        card = "all"
    elif packet.scope == "compare":
        card = "compare"

    status: TaskStatus = "ready"
    unresolved: list[str] = []
    if packet.needs_clarification:
        status = "needs_clarification"
        unresolved = ["entity_ref"]

    filters: dict[str, Any] = {}
    if domain == "process" and packet.rewritten_question:
        filters["query"] = packet.rewritten_question

    task = PlanTask(
        id="t1",
        domain=domain,
        action=action,
        object=(packet.product or "none"),
        fields=[packet.field] if packet.field else [],
        scope=domain,
        cardinality=card,
        entity_ref=packet.product_hint_digits,
        unresolved_slots=unresolved,
        status=status,
        filters=filters,
    )
    return TurnPlan(tasks=[task], transition="none", source=packet.source or "adapter")


def validate_turn_plan(plan: TurnPlan) -> list[str]:
    """Validación semántica: IDs, dependencias y ciclos de cualquier longitud (DFS)."""
    errors: list[str] = []
    ids = [t.id for t in plan.tasks]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_task_ids")
    id_set = set(ids)
    adj: dict[str, list[str]] = {t.id: list(t.depends_on) for t in plan.tasks}
    for t in plan.tasks:
        for dep in t.depends_on:
            if dep not in id_set:
                errors.append(f"missing_dependency:{t.id}->{dep}")
            if dep == t.id:
                errors.append(f"self_dependency:{t.id}")
        if t.domain == "personal" and t.action == "read_field" and not t.fields and t.status == "ready":
            errors.append(f"personal_read_without_field:{t.id}")

    visited: set[str] = set()
    in_stack: set[str] = set()

    def dfs(node: str) -> None:
        if node in in_stack:
            errors.append(f"cycle_involving:{node}")
            return
        if node in visited:
            return
        in_stack.add(node)
        for neighbor in adj.get(node, []):
            if neighbor in id_set:
                dfs(neighbor)
        in_stack.discard(node)
        visited.add(node)

    for tid in ids:
        dfs(tid)
    return errors


class InvalidTurnPlanError(ValueError):
    """Plan semánticamente inválido — no debe ejecutarse."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("invalid_turn_plan:" + ",".join(errors[:8]))
