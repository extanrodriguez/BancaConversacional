"""T06 — CapabilityCatalog tests."""

import pytest

from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
from genesis_cognitive.decision.capability_types import (
    AppRequirements,
    AuthenticationRequirements,
    CapabilityManifest,
    CapabilityQueryContext,
    CapabilityValidationRules,
    OrchestratorRequirements,
)
from genesis_cognitive.decision.types import DetectedEntities, SemanticAction, TurnInterpretation
from genesis_cognitive.enums import (
    InterpretationMode,
    LifecycleStatus,
    SelectedRoute,
    SupportLevel,
)
from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError


@pytest.fixture()
def catalog() -> CapabilityCatalog:
    return CapabilityCatalog()


class TestCatalogBasics:
    def test_canonical_manifest_count(self, catalog: CapabilityCatalog) -> None:
        assert len(catalog.get_manifests()) == 10

    def test_no_extra_canonical(self, catalog: CapabilityCatalog) -> None:
        assert len(catalog.get_manifests()) == 10

    def test_manifests_are_tuple(self, catalog: CapabilityCatalog) -> None:
        assert isinstance(catalog.get_manifests(), tuple)

    def test_unique_capability_ids(self, catalog: CapabilityCatalog) -> None:
        ids = [m.capability_id for m in catalog.get_manifests()]
        assert len(ids) == len(set(ids))

    def test_unique_intent_ids(self, catalog: CapabilityCatalog) -> None:
        intents = []
        for m in catalog.get_manifests():
            intents.extend(m.intent_ids)
        assert len(intents) == len(set(intents))

    def test_get_domain_knowledge(self, catalog: CapabilityCatalog) -> None:
        assert catalog.get_domain("BUSINESS_KNOWLEDGE_QUERY") == "BUSINESS_KNOWLEDGE"

    def test_get_domain_accounts(self, catalog: CapabilityCatalog) -> None:
        assert catalog.get_domain("ACCOUNT_BALANCE_READ") == "ACCOUNTS"

    def test_get_domain_transfers(self, catalog: CapabilityCatalog) -> None:
        assert catalog.get_domain("TRANSFER_BETWEEN_OWN_ACCOUNTS") == "TRANSFERS"

    def test_get_domain_unsupported(self, catalog: CapabilityCatalog) -> None:
        assert catalog.get_domain("UNKNOWN") == "UNSUPPORTED"

    def test_unknown_intent_rejected(self, catalog: CapabilityCatalog) -> None:
        with pytest.raises(InvalidModelOutputError):
            catalog.get_manifest("NONEXISTENT_INTENT")


class TestValidation:
    def test_valid_single(self, catalog: CapabilityCatalog) -> None:
        ti = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.PERSONAL_READ,
                    detected_entities=DetectedEntities(account_ref="COR001"),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.95,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        catalog.validate_interpretation(ti)

    def test_wrong_route_rejected(self, catalog: CapabilityCatalog) -> None:
        ti = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="ACCOUNT_BALANCE_READ",
                    capability_candidate="ACCOUNT_BALANCE",
                    selected_route=SelectedRoute.BUSINESS_RAG,  # WRONG
                    detected_entities=DetectedEntities(),
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        with pytest.raises(InvalidModelOutputError):
            catalog.validate_interpretation(ti)

    def test_extra_entity_rejected(self, catalog: CapabilityCatalog) -> None:
        ti = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="PORTFOLIO_LIST",
                    capability_candidate="PORTFOLIO_LIST",
                    selected_route=SelectedRoute.PORTFOLIO_QUERY,
                    detected_entities=DetectedEntities(account_ref="COR001"),  # Not allowed
                    missing_requirements=[],
                    depends_on=[],
                    confidence=0.9,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        with pytest.raises(InvalidModelOutputError):
            catalog.validate_interpretation(ti)

    def test_unknown_with_candidate_rejected(self, catalog: CapabilityCatalog) -> None:
        """UNKNOWN + capability_candidate='TRANSFER' must be rejected by validate_interpretation."""
        unknown_action = SemanticAction(
            sequence=1,
            intent_id="UNKNOWN",
            capability_candidate="TRANSFER",
            selected_route=SelectedRoute.UNSUPPORTED,
            detected_entities=DetectedEntities(),
            missing_requirements=[],
            depends_on=[],
            confidence=0.9,
        )
        # Use model_construct to bypass mode invariant validators
        invalid_interpretation = TurnInterpretation.model_construct(
            mode=InterpretationMode.UNSUPPORTED,
            actions=[unknown_action],
            clarifications=[],
            unsupported_segments=[],
        )
        with pytest.raises(InvalidModelOutputError):
            catalog.validate_interpretation(invalid_interpretation)

    def test_clarification_without_missing_rejected(self, catalog: CapabilityCatalog) -> None:
        ti = TurnInterpretation(
            mode=InterpretationMode.SINGLE,
            actions=[
                SemanticAction(
                    sequence=1,
                    intent_id="CLARIFICATION_REQUIRED",
                    capability_candidate=None,
                    selected_route=SelectedRoute.CLARIFICATION,
                    detected_entities=DetectedEntities(),
                    missing_requirements=[],  # WRONG: must have at least one
                    depends_on=[],
                    confidence=0.8,
                )
            ],
            clarifications=[],
            unsupported_segments=[],
        )
        with pytest.raises(InvalidModelOutputError):
            catalog.validate_interpretation(ti)


