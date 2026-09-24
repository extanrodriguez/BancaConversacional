"""ModelInputBuilder — projects AssembledContext into a safe model envelope."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from genesis_cognitive.context.context_assembler import AssembledContext
from genesis_cognitive.enums import SelectedRoute

# ---------------------------------------------------------------------------
# Projected sub-models (whitelist-only, no sensitive data)
# ---------------------------------------------------------------------------


class ProjectedTurn(BaseModel):
    """A single conversational turn visible to the model."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: str
    summary: str


class ProjectedProduct(BaseModel):
    """A portfolio product visible to the model — no balances."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    product_ref: str
    product_type: str
    label: str | None
    alias: str | None
    currency: str
    operational_state: str
    # Proyección contextual v1 (sin saldos ni PII completa)
    masked_label: str | None = None
    last_four: str | None = None
    applicable_fields: tuple[str, ...] = ()
    classification: str = "known"  # known | unknown_commercial
    mapping_provenance: str = "core_description"


class ProjectedPendingAction(BaseModel):
    """Pending clarification action from a previous turn — projected for model context."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent_id: str
    capability_candidate: str | None
    selected_route: str
    detected_entities: dict[str, str | None]
    missing_requirements: list[str]
    suggested_question: str
    original_question: str = ""
    query_spec: dict[str, str] = Field(default_factory=dict)


class ProjectedPendingOperation(BaseModel):
    """Pending operation projection — currently null per canonical contract."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    pending_operation: None = None
    last_operation_request: None = None
    last_operation_result: None = None


class ProjectedCapability(BaseModel):
    """A capability manifest projected for model selection."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    capability_id: str
    intent_ids: tuple[str, ...]
    capability_candidate: str | None
    domain: str
    description: str
    selected_route: SelectedRoute
    required_entities: tuple[str, ...]
    optional_entities: tuple[str, ...]
    min_required_entities: int = Field(ge=0)
    output_contract: str
    support_level: str
    requires_confirmation: bool
    requires_idempotency: bool


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class ProjectedPendingTask(BaseModel):
    """Tarea pendiente multi-campo proyectada (sin saldos)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    task_id: str
    object: str
    fields: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    original_question: str = ""
    display_order: tuple[str, ...] = ()


class ProjectedConversationMemory(BaseModel):
    """Memoria conversacional acotada para el modelo (sin saldos vigentes)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    pending_tasks: tuple[ProjectedPendingTask, ...] = ()
    compare_set: tuple[str, ...] = ()
    product_focus_kind: str | None = None
    product_focus_id: str | None = None
    last_knowledge_topic: str | None = None
    catalog_personal_map_keys: tuple[str, ...] = ()
    # Metadatos de contexto (sin montos)
    context_source: str | None = None
    snapshot_revision: str | None = None
    portfolio_completeness: str = "unknown"  # known_complete | lab_fallback | unknown
    projection_version: str = "contextual-v1"


