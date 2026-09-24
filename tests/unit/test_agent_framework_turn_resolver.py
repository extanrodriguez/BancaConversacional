"""T13-A1 — Unit tests for AgentFrameworkTurnResolver.

Uses a FakeAgent mock — no network, no real model calls.
Validates:
- calls agent.run once
- sends response_format=TurnInterpretation
- sends store=False
- returns typed result
- rejects None value
- rejects wrong type
- factory uses PromptRegistry
- no keyword routing
- no financial execution
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from genesis_cognitive.agents.agent_framework_turn_resolver import (
    AgentFrameworkTurnResolver,
    create_turn_resolver,
)
from genesis_cognitive.decision.types import TurnInterpretation
from genesis_cognitive.enums import InterpretationMode, SelectedRoute
from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError
from genesis_cognitive.model_input.model_input_builder import (
    ModelInputEnvelope,
    ProjectedCapability,
    ProjectedPendingOperation,
    ProjectedProduct,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROMPTS_ROOT = PROJECT_ROOT / "prompts"
SCHEMAS_ROOT = PROJECT_ROOT / "schemas"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_envelope() -> ModelInputEnvelope:
    """Minimal synthetic ModelInputEnvelope for testing."""
    return ModelInputEnvelope(
        raw_text="¿Cuánto tengo disponible en mi cuenta principal?",
        language="es",
        locale="es-DO",
        conversation=(),
        portfolio=(
            ProjectedProduct(
                product_ref="COR001",
                product_type="CHECKING",
                label="Cuenta corriente",
                alias="cuenta principal",
                currency="DOP",
                operational_state="ACTIVE",
            ),
        ),
        pending_operation=ProjectedPendingOperation(),
        effective_capabilities=(
            ProjectedCapability(
                capability_id="account-balance",
                intent_ids=("ACCOUNT_BALANCE_READ",),
                capability_candidate="ACCOUNT_BALANCE",
                domain="PORTFOLIO",
                description="Consulta de saldo disponible",
                selected_route=SelectedRoute.PERSONAL_READ,
                required_entities=("account_ref",),
                optional_entities=(),
                min_required_entities=1,
                output_contract="AccountBalanceResponse",
                support_level="INFORMATION_ONLY",
                requires_confirmation=False,
                requires_idempotency=False,
            ),
        ),
    )


def _make_interpretation() -> TurnInterpretation:
    """Minimal valid TurnInterpretation for test assertions."""
    from genesis_cognitive.decision.types import DetectedEntities, SemanticAction

    return TurnInterpretation(
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


class FakeAgentResponse:
    """Mimics AgentResponse with .value attribute."""

    def __init__(self, value: Any) -> None:
        self.value = value


class FakeAgent:
    """Fake Agent that records calls and returns a configurable response.

    Accepts Message objects (as used by Agent Framework) without requiring
    the full agent_framework runtime.
    """

    def __init__(self, response_value: Any) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._response_value = response_value

    async def run(self, messages: Any, *, options: Any = None) -> FakeAgentResponse:
        self.calls.append((messages, options))
        return FakeAgentResponse(self._response_value)


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


class TestResolverHappyPath:
    @pytest.fixture()
    def interpretation(self) -> TurnInterpretation:
        return _make_interpretation()

    @pytest.fixture()
    def fake_agent(self, interpretation: TurnInterpretation) -> FakeAgent:
        return FakeAgent(interpretation)

    @pytest.fixture()
    def resolver(self, fake_agent: FakeAgent) -> AgentFrameworkTurnResolver:
        return AgentFrameworkTurnResolver(fake_agent)  # type: ignore[arg-type]

    async def test_calls_agent_run_once(
        self, resolver: AgentFrameworkTurnResolver, fake_agent: FakeAgent
    ) -> None:
        await resolver.resolve(_make_envelope())
        assert len(fake_agent.calls) == 1

    async def test_sends_response_format_turn_interpretation(
        self, resolver: AgentFrameworkTurnResolver, fake_agent: FakeAgent
    ) -> None:
        await resolver.resolve(_make_envelope())
        _, options = fake_agent.calls[0]
        assert options["response_format"] is TurnInterpretation

    async def test_sends_store_false(
        self, resolver: AgentFrameworkTurnResolver, fake_agent: FakeAgent
    ) -> None:
        await resolver.resolve(_make_envelope())
        _, options = fake_agent.calls[0]
        assert options["store"] is False

    async def test_returns_typed_turn_interpretation(
        self,
        resolver: AgentFrameworkTurnResolver,
        interpretation: TurnInterpretation,
    ) -> None:
        result = await resolver.resolve(_make_envelope())
        assert isinstance(result, TurnInterpretation)
        assert result is interpretation


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestResolverErrors:
    async def test_rejects_none_value(self) -> None:
        fake = FakeAgent(None)
        resolver = AgentFrameworkTurnResolver(fake)  # type: ignore[arg-type]
        with pytest.raises(InvalidModelOutputError):
            await resolver.resolve(_make_envelope())

    async def test_rejects_wrong_type(self) -> None:
        fake = FakeAgent({"mode": "SINGLE", "actions": []})  # dict, not TurnInterpretation
        resolver = AgentFrameworkTurnResolver(fake)  # type: ignore[arg-type]
        with pytest.raises(InvalidModelOutputError):
            await resolver.resolve(_make_envelope())

    async def test_rejects_agent_exception(self) -> None:
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=RuntimeError("timeout"))
        resolver = AgentFrameworkTurnResolver(agent)
        with pytest.raises(InvalidModelOutputError) as exc_info:
            await resolver.resolve(_make_envelope())
        assert exc_info.value.internal_cause is not None


# ---------------------------------------------------------------------------
# Tests: factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_factory_uses_prompt_registry(self) -> None:
        from genesis_cognitive.prompts.prompt_registry import PromptRegistry

        registry = PromptRegistry(PROMPTS_ROOT, SCHEMAS_ROOT)
        resolver = create_turn_resolver(registry, "fake-key", "gpt-4.1-mini")
        assert isinstance(resolver, AgentFrameworkTurnResolver)

    def test_factory_loads_current_prompt_version(self) -> None:
        from genesis_cognitive.prompts.prompt_registry import PromptRegistry

        registry = PromptRegistry(PROMPTS_ROOT, SCHEMAS_ROOT)
        # Verify prompt 1.2.0 is current
        pv = registry.get_current("turn-decision-agent")
        assert pv.prompt_version == "1.2.0"
        # Factory should succeed using same registry
        resolver = create_turn_resolver(registry, "fake-key", "gpt-4.1-mini")
        assert resolver is not None


# ---------------------------------------------------------------------------
# Tests: mandatory controls
# ---------------------------------------------------------------------------


class TestMandatoryControls:
    """Verify no keyword routing, no financial execution."""

    async def test_no_keyword_routing(self) -> None:
        """Resolver does not inspect raw_text for keywords — it passes to agent."""
        interpretation = _make_interpretation()
        fake = FakeAgent(interpretation)
        resolver = AgentFrameworkTurnResolver(fake)  # type: ignore[arg-type]

        # Different raw_text patterns should all just pass through to agent
        for text in [
            "transferir dinero",
            "hello world",
            "¿saldo?",
            "préstamo hipotecario",
        ]:
            envelope = ModelInputEnvelope(
                raw_text=text,
                language="es",
                locale="es-DO",
                conversation=(),
                portfolio=(),
                pending_operation=ProjectedPendingOperation(),
                effective_capabilities=(),
            )
            result = await resolver.resolve(envelope)
            # All return same interpretation — resolver doesn't route by text
            assert result is interpretation

    async def test_no_financial_execution(self) -> None:
        """Resolver output is TurnInterpretation — no execution, no side effects."""
        interpretation = _make_interpretation()
        fake = FakeAgent(interpretation)
        resolver = AgentFrameworkTurnResolver(fake)  # type: ignore[arg-type]
        result = await resolver.resolve(_make_envelope())
        # Result is purely interpretive
        assert result.mode == InterpretationMode.SINGLE
        assert result.actions[0].selected_route == SelectedRoute.PERSONAL_READ
        # No execution methods exist on result
        assert not hasattr(result, "execute")
        assert not hasattr(result, "confirm")
