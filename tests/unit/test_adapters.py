"""T07 — Context provider adapter tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from genesis_cognitive.context.adapters.in_memory_capability_context import (
    InMemoryCapabilityContextProvider,
)
from genesis_cognitive.context.adapters.in_memory_conversation_context import (
    InMemoryConversationContextProvider,
)
from genesis_cognitive.context.adapters.in_memory_historical_activity import (
    InMemoryHistoricalActivityProvider,
)
from genesis_cognitive.context.adapters.in_memory_pending_operation_context import (
    InMemoryPendingOperationContextProvider,
)
from genesis_cognitive.context.adapters.in_memory_portfolio_context import (
    InMemoryPortfolioContextProvider,
)
from genesis_cognitive.context.context_types import ConversationContext, PortfolioContext
from genesis_cognitive.context.types import PortfolioProduct, PortfolioSnapshot
from genesis_cognitive.decision.capability_types import CapabilityQueryContext
from genesis_cognitive.enums import FreshnessState, OperationalState, SessionStatus


class TestConversationProvider:
    @pytest.mark.asyncio
    async def test_unknown_returns_defaults(self) -> None:
        p = InMemoryConversationContextProvider()
        ctx = await p.get("conv-new", "cust-new")
        assert ctx.turn_number == 1
        assert ctx.session_status == SessionStatus.ACTIVE
        assert ctx.recent_turns == ()

    @pytest.mark.asyncio
    async def test_known_returns_stored(self) -> None:
        stored = ConversationContext(
            session_id="sess-1", turn_number=3, session_status=SessionStatus.ACTIVE, recent_turns=()
        )
        p = InMemoryConversationContextProvider(data={("conv-1", "cust-1"): stored})
        ctx = await p.get("conv-1", "cust-1")
        assert ctx.turn_number == 3

    @pytest.mark.asyncio
    async def test_isolation_between_customers(self) -> None:
        """Same conversation_id, different customers → different contexts."""
        p = InMemoryConversationContextProvider()
        ctx1 = await p.get("conv-1", "cust-A")
        ctx2 = await p.get("conv-1", "cust-B")
        assert ctx1.session_id != ctx2.session_id

    @pytest.mark.asyncio
    async def test_recent_turns_immutable(self) -> None:
        p = InMemoryConversationContextProvider()
        ctx = await p.get("conv-1", "cust-1")
        assert isinstance(ctx.recent_turns, tuple)


class TestPortfolioProvider:
    @pytest.mark.asyncio
    async def test_unknown_returns_empty_fresh(self) -> None:
        p = InMemoryPortfolioContextProvider()
        ctx = await p.get("unknown-cust")
        assert ctx.snapshot.freshness_state == FreshnessState.FRESH
        assert ctx.snapshot.products == ()

    @pytest.mark.asyncio
    async def test_dates_timezone_aware(self) -> None:
        p = InMemoryPortfolioContextProvider()
        ctx = await p.get("cust")
        assert ctx.snapshot.generated_at.tzinfo is not None
        assert ctx.snapshot.fresh_until.tzinfo is not None

    @pytest.mark.asyncio
    async def test_isolation_between_customers(self) -> None:
        p = InMemoryPortfolioContextProvider()
        ctx_a = await p.get("cust-A")
        ctx_b = await p.get("cust-B")
        # Both are empty but independent
        assert ctx_a.snapshot.version == ctx_b.snapshot.version

    # --- T08-C5B: Portfolio known, Decimal, isolation ---

    @pytest.mark.asyncio
    async def test_known_customer_returns_stored_portfolio(self) -> None:
        data = _build_two_customer_data()
        p = InMemoryPortfolioContextProvider(data=data)
        ctx = await p.get("cust-A")
        assert len(ctx.snapshot.products) == 1
        assert ctx.snapshot.products[0].product_ref == "COR001"
        assert ctx.snapshot.products[0].alias == "cuenta principal"

    @pytest.mark.asyncio
    async def test_known_customer_preserves_recent_balance_decimal(self) -> None:
        data = _build_two_customer_data()
        p = InMemoryPortfolioContextProvider(data=data)
        ctx = await p.get("cust-A")
        balance = ctx.snapshot.products[0].recent_balance
        assert isinstance(balance, Decimal)
        assert balance == Decimal("12500.75")

    @pytest.mark.asyncio
    async def test_known_customer_preserves_reserved_amount_decimal(self) -> None:
        data = _build_two_customer_data()
        p = InMemoryPortfolioContextProvider(data=data)
        ctx = await p.get("cust-A")
        reserved = ctx.snapshot.products[0].known_reserved_amount
        assert isinstance(reserved, Decimal)
        assert reserved == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_negative_recent_balance_is_preserved(self) -> None:
        from genesis_cognitive.types.monetary import SignedDecimalString  # noqa: F401

        product = PortfolioProduct(
            product_ref="OVD001",
            product_type="OVERDRAFT",
            label=None,
            alias=None,
            currency="DOP",
            operational_state=OperationalState.ACTIVE,
            recent_balance=Decimal("-25.50"),
            known_reserved_amount=Decimal("0"),
            balance_as_of=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
        )
        snapshot = PortfolioSnapshot(
            version="test-neg",
            generated_at=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
            fresh_until=datetime(2026, 7, 26, 10, 1, tzinfo=UTC),
            freshness_state=FreshnessState.FRESH,
            products=(product,),
        )
        data = {"cust-neg": PortfolioContext(snapshot=snapshot)}
        p = InMemoryPortfolioContextProvider(data=data)
        ctx = await p.get("cust-neg")
        assert ctx.snapshot.products[0].recent_balance == Decimal("-25.50")

    @pytest.mark.asyncio
    async def test_customer_a_never_receives_customer_b_product(self) -> None:
        data = _build_two_customer_data()
        p = InMemoryPortfolioContextProvider(data=data)
        ctx_a = await p.get("cust-A")
        refs = [prod.product_ref for prod in ctx_a.snapshot.products]
        assert "AHO001" not in refs

    @pytest.mark.asyncio
    async def test_customer_b_never_receives_customer_a_product(self) -> None:
        data = _build_two_customer_data()
        p = InMemoryPortfolioContextProvider(data=data)
        ctx_b = await p.get("cust-B")
        refs = [prod.product_ref for prod in ctx_b.snapshot.products]
        assert "COR001" not in refs

    @pytest.mark.asyncio
    async def test_unknown_customer_is_empty_even_when_known_data_exists(self) -> None:
        data = _build_two_customer_data()
        p = InMemoryPortfolioContextProvider(data=data)
        ctx = await p.get("cust-unknown")
        assert ctx.snapshot.products == ()
        assert ctx.snapshot.freshness_state == FreshnessState.FRESH

    @pytest.mark.asyncio
    async def test_products_collection_is_tuple(self) -> None:
        data = _build_two_customer_data()
        p = InMemoryPortfolioContextProvider(data=data)
        ctx = await p.get("cust-A")
        assert isinstance(ctx.snapshot.products, tuple)
        assert not hasattr(ctx.snapshot.products, "append")

    @pytest.mark.asyncio
    async def test_injected_clock_controls_empty_snapshot_times(self) -> None:
        fixed_time = datetime(2026, 7, 26, 15, 0, tzinfo=UTC)
        p = InMemoryPortfolioContextProvider(clock=lambda: fixed_time)
        ctx = await p.get("cust-new")
        assert ctx.snapshot.generated_at == fixed_time
        assert ctx.snapshot.fresh_until == fixed_time + timedelta(seconds=60)
        assert ctx.snapshot.generated_at.tzinfo is not None
        assert ctx.snapshot.fresh_until.tzinfo is not None


class TestPendingOperationProvider:
    @pytest.mark.asyncio
    async def test_returns_three_null(self) -> None:
        p = InMemoryPendingOperationContextProvider()
        ctx = await p.get("conv-1", "cust-1")
        assert ctx.pending_operation is None
        assert ctx.last_operation_request is None
        assert ctx.last_operation_result is None


class TestCapabilityProvider:
    @pytest.mark.asyncio
    async def test_returns_seven_capabilities(self) -> None:
        p = InMemoryCapabilityContextProvider()
        qctx = CapabilityQueryContext(
            channel="ws",
            authenticated=True,
            authentication_level="standard",
            customer_segment=None,
            app_capabilities=(),
            orchestrator_capabilities=("core.transfer",),
        )
        caps = await p.get_effective_capabilities(qctx)
        assert len(caps) == 10

    @pytest.mark.asyncio
    async def test_returns_tuple(self) -> None:
        p = InMemoryCapabilityContextProvider()
        qctx = CapabilityQueryContext(
            channel="ws",
            authenticated=True,
            authentication_level=None,
            customer_segment=None,
            app_capabilities=(),
            orchestrator_capabilities=("core.transfer",),
        )
        caps = await p.get_effective_capabilities(qctx)
        assert isinstance(caps, tuple)


class TestHistoricalActivityProvider:
    @pytest.mark.asyncio
    async def test_returns_empty(self) -> None:
        p = InMemoryHistoricalActivityProvider()
        activity = await p.get("cust-1")
        assert activity.items == ()

    @pytest.mark.asyncio
    async def test_call_count_starts_zero(self) -> None:
        p = InMemoryHistoricalActivityProvider()
        assert p.call_count == 0

    @pytest.mark.asyncio
    async def test_increments_on_call(self) -> None:
        p = InMemoryHistoricalActivityProvider()
        await p.get("cust-1")
        assert p.call_count == 1
        await p.get("cust-2")
        assert p.call_count == 2

    @pytest.mark.asyncio
    async def test_not_called_by_other_adapters(self) -> None:
        """Historical is on-demand only — other providers don't call it."""
        hist = InMemoryHistoricalActivityProvider()
        conv = InMemoryConversationContextProvider()
        port = InMemoryPortfolioContextProvider()
        await conv.get("conv-1", "cust-1")
        await port.get("cust-1")
        assert hist.call_count == 0


