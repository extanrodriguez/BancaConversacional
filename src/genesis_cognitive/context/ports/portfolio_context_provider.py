"""Port: PortfolioContextProvider."""

from typing import Protocol, runtime_checkable

from genesis_cognitive.context.context_types import PortfolioContext


@runtime_checkable
class PortfolioContextProvider(Protocol):
    async def get(self, customer_id: str) -> PortfolioContext: ...
