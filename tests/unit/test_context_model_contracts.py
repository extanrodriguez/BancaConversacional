"""T08-C5C1 — Context model strictness, immutability, and collection contracts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from genesis_cognitive.context.context_types import (
    ConversationContext,
    HistoricalActivity,
    HistoricalActivityItem,
    PortfolioContext,
)
from genesis_cognitive.context.types import (
    PortfolioProduct,
    PortfolioSnapshot,
    SessionContext,
)
from genesis_cognitive.enums import (
    FreshnessState,
    OperationalState,
    SessionStatus,
)

# --- Helpers ---


def _snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        version="v1",
        generated_at=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
        fresh_until=datetime(2026, 7, 26, 10, 1, tzinfo=UTC),
        freshness_state=FreshnessState.FRESH,
        products=(),
    )


def _product() -> PortfolioProduct:
    return PortfolioProduct(
        product_ref="COR001",
        product_type="CHECKING",
        label=None,
        alias=None,
        currency="DOP",
        operational_state=OperationalState.ACTIVE,
        recent_balance=Decimal("100.00"),
        known_reserved_amount=Decimal("0"),
        balance_as_of=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
    )


# --- ConversationContext ---


class TestConversationContextStrict:
    def test_conversation_context_rejects_extra_field(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs"):
            ConversationContext(
                session_id="s1",
                turn_number=1,
                session_status=SessionStatus.ACTIVE,
                recent_turns=(),
                extra_field="bad",  # type: ignore[call-arg]
            )

    def test_conversation_context_rejects_turn_number_string(self) -> None:
        with pytest.raises(ValidationError):
            ConversationContext(
                session_id="s1",
                turn_number="1",  # type: ignore[arg-type]
                session_status=SessionStatus.ACTIVE,
                recent_turns=(),
            )

    def test_conversation_context_is_frozen(self) -> None:
        ctx = ConversationContext(
            session_id="s1",
            turn_number=1,
            session_status=SessionStatus.ACTIVE,
            recent_turns=(),
        )
        with pytest.raises(ValidationError):
            ctx.turn_number = 2  # noqa: F841


# --- PortfolioContext ---


class TestPortfolioContextStrict:
    def test_portfolio_context_rejects_extra_field(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs"):
            PortfolioContext(
                snapshot=_snapshot(),
                extra="bad",  # type: ignore[call-arg]
            )

    def test_portfolio_snapshot_rejects_products_list(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioSnapshot(
                version="v1",
                generated_at=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
                fresh_until=datetime(2026, 7, 26, 10, 1, tzinfo=UTC),
                freshness_state=FreshnessState.FRESH,
                products=[_product()],  # type: ignore[arg-type]
            )

    def test_portfolio_snapshot_products_is_tuple(self) -> None:
        snap = PortfolioSnapshot(
            version="v1",
            generated_at=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
            fresh_until=datetime(2026, 7, 26, 10, 1, tzinfo=UTC),
            freshness_state=FreshnessState.FRESH,
            products=(_product(),),
        )
        assert isinstance(snap.products, tuple)


# --- SessionContext ---


class TestSessionContextStrict:
    def test_session_context_rejects_recent_turns_list(self) -> None:
        with pytest.raises(ValidationError):
            SessionContext(
                session_status=SessionStatus.ACTIVE,
                recent_turns=[],  # type: ignore[arg-type]
                known_products=_snapshot(),
                pending_operation=None,
                last_operation_request=None,
                last_operation_result=None,
            )

    def test_session_context_recent_turns_is_tuple(self) -> None:
        ctx = SessionContext(
            session_status=SessionStatus.ACTIVE,
            recent_turns=(),
            known_products=_snapshot(),
            pending_operation=None,
            last_operation_request=None,
            last_operation_result=None,
        )
        assert isinstance(ctx.recent_turns, tuple)


# --- HistoricalActivityItem ---


class TestHistoricalActivityItemStrict:
    def test_historical_item_rejects_timestamp_string(self) -> None:
        with pytest.raises(ValidationError):
            HistoricalActivityItem(
                description="test",
                timestamp="2026-07-26T10:00:00Z",  # type: ignore[arg-type]
            )

    def test_historical_item_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            HistoricalActivityItem(
                description="test",
                timestamp=datetime(2026, 7, 26, 10, 0),  # noqa: DTZ001
            )

    def test_historical_item_accepts_timezone_aware_datetime(self) -> None:
        item = HistoricalActivityItem(
            description="test",
            timestamp=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
        )
        assert item.timestamp.tzinfo is not None


# --- HistoricalActivity ---


class TestHistoricalActivityStrict:
    def test_historical_activity_rejects_items_list(self) -> None:
        item = HistoricalActivityItem(
            description="test",
            timestamp=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
        )
        with pytest.raises(ValidationError):
            HistoricalActivity(items=[item])  # type: ignore[arg-type]
        # tuple accepted
        activity = HistoricalActivity(items=(item,))
        assert isinstance(activity.items, tuple)


# --- ConfigDict verification ---


class TestModelConfigContracts:
    @pytest.mark.parametrize(
        "model",
        [
            ConversationContext,
            PortfolioContext,
            PortfolioSnapshot,
            SessionContext,
            HistoricalActivityItem,
            HistoricalActivity,
        ],
    )
    def test_model_config_extra_strict_frozen(self, model: type) -> None:
        config = model.model_config  # type: ignore[attr-defined]
        assert config.get("extra") == "forbid", f"{model.__name__} extra != forbid"
        assert config.get("strict") is True, f"{model.__name__} strict != True"
        assert config.get("frozen") is True, f"{model.__name__} frozen != True"
