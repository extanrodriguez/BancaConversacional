"""In-memory HistoricalActivityProvider — on-demand, empty by default."""

from genesis_cognitive.context.context_types import HistoricalActivity


class InMemoryHistoricalActivityProvider:
    """Returns empty activity. Tracks call count for testing on-demand behavior."""

    def __init__(self) -> None:
        self.call_count = 0

    async def get(self, customer_id: str) -> HistoricalActivity:
        self.call_count += 1
        return HistoricalActivity()
