"""Port: HistoricalActivityProvider — on-demand only."""

from typing import Protocol, runtime_checkable

from genesis_cognitive.context.context_types import HistoricalActivity


@runtime_checkable
class HistoricalActivityProvider(Protocol):
    async def get(self, customer_id: str) -> HistoricalActivity: ...