class ModelInputEnvelope(BaseModel):
    """Safe, serializable input for the cognitive model.

    Contains ONLY data the model needs to interpret the turn.
    Excludes all identity fields, credentials, balances, and timestamps.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    raw_text: str
    language: str
    locale: str
    conversation: tuple[ProjectedTurn, ...]
    portfolio: tuple[ProjectedProduct, ...]
    pending_operation: ProjectedPendingOperation
    effective_capabilities: tuple[ProjectedCapability, ...]
    pending_action: ProjectedPendingAction | None = None
    domain_hint: str | None = None  # "own_product" | "business" | "ambiguous" | None
    conversation_memory: ProjectedConversationMemory | None = None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ModelInputBuilder:
    """Transforms AssembledContext into a safe ModelInputEnvelope.

    Applies explicit whitelists to exclude sensitive data.
    Does NOT interpret raw_text, infer intent, or filter by keywords.
    """

    def build(self, assembled: AssembledContext) -> ModelInputEnvelope:
        """Project assembled context into a model-safe envelope.

        The projection is deterministic: same input always produces same output.
        """
        # Conversation turns — whitelist: role, summary, original order
        conversation = tuple(
            ProjectedTurn(role=turn.role.value, summary=turn.summary)
            for turn in assembled.conversation.recent_turns
        )

        # Portfolio — whitelist: refs/tipos/alias/campos aplicables (sin saldos)
        portfolio = tuple(
            _project_one_product(p)
            for p in assembled.portfolio.snapshot.products
        )

        # Pending operation — whitelist per canonical contract
        pending = ProjectedPendingOperation(
            pending_operation=assembled.pending_operations.pending_operation,
            last_operation_request=assembled.pending_operations.last_operation_request,
            last_operation_result=assembled.pending_operations.last_operation_result,
        )

        # Capabilities — whitelist for model selection
        capabilities = tuple(
            ProjectedCapability(
                capability_id=m.capability_id,
                intent_ids=m.intent_ids,
                capability_candidate=m.capability_candidate,
                domain=m.domain,
                description=m.description,
                selected_route=m.selected_route,
                required_entities=m.required_entities,
                optional_entities=m.optional_entities,
                min_required_entities=m.validation_rules.min_required_entities,
                output_contract=m.output_contract,
                support_level=m.support_level.value,
                requires_confirmation=m.orchestrator_requirements.requires_confirmation,
                requires_idempotency=m.orchestrator_requirements.requires_idempotency,
            )
            for m in assembled.effective_capabilities
        )

        return ModelInputEnvelope(
            raw_text=assembled.raw_text,
            language=assembled.language,
            locale=assembled.locale,
            conversation=conversation,
            portfolio=portfolio,
            pending_operation=pending,
            effective_capabilities=capabilities,
        )


def _project_one_product(p: object) -> ProjectedProduct:
    from genesis_cognitive.brain.semantic_field_catalog import applicable_fields_for_type
    from genesis_cognitive.context.product_display import display_label

    alias = getattr(p, "alias", None)
    pid = str(getattr(p, "product_id", getattr(p, "product_ref", "")) or "")
    ptype = str(getattr(p, "product_type", "") or "")
    status = getattr(p, "status", getattr(p, "operational_state", "active"))
    if hasattr(status, "value"):
        status = status.value
    try:
        masked = display_label(p)  # type: ignore[arg-type]
    except Exception:
        masked = alias or pid
    last4 = getattr(p, "last_four", None)
    if not last4 and isinstance(getattr(p, "card_mask", None), str):
        digits = "".join(ch for ch in p.card_mask if ch.isdigit())
        last4 = digits[-4:] if digits else None
    return ProjectedProduct(
        product_ref=pid,
        product_type=ptype,
        label=alias,
        alias=alias,
        currency=str(getattr(p, "currency", "") or ""),
        operational_state=str(status),
        masked_label=masked,
        last_four=str(last4) if last4 else None,
        applicable_fields=applicable_fields_for_type(ptype),
        classification="known" if alias else "unknown_commercial",
        mapping_provenance="core_description",
    )


def project_conversation_memory(
    session: object,
    *,
    context_source: str | None = None,
    snapshot_revision: str | None = None,
    portfolio_completeness: str = "unknown",
) -> ProjectedConversationMemory:
    """Proyecta pendientes/foco/compare_set sin saldos ni PII sensible."""
    pts: list[ProjectedPendingTask] = []
    for pt in list(getattr(session, "pending_tasks", None) or []):
        if not isinstance(pt, dict):
            continue
        pts.append(ProjectedPendingTask(
            task_id=str(pt.get("task_id") or pt.get("id") or ""),
            object=str(pt.get("object") or ""),
            fields=tuple(str(x) for x in (pt.get("fields") or [])),
            exclusions=tuple(str(x) for x in (pt.get("exclusions") or [])),
            original_question=str(pt.get("original_question") or ""),
            display_order=tuple(str(x) for x in (pt.get("display_order") or [])),
        ))
    pf = getattr(session, "product_focus", None)
    cmap = getattr(session, "catalog_personal_map", None) or {}
    return ProjectedConversationMemory(
        pending_tasks=tuple(pts),
        compare_set=tuple(str(x) for x in (getattr(session, "compare_set", None) or [])),
        product_focus_kind=getattr(pf, "kind", None) if pf else None,
        product_focus_id=getattr(pf, "product_id", None) if pf else None,
        last_knowledge_topic=getattr(session, "last_knowledge_topic", None),
        catalog_personal_map_keys=tuple(sorted(str(k) for k in cmap.keys())),
        context_source=context_source,
        snapshot_revision=snapshot_revision,
        portfolio_completeness=portfolio_completeness,
        projection_version="contextual-v1",
    )