class TestEffectiveCapabilities:
    def _ctx(self, **kw: object) -> CapabilityQueryContext:
        defaults: dict = {
            "channel": "websocket",
            "authenticated": True,
            "authentication_level": "standard",
            "customer_segment": None,
            "app_capabilities": (),
            "orchestrator_capabilities": ("core.transfer",),
        }
        defaults.update(kw)
        return CapabilityQueryContext(**defaults)

    def test_all_enabled_by_default(self, catalog: CapabilityCatalog) -> None:
        effective = catalog.get_effective_capabilities(self._ctx())
        assert len(effective) == 10

    def test_disabled_filtered(self) -> None:
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        # Disable first one
        disabled = manifests[0].model_copy(update={"enabled": False})
        new_manifests = (disabled, *manifests[1:])
        cat = CapabilityCatalog(manifests=new_manifests)
        effective = cat.get_effective_capabilities(self._ctx())
        assert len(effective) == 9

    def test_not_authenticated_filtered(self, catalog: CapabilityCatalog) -> None:
        effective = catalog.get_effective_capabilities(self._ctx(authenticated=False))
        assert len(effective) == 0

    def test_feature_flag_filtered(self) -> None:
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        flagged = manifests[0].model_copy(update={"feature_flag": "beta-flag"})
        cat = CapabilityCatalog(manifests=(flagged, *manifests[1:]))
        # Without flag active
        effective = cat.get_effective_capabilities(self._ctx())
        assert len(effective) == 9
        # With flag active
        cat2 = CapabilityCatalog(
            manifests=(flagged, *manifests[1:]),
            active_feature_flags=frozenset(["beta-flag"]),
        )
        effective2 = cat2.get_effective_capabilities(self._ctx())
        assert len(effective2) == 10


