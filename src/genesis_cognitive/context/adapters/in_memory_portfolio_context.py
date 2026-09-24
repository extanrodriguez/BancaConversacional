"""In-memory PortfolioContextProvider."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from genesis_cognitive.context.context_types import PortfolioContext
from genesis_cognitive.context.types import PortfolioSnapshot
from genesis_cognitive.enums import FreshnessState


class InMemoryPortfolioContextProvider:
    """Deterministic in-memory portfolio context."""

    def __init__(
        self,
        data: dict[str, PortfolioContext] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._data: dict[str, PortfolioContext] = data or {}
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def get(self, customer_id: str) -> PortfolioContext:
        if customer_id in self._data:
            return self._data[customer_id]
        # Unknown customer: empty valid snapshot
        now = self._clock()
        return PortfolioContext(
            snapshot=PortfolioSnapshot(
                version="in-memory-0",
                generated_at=now,
                fresh_until=now + timedelta(seconds=60),
                freshness_state=FreshnessState.FRESH,
                products=(),
            )
        )
