"""CapabilityCatalog — validates interpretations against the closed catalog."""

from genesis_cognitive.decision.capability_types import (
    AppRequirements,
    AuthenticationRequirements,
    CapabilityManifest,
    CapabilityQueryContext,
    CapabilityValidationRules,
    OrchestratorRequirements,
)
from genesis_cognitive.decision.types import SemanticAction, TurnInterpretation
from genesis_cognitive.enums import (
    InterpretationMode,
    LifecycleStatus,
    SelectedRoute,
    SupportLevel,
)
from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError

# Allowed entity names across the system
_ALL_ALLOWED_ENTITIES = frozenset(
    [
        "account_ref",
        "source_account_ref",
        "destination_account_ref",
        "amount",
        "currency",
        "knowledge_topic",
    ]
)


def _build_canonical_manifests() -> tuple[CapabilityManifest, ...]:
    """Build the 7 canonical manifests."""
    base_orch = OrchestratorRequirements(
        required_capabilities=(),
        requires_confirmation=False,
        requires_idempotency=False,
        max_execution_time_seconds=None,
    )
    base_app = AppRequirements(
        allowed_channels=(),
        required_capabilities=(),
        show_confirmation_ui=False,
        show_cancellation_ui=False,
        show_timer=False,
    )
    base_auth = AuthenticationRequirements(
        requires_authenticated=True, minimum_authentication_level=None, requires_elevated=False
    )
    base_rules = CapabilityValidationRules(
        min_required_entities=0, all_required_entities_present=True
    )

    return (
        CapabilityManifest(
            capability_id="business-knowledge",
            intent_ids=("BUSINESS_KNOWLEDGE_QUERY",),
            capability_candidate="BUSINESS_KNOWLEDGE",
            domain="BUSINESS_KNOWLEDGE",
            description="Consultas de conocimiento de negocio",
            required_entities=(),
            optional_entities=("knowledge_topic",),
            skill_or_specialist=None,
            output_contract="KnowledgeResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.BUSINESS_RAG,
            validation_rules=base_rules,
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="portfolio-list",
            intent_ids=("PORTFOLIO_LIST",),
            capability_candidate="PORTFOLIO_LIST",
            domain="PORTFOLIO",
            description="Lista de productos del cliente",
            required_entities=(),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="PortfolioResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.PORTFOLIO_QUERY,
            validation_rules=base_rules,
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="account-balance",
            intent_ids=("ACCOUNT_BALANCE_READ",),
            capability_candidate="ACCOUNT_BALANCE",
            domain="ACCOUNTS",
            description="Consulta de saldo de cuenta",
            required_entities=("account_ref",),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="BalanceResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.PERSONAL_READ,
            validation_rules=CapabilityValidationRules(
                min_required_entities=1, all_required_entities_present=True
            ),
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="account-movements",
            intent_ids=("ACCOUNT_MOVEMENTS_READ",),
            capability_candidate="ACCOUNT_MOVEMENTS",
            domain="ACCOUNTS",
            description="Consulta de movimientos de cuenta",
            required_entities=("account_ref",),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="MovementsResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.PERSONAL_READ,
            validation_rules=CapabilityValidationRules(
                min_required_entities=1, all_required_entities_present=True
            ),
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="loan-read",
            intent_ids=("LOAN_DETAIL_READ",),
            capability_candidate="LOAN_DETAIL",
            domain="LOANS",
            description="Consulta de detalle de prestamo del cliente (cuota, tasa, capital, mora, proxima fecha)",
            required_entities=("account_ref",),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="LoanDetailResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.PERSONAL_READ,
            validation_rules=CapabilityValidationRules(
                min_required_entities=1, all_required_entities_present=True
            ),
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="credit-card-read",
            intent_ids=("CREDIT_CARD_DETAIL_READ",),
            capability_candidate="CREDIT_CARD_DETAIL",
            domain="CREDIT_CARD",
            description="Consulta de tarjeta de credito del cliente (disponible, limite, corte, pago minimo, puntos)",
            required_entities=("account_ref",),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="CardDetailResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.PERSONAL_READ,
            validation_rules=CapabilityValidationRules(
                min_required_entities=1, all_required_entities_present=True
            ),
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="term-deposit-read",
            intent_ids=("TERM_DEPOSIT_DETAIL_READ",),
            capability_candidate="TERM_DEPOSIT_DETAIL",
            domain="INVESTMENTS",
            description="Consulta de deposito a plazo del cliente (monto, tasa, vencimiento, intereses)",
            required_entities=("account_ref",),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="TermDepositDetailResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.PERSONAL_READ,
            validation_rules=CapabilityValidationRules(
                min_required_entities=1, all_required_entities_present=True
            ),
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="transfer-own-accounts",
            intent_ids=("TRANSFER_BETWEEN_OWN_ACCOUNTS",),
            capability_candidate="TRANSFER",
            domain="TRANSFERS",
            description="Transferencia entre cuentas propias",
            required_entities=(
                "source_account_ref",
                "destination_account_ref",
                "amount",
                "currency",
            ),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="TransferContractCandidate",
            orchestrator_requirements=OrchestratorRequirements(
                required_capabilities=("core.transfer",),
                requires_confirmation=True,
                requires_idempotency=True,
                max_execution_time_seconds=60,
            ),
            app_requirements=AppRequirements(
                allowed_channels=(),
                required_capabilities=(),
                show_confirmation_ui=True,
                show_cancellation_ui=True,
                show_timer=True,
            ),
            auth_requirements=base_auth,
            support_level=SupportLevel.EXECUTABLE,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.TRANSFER_CONTRACT_BUILDER,
            validation_rules=CapabilityValidationRules(
                min_required_entities=4, all_required_entities_present=True
            ),
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="clarification",
            intent_ids=("CLARIFICATION_REQUIRED",),
            capability_candidate=None,
            domain="GENERAL",
            description="Aclaracion de datos faltantes",
            required_entities=(),
            optional_entities=tuple(_ALL_ALLOWED_ENTITIES),
            skill_or_specialist=None,
            output_contract="ClarificationResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.GUIDED,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.CLARIFICATION,
            validation_rules=CapabilityValidationRules(
                min_required_entities=0, all_required_entities_present=False
            ),
            enabled=True,
        ),
        CapabilityManifest(
            capability_id="unsupported",
            intent_ids=("UNKNOWN",),
            capability_candidate=None,
            domain="UNSUPPORTED",
            description="Solicitud no soportada",
            required_entities=(),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="UnsupportedResponse",
            orchestrator_requirements=base_orch,
            app_requirements=base_app,
            auth_requirements=base_auth,
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.UNSUPPORTED,
            validation_rules=CapabilityValidationRules(
                min_required_entities=0, all_required_entities_present=False
            ),
            enabled=True,
        ),
    )