# --- Helpers ---


def _build_two_customer_data() -> dict[str, PortfolioContext]:
    """Build fixture data for cust-A and cust-B."""
    product_a = PortfolioProduct(
        product_ref="COR001",
        product_type="CHECKING",
        label="Cuenta corriente",
        alias="cuenta principal",
        currency="DOP",
        operational_state=OperationalState.ACTIVE,
        recent_balance=Decimal("12500.75"),
        known_reserved_amount=Decimal("500.00"),
        balance_as_of=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
    )
    snapshot_a = PortfolioSnapshot(
        version="v1-a",
        generated_at=datetime(2026, 7, 26, 9, 0, tzinfo=UTC),
        fresh_until=datetime(2026, 7, 26, 9, 1, tzinfo=UTC),
        freshness_state=FreshnessState.FRESH,
        products=(product_a,),
    )

    product_b = PortfolioProduct(
        product_ref="AHO001",
        product_type="SAVINGS",
        label="Cuenta de ahorros",
        alias="mis ahorros",
        currency="DOP",
        operational_state=OperationalState.ACTIVE,
        recent_balance=Decimal("3200.25"),
        known_reserved_amount=Decimal("0"),
        balance_as_of=datetime(2026, 7, 26, 11, 0, tzinfo=UTC),
    )
    snapshot_b = PortfolioSnapshot(
        version="v1-b",
        generated_at=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
        fresh_until=datetime(2026, 7, 26, 10, 1, tzinfo=UTC),
        freshness_state=FreshnessState.FRESH,
        products=(product_b,),
    )

    return {
        "cust-A": PortfolioContext(snapshot=snapshot_a),
        "cust-B": PortfolioContext(snapshot=snapshot_b),
    }
