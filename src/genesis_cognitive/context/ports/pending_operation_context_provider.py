"""Port: PendingOperationContextProvider."""

from typing import Protocol, runtime_checkable

from genesis_cognitive.context.context_types import PendingOperationContext


@runtime_checkable
class PendingOperationContextProvider(Protocol):
    async def get(self, conversation_id: str, customer_id: str) -> PendingOperationContext: ...