class CapabilityCatalog:
    """Immutable catalog of capabilities for validation."""

    def __init__(
        self,
        manifests: tuple[CapabilityManifest, ...] | None = None,
        *,
        active_feature_flags: frozenset[str] = frozenset(),
        allowed_lifecycle_statuses: frozenset[LifecycleStatus] = frozenset(LifecycleStatus),
        allowed_support_levels: frozenset[SupportLevel] = frozenset(SupportLevel),
        authentication_level_order: tuple[str, ...] = ("basic", "standard", "elevated"),
    ) -> None:
        self._manifests = manifests if manifests is not None else _build_canonical_manifests()
        self._active_flags = active_feature_flags
        self._allowed_lifecycle = allowed_lifecycle_statuses
        self._allowed_support = allowed_support_levels
        self._auth_order = authentication_level_order
        self._by_intent: dict[str, CapabilityManifest] = {}
        self._by_id: dict[str, CapabilityManifest] = {}
        self._by_candidate: dict[str, CapabilityManifest] = {}

        for m in self._manifests:
            if m.capability_id in self._by_id:
                msg = f"Duplicate capability_id: {m.capability_id}"
                raise ValueError(msg)
            self._by_id[m.capability_id] = m

            # Validate entities are within the authorized set
            if not set(m.required_entities) <= _ALL_ALLOWED_ENTITIES:
                raise InvalidModelOutputError()
            if not set(m.optional_entities) <= _ALL_ALLOWED_ENTITIES:
                raise InvalidModelOutputError()

            # Validate no overlap between required and optional
            overlap = set(m.required_entities) & set(m.optional_entities)
            if overlap:
                msg = f"Overlapping required/optional entities in {m.capability_id}"
                raise ValueError(msg)

            # Validate min_required_entities coherence
            required_count = len(m.required_entities)
            minimum = m.validation_rules.min_required_entities
            require_all = m.validation_rules.all_required_entities_present
            if minimum < 0 or minimum > required_count:
                raise InvalidModelOutputError()
            if require_all and minimum != required_count:
                raise InvalidModelOutputError()

            # Validate candidate uniqueness (non-null)
            if m.capability_candidate is not None:
                if m.capability_candidate in self._by_candidate:
                    msg = f"Duplicate capability_candidate: {m.capability_candidate}"
                    raise ValueError(msg)
                self._by_candidate[m.capability_candidate] = m

            for iid in m.intent_ids:
                if iid in self._by_intent:
                    msg = f"Duplicate intent_id across manifests: {iid}"
                    raise ValueError(msg)
                self._by_intent[iid] = m

    def get_manifests(self) -> tuple[CapabilityManifest, ...]:
        return self._manifests

    def get_manifest(self, intent_id: str) -> CapabilityManifest:
        m = self._by_intent.get(intent_id)
        if m is None:
            raise InvalidModelOutputError()
        return m

    def get_domain(self, intent_id: str, capability_candidate: str | None = None) -> str:
        """Get domain for an intent. For CLARIFICATION_REQUIRED, derive from candidate."""
        if intent_id == "CLARIFICATION_REQUIRED":
            if capability_candidate is None:
                return "GENERAL"
            # Find the manifest that owns this candidate
            for m in self._manifests:
                if m.capability_candidate == capability_candidate:
                    return m.domain
            raise InvalidModelOutputError()
        manifest = self._by_intent.get(intent_id)
        if manifest is None:
            raise InvalidModelOutputError()
        if (
            capability_candidate is not None
            and capability_candidate != manifest.capability_candidate
        ):
            raise InvalidModelOutputError()
        return manifest.domain

    def validate_interpretation(self, interpretation: TurnInterpretation) -> None:
        """Validate each action against the catalog."""
        for action in interpretation.actions:
            self._validate_action(action, interpretation.mode)

    def _validate_action(self, action: SemanticAction, mode: InterpretationMode) -> None:
        intent_id = action.intent_id
        manifest = self._by_intent.get(intent_id)
        if manifest is None:
            raise InvalidModelOutputError()

        # Route must match
        if action.selected_route != manifest.selected_route:
            raise InvalidModelOutputError()

        # Capability candidate must match
        if intent_id == "UNKNOWN":
            if action.capability_candidate is not None:
                raise InvalidModelOutputError()
        elif intent_id == "CLARIFICATION_REQUIRED":
            # May have a candidate or null
            if action.capability_candidate is not None:
                # Must match a known candidate from another manifest
                known_candidates = {
                    m.capability_candidate
                    for m in self._manifests
                    if m.capability_candidate is not None
                }
                if action.capability_candidate not in known_candidates:
                    raise InvalidModelOutputError()
        else:
            # Normal intent: candidate must match manifest
            if action.capability_candidate != manifest.capability_candidate:
                raise InvalidModelOutputError()

        # Validate entities
        detected = action.detected_entities
        detected_keys = {k for k, v in detected.model_dump().items() if v is not None}
        allowed = set(manifest.required_entities) | set(manifest.optional_entities)
        if not detected_keys.issubset(allowed) and intent_id != "CLARIFICATION_REQUIRED":
            raise InvalidModelOutputError()

        # Entity cannot be both detected and missing
        for req in action.missing_requirements:
            if req in detected_keys:
                raise InvalidModelOutputError()

        # UNKNOWN specifics
        if intent_id == "UNKNOWN":
            if action.capability_candidate is not None:
                raise InvalidModelOutputError()
            if action.selected_route != SelectedRoute.UNSUPPORTED:
                raise InvalidModelOutputError()

        # CLARIFICATION_REQUIRED must have missing_requirements
        if intent_id == "CLARIFICATION_REQUIRED" and not action.missing_requirements:
            raise InvalidModelOutputError()

        # UNKNOWN must not have entities or missing requirements
        if intent_id == "UNKNOWN":
            if detected_keys:
                raise InvalidModelOutputError()
            if action.missing_requirements:
                raise InvalidModelOutputError()

        # missing_requirements must be subset of required_entities
        if intent_id == "CLARIFICATION_REQUIRED" and action.capability_candidate is not None:
            # Validate against the candidate's manifest
            candidate_manifest = None
            for m in self._manifests:
                if m.capability_candidate == action.capability_candidate:
                    candidate_manifest = m
                    break
            if candidate_manifest:
                valid_missing = set(candidate_manifest.required_entities)
                if not set(action.missing_requirements).issubset(valid_missing):
                    raise InvalidModelOutputError()
                valid_entities = set(candidate_manifest.required_entities) | set(
                    candidate_manifest.optional_entities
                )
                if not detected_keys.issubset(valid_entities):
                    raise InvalidModelOutputError()
        elif intent_id != "CLARIFICATION_REQUIRED" and intent_id != "UNKNOWN":
            valid_missing = set(manifest.required_entities)
            if not set(action.missing_requirements).issubset(valid_missing):
                raise InvalidModelOutputError()

        # For complete modes: required entities must all be detected
        complete_modes = {
            InterpretationMode.SINGLE,
            InterpretationMode.MULTI_INDEPENDENT,
            InterpretationMode.MULTI_DEPENDENT,
            InterpretationMode.MIXED,
        }
        if mode in complete_modes and intent_id not in ("CLARIFICATION_REQUIRED", "UNKNOWN"):
            required = set(manifest.required_entities)
            if not required.issubset(detected_keys):
                raise InvalidModelOutputError()
            if action.missing_requirements:
                raise InvalidModelOutputError()

    def get_effective_capabilities(
        self, context: CapabilityQueryContext
    ) -> tuple[CapabilityManifest, ...]:
        """Filter manifests by context."""
        result = []
        for m in self._manifests:
            if not m.enabled:
                continue
            if m.feature_flag and m.feature_flag not in self._active_flags:
                continue
            if m.lifecycle_status not in self._allowed_lifecycle:
                continue
            if m.support_level not in self._allowed_support:
                continue
            # Channel filter (empty = no restriction)
            if m.app_requirements.allowed_channels:
                if context.channel not in m.app_requirements.allowed_channels:
                    continue
            # App capabilities
            if m.app_requirements.required_capabilities and not all(
                c in context.app_capabilities for c in m.app_requirements.required_capabilities
            ):
                continue
            # Orchestrator capabilities
            if m.orchestrator_requirements.required_capabilities and not all(
                c in context.orchestrator_capabilities
                for c in m.orchestrator_requirements.required_capabilities
            ):
                continue
            # Authentication
            if m.auth_requirements.requires_authenticated and not context.authenticated:
                continue
            if m.auth_requirements.minimum_authentication_level:
                if not self._auth_level_sufficient(
                    context.authentication_level, m.auth_requirements.minimum_authentication_level
                ):
                    continue
            if m.auth_requirements.requires_elevated and (
                context.authentication_level != self._auth_order[-1] if self._auth_order else True
            ):
                continue
            result.append(m)
        return tuple(result)

    def _auth_level_sufficient(self, current: str | None, required: str) -> bool:
        if current is None:
            return False
        if current not in self._auth_order or required not in self._auth_order:
            return False
        return self._auth_order.index(current) >= self._auth_order.index(required)
