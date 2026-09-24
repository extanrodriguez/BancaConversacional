"""T09-B — ContextAssembler unit tests."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest

from genesis_cognitive.context.context_assembler import (
    AssembledContext,
    ContextAssembler,
    _derive_language,
)
from genesis_cognitive.context.context_types import (
    ConversationContext,
    PendingOperationContext,
    PortfolioContext,
)
from genesis_cognitive.context.types import (
    PortfolioProduct,
    PortfolioSnapshot,
    RecentTurn,
    ValidatedInput,
)
from genesis_cognitive.decision.capability_types import (
    CapabilityManifest,
    CapabilityQueryContext,
)
from genesis_cognitive.enums import (
    FreshnessState,
    OperationalState,
    SessionStatus,
    TurnRole,
)
from genesis_cognitive.errors.cognitive_errors import ContextProviderError

# --- Fakes ---


def _make_validated_input(
    customer_id: str = "cust-001",
    conversation_id: str = "conv-001",
    locale: str = "es-DO",
) -> ValidatedInput:
    return ValidatedInput(
        request_id="req-001",
        correlation_id="cor-001",
        conversation_id=conversation_id,
        customer_id=customer_id,
        subject_token="tok-secret",
        raw_text="  Quiero consultar MI saldo.  ",
        locale=locale,
        authenticated=True,
        channel="mobile",
        client_slot="slot-001",
    )


def _make_conversation_context() -> ConversationContext:
    return ConversationContext(
        session_id="sess-001",
        turn_number=3,
        session_status=SessionStatus.ACTIVE,
        recent_turns=(
            RecentTurn(role=TurnRole.USER, summary="Hola"),
            RecentTurn(role=TurnRole.ASSISTANT, summary="Buenos dias"),
        ),
    )


def _make_portfolio_context(customer_id: str = "cust-001") -> PortfolioContext:
    return PortfolioContext(
        snapshot=PortfolioSnapshot(
            version="v1",
            generated_at=datetime(2026, 7, 27, tzinfo=UTC),
            fresh_until=datetime(2026, 7, 27, 0, 1, tzinfo=UTC),
            freshness_state=FreshnessState.FRESH,
            products=(
                PortfolioProduct(
                    product_ref=f"COR-{customer_id}",
                    product_type="CHECKING",
                    label="Corriente",
                    alias="principal",
                    currency="DOP",
                    operational_state=OperationalState.ACTIVE,
                    recent_balance=None,
                    known_reserved_amount=None,
                    balance_as_of=None,
                ),
            ),
        )
    )


def _make_pending_context() -> PendingOperationContext:
    return PendingOperationContext()


class FakeConversationProvider:
    def __init__(self, ctx: ConversationContext) -> None:
        self._ctx = ctx
        self.calls: list[tuple[str, str]] = []

    async def get(self, conversation_id: str, customer_id: str) -> ConversationContext:
        self.calls.append((conversation_id, customer_id))
        return self._ctx


class FakePortfolioProvider:
    def __init__(self, contexts: dict[str, PortfolioContext]) -> None:
        self._contexts = contexts
        self.calls: list[str] = []

    async def get(self, customer_id: str) -> PortfolioContext:
        self.calls.append(customer_id)
        return self._contexts[customer_id]


class FakePendingProvider:
    def __init__(self, ctx: PendingOperationContext) -> None:
        self._ctx = ctx
        self.calls: list[tuple[str, str]] = []

    async def get(self, conversation_id: str, customer_id: str) -> PendingOperationContext:
        self.calls.append((conversation_id, customer_id))
        return self._ctx


class FakeCapabilityProvider:
    def __init__(self) -> None:
        self.calls: list[CapabilityQueryContext] = []

    async def get_effective_capabilities(
        self, context: CapabilityQueryContext
    ) -> tuple[CapabilityManifest, ...]:
        self.calls.append(context)
        return ()


class FailingProvider:
    async def get(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("provider failure")

    async def get_effective_capabilities(
        self, context: CapabilityQueryContext
    ) -> tuple[CapabilityManifest, ...]:
        raise RuntimeError("provider failure")


# --- Tests ---


class TestLanguageDerivation:
    def test_es_do_derives_es(self) -> None:
        assert _derive_language("es-DO") == "es"

    def test_en_us_derives_en(self) -> None:
        assert _derive_language("en-US") == "en"

    def test_bare_locale_preserves(self) -> None:
        assert _derive_language("pt") == "pt"


class TestProviderKeys:
    @pytest.mark.asyncio
    async def test_conversation_receives_correct_keys(self) -> None:
        conv = FakeConversationProvider(_make_conversation_context())
        assembler = ContextAssembler(
            conv,
            FakePortfolioProvider({"cust-001": _make_portfolio_context()}),
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        await assembler.assemble(_make_validated_input())
        assert conv.calls == [("conv-001", "cust-001")]

    @pytest.mark.asyncio
    async def test_portfolio_receives_customer_id(self) -> None:
        port = FakePortfolioProvider({"cust-001": _make_portfolio_context()})
        assembler = ContextAssembler(
            FakeConversationProvider(_make_conversation_context()),
            port,
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        await assembler.assemble(_make_validated_input())
        assert port.calls == ["cust-001"]

    @pytest.mark.asyncio
    async def test_pending_receives_both_keys(self) -> None:
        pend = FakePendingProvider(_make_pending_context())
        assembler = ContextAssembler(
            FakeConversationProvider(_make_conversation_context()),
            FakePortfolioProvider({"cust-001": _make_portfolio_context()}),
            pend,
            FakeCapabilityProvider(),
        )
        await assembler.assemble(_make_validated_input())
        assert pend.calls == [("conv-001", "cust-001")]

    @pytest.mark.asyncio
    async def test_capability_receives_channel_context(self) -> None:
        cap = FakeCapabilityProvider()
        assembler = ContextAssembler(
            FakeConversationProvider(_make_conversation_context()),
            FakePortfolioProvider({"cust-001": _make_portfolio_context()}),
            FakePendingProvider(_make_pending_context()),
            cap,
        )
        await assembler.assemble(_make_validated_input())
        assert len(cap.calls) == 1
        assert cap.calls[0].channel == "mobile"
        assert cap.calls[0].authenticated is True


class TestAssemblyResult:
    @pytest.mark.asyncio
    async def test_all_four_contexts_assembled(self) -> None:
        assembler = ContextAssembler(
            FakeConversationProvider(_make_conversation_context()),
            FakePortfolioProvider({"cust-001": _make_portfolio_context()}),
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        result = await assembler.assemble(_make_validated_input())
        assert isinstance(result, AssembledContext)
        assert result.conversation.session_id == "sess-001"
        assert result.portfolio.snapshot.version == "v1"
        assert result.pending_operations.pending_operation is None
        assert result.effective_capabilities == ()

    @pytest.mark.asyncio
    async def test_raw_text_preserved_identically(self) -> None:
        assembler = ContextAssembler(
            FakeConversationProvider(_make_conversation_context()),
            FakePortfolioProvider({"cust-001": _make_portfolio_context()}),
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        result = await assembler.assemble(_make_validated_input())
        assert result.raw_text == "  Quiero consultar MI saldo.  "


class TestIsolation:
    @pytest.mark.asyncio
    async def test_two_customers_do_not_share_portfolio(self) -> None:
        port = FakePortfolioProvider(
            {
                "cust-A": _make_portfolio_context("cust-A"),
                "cust-B": _make_portfolio_context("cust-B"),
            }
        )
        assembler = ContextAssembler(
            FakeConversationProvider(_make_conversation_context()),
            port,
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        r1 = await assembler.assemble(_make_validated_input(customer_id="cust-A"))
        r2 = await assembler.assemble(_make_validated_input(customer_id="cust-B"))
        assert r1.portfolio.snapshot.products[0].product_ref == "COR-cust-A"
        assert r2.portfolio.snapshot.products[0].product_ref == "COR-cust-B"
        assert port.calls == ["cust-A", "cust-B"]

    @pytest.mark.asyncio
    async def test_two_conversations_do_not_share_memory(self) -> None:
        conv = FakeConversationProvider(_make_conversation_context())
        assembler = ContextAssembler(
            conv,
            FakePortfolioProvider({"cust-001": _make_portfolio_context()}),
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        await assembler.assemble(_make_validated_input(conversation_id="conv-A"))
        await assembler.assemble(_make_validated_input(conversation_id="conv-B"))
        assert conv.calls == [("conv-A", "cust-001"), ("conv-B", "cust-001")]


class TestNoHistoricalContext:
    def test_assembler_does_not_import_historical(self) -> None:
        source = Path(inspect.getfile(ContextAssembler))
        tree = ast.parse(source.read_text(encoding="utf-8"))
        # Check that no import statement references historical provider
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "historical" not in node.module.lower()
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "historical" not in alias.name.lower()


class TestProviderFailureNoFallback:
    @pytest.mark.asyncio
    async def test_conversation_failure_raises_context_error(self) -> None:
        assembler = ContextAssembler(
            FailingProvider(),  # type: ignore[arg-type]
            FakePortfolioProvider({"cust-001": _make_portfolio_context()}),
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        with pytest.raises(ContextProviderError):
            await assembler.assemble(_make_validated_input())

    @pytest.mark.asyncio
    async def test_portfolio_failure_raises_context_error(self) -> None:
        assembler = ContextAssembler(
            FakeConversationProvider(_make_conversation_context()),
            FailingProvider(),  # type: ignore[arg-type]
            FakePendingProvider(_make_pending_context()),
            FakeCapabilityProvider(),
        )
        with pytest.raises(ContextProviderError):
            await assembler.assemble(_make_validated_input())


class TestNoRoutingOrExternalCalls:
    def test_module_has_no_openai_rag_or_keyword_routing(self) -> None:
        source = Path(inspect.getfile(ContextAssembler))
        tree = ast.parse(source.read_text(encoding="utf-8"))
        text = source.read_text(encoding="utf-8").lower()
        assert "openai" not in text
        assert "keyword" not in text
        assert "re.match" not in text
        assert "re.search" not in text
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and len(node.elts) > 5:
                strs = [
                    e for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                assert len(strs) < 5, "Suspicious keyword list"