class TestExtensibility:
    def test_additional_manifest_via_injection(self) -> None:
        """A new manifest can be added without modifying the catalog class."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        base = _build_canonical_manifests()
        new_manifest = CapabilityManifest(
            capability_id="new-feature",
            intent_ids=("NEW_FEATURE_QUERY",),
            capability_candidate="NEW_FEATURE",
            domain="NEW_DOMAIN",
            description="A new feature",
            required_entities=(),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="NewFeatureResponse",
            orchestrator_requirements=OrchestratorRequirements(
                required_capabilities=(),
                requires_confirmation=False,
                requires_idempotency=False,
                max_execution_time_seconds=None,
            ),
            app_requirements=AppRequirements(
                allowed_channels=(),
                required_capabilities=(),
                show_confirmation_ui=False,
                show_cancellation_ui=False,
                show_timer=False,
            ),
            auth_requirements=AuthenticationRequirements(
                requires_authenticated=True,
                minimum_authentication_level=None,
                requires_elevated=False,
            ),
            support_level=SupportLevel.INFORMATION_ONLY,
            lifecycle_status=LifecycleStatus.PRODUCTION,
            feature_flag=None,
            selected_route=SelectedRoute.BUSINESS_RAG,  # Reuse existing route
            validation_rules=CapabilityValidationRules(
                min_required_entities=0,
                all_required_entities_present=True,
            ),
            enabled=True,
        )
        extended = (*base, new_manifest)
        cat = CapabilityCatalog(manifests=extended)
        assert len(cat.get_manifests()) == 11
        assert cat.get_domain("NEW_FEATURE_QUERY") == "NEW_DOMAIN"


# --- T08-C1: Entity authorization validation ---


class TestEntityAuthorization:
    def test_required_entity_authorized_valid(self) -> None:
        """required_entities with an authorized entity → catalog builds."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        # The canonical manifests all have authorized entities
        cat = CapabilityCatalog(manifests=_build_canonical_manifests())
        assert len(cat.get_manifests()) == 10

    def test_optional_entity_authorized_valid(self) -> None:
        """optional_entities with an authorized entity → catalog builds."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        # business-knowledge has optional_entities=("knowledge_topic",)
        manifests = _build_canonical_manifests()
        bk = [m for m in manifests if m.capability_id == "business-knowledge"][0]
        assert "knowledge_topic" in bk.optional_entities
        # Catalog builds successfully
        CapabilityCatalog(manifests=manifests)

    def test_required_entity_not_authorized_rejected(self) -> None:
        """required_entities=('not_allowed',) → InvalidModelOutputError."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        bad = manifests[0].model_copy(update={"required_entities": ("not_allowed",)})
        with pytest.raises(InvalidModelOutputError):
            CapabilityCatalog(manifests=(bad, *manifests[1:]))

    def test_optional_entity_not_authorized_rejected(self) -> None:
        """optional_entities=('not_allowed',) → InvalidModelOutputError."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        bad = manifests[0].model_copy(update={"optional_entities": ("not_allowed",)})
        with pytest.raises(InvalidModelOutputError):
            CapabilityCatalog(manifests=(bad, *manifests[1:]))

    def test_model_construct_with_unauthorized_entity_rejected(self) -> None:
        """Manifest via model_construct() with bad entity → InvalidModelOutputError."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        # Use model_construct to bypass Pydantic validation
        bad = CapabilityManifest.model_construct(
            capability_id="bad-manifest",
            intent_ids=("BAD_INTENT",),
            capability_candidate=None,
            domain="BAD",
            description="bad",
            required_entities=("unauthorized_field",),
            optional_entities=(),
            skill_or_specialist=None,
            output_contract="x",
            orchestrator_requirements=manifests[0].orchestrator_requirements,
            app_requirements=manifests[0].app_requirements,
            auth_requirements=manifests[0].auth_requirements,
            support_level=manifests[0].support_level,
            lifecycle_status=manifests[0].lifecycle_status,
            feature_flag=None,
            selected_route=manifests[0].selected_route,
            validation_rules=manifests[0].validation_rules,
            enabled=True,
        )
        with pytest.raises(InvalidModelOutputError):
            CapabilityCatalog(manifests=(bad, *manifests))

    def test_canonical_manifests_all_build_correctly(self) -> None:
        """All 7 canonical manifests build without error."""
        cat = CapabilityCatalog()
        assert len(cat.get_manifests()) == 10


# --- T08-C2: min_required_entities coherence ---


class TestMinRequiredEntitiesCoherence:
    def test_min_required_equal_required_count_valid(self) -> None:
        """min=1, required=('account_ref',), all=True → valid."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        # account-balance has required=("account_ref",), min=1, all=True
        cat = CapabilityCatalog(manifests=tuple(manifests))
        assert len(cat.get_manifests()) == 10

    def test_zero_required_entities_with_zero_minimum_valid(self) -> None:
        """required=(), min=0, all=True → valid."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        # portfolio-list has required=(), min=0, all=True
        cat = CapabilityCatalog(manifests=tuple(manifests))
        portfolio = [m for m in cat.get_manifests() if m.capability_id == "portfolio-list"][0]
        assert len(portfolio.required_entities) == 0
        assert portfolio.validation_rules.min_required_entities == 0

    def test_min_required_greater_than_required_count_rejected(self) -> None:
        """min=2, required=('account_ref',) → InvalidModelOutputError."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        bad = manifests[2].model_copy(
            update={
                "validation_rules": CapabilityValidationRules(
                    min_required_entities=2, all_required_entities_present=True
                )
            }
        )
        with pytest.raises(InvalidModelOutputError):
            CapabilityCatalog(manifests=(manifests[0], manifests[1], bad, *manifests[3:]))

    def test_require_all_with_lower_minimum_rejected(self) -> None:
        """required=('src','amt'), min=1, all=True → InvalidModelOutputError."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        transfer = next(m for m in manifests if m.capability_id == "transfer-own-accounts")
        bad = transfer.model_copy(
            update={
                "validation_rules": CapabilityValidationRules(
                    min_required_entities=1, all_required_entities_present=True
                )
            }
        )
        with pytest.raises(InvalidModelOutputError):
            CapabilityCatalog(
                manifests=tuple(bad if m.capability_id == "transfer-own-accounts" else m for m in manifests)
            )

    def test_partial_requirement_rule_valid(self) -> None:
        """required=('src','amt'), min=1, all=False → valid."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        partial = manifests[4].model_copy(
            update={
                "validation_rules": CapabilityValidationRules(
                    min_required_entities=1, all_required_entities_present=False
                )
            }
        )
        cat = CapabilityCatalog(
            manifests=(
                manifests[0],
                manifests[1],
                manifests[2],
                manifests[3],
                partial,
                *manifests[5:],
            )
        )
        assert len(cat.get_manifests()) == 10

    def test_model_construct_with_invalid_min_required_rejected(self) -> None:
        """model_construct() with min > required_count → InvalidModelOutputError."""
        from genesis_cognitive.decision.capability_catalog import _build_canonical_manifests

        manifests = list(_build_canonical_manifests())
        bad_rules = CapabilityValidationRules.model_construct(
            min_required_entities=5, all_required_entities_present=True
        )
        bad = manifests[0].model_copy(update={"validation_rules": bad_rules})
        with pytest.raises(InvalidModelOutputError):
            CapabilityCatalog(manifests=(bad, *manifests[1:]))


# --- T08-C3: get_domain candidate validation ---


class TestGetDomainCandidateValidation:
    def test_get_domain_without_candidate_returns_domain(self, catalog: CapabilityCatalog) -> None:
        assert catalog.get_domain("ACCOUNT_BALANCE_READ") == "ACCOUNTS"

    def test_get_domain_with_correct_candidate_returns_domain(
        self, catalog: CapabilityCatalog
    ) -> None:
        assert catalog.get_domain("ACCOUNT_BALANCE_READ", "ACCOUNT_BALANCE") == "ACCOUNTS"

    def test_get_domain_with_wrong_candidate_rejected(self, catalog: CapabilityCatalog) -> None:
        with pytest.raises(InvalidModelOutputError):
            catalog.get_domain("ACCOUNT_BALANCE_READ", "TRANSFER")

    def test_transfer_domain_with_wrong_candidate_rejected(
        self, catalog: CapabilityCatalog
    ) -> None:
        with pytest.raises(InvalidModelOutputError):
            catalog.get_domain("TRANSFER_BETWEEN_OWN_ACCOUNTS", "ACCOUNT_BALANCE")

    def test_unknown_domain_without_candidate_valid(self, catalog: CapabilityCatalog) -> None:
        assert catalog.get_domain("UNKNOWN") == "UNSUPPORTED"

    def test_unknown_domain_with_candidate_rejected(self, catalog: CapabilityCatalog) -> None:
        # UNKNOWN manifest has capability_candidate=None
        # Passing a non-None candidate should fail
        with pytest.raises(InvalidModelOutputError):
            catalog.get_domain("UNKNOWN", "TRANSFER")

    def test_clarification_domain_from_known_candidate_unchanged(
        self, catalog: CapabilityCatalog
    ) -> None:
        assert catalog.get_domain("CLARIFICATION_REQUIRED", "ACCOUNT_BALANCE") == "ACCOUNTS"
        assert catalog.get_domain("CLARIFICATION_REQUIRED", "TRANSFER") == "TRANSFERS"

    def test_clarification_domain_unknown_candidate_rejected(
        self, catalog: CapabilityCatalog
    ) -> None:
        with pytest.raises(InvalidModelOutputError):
            catalog.get_domain("CLARIFICATION_REQUIRED", "FAKE_CAPABILITY")
