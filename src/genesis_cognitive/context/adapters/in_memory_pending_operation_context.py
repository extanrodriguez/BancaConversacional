"""In-memory PendingOperationContextProvider — always null."""

from genesis_cognitive.context.context_types import PendingOperationContext


class InMemoryPendingOperationContextProvider:
    async def get(self, conversation_id: str, customer_id: str) -> PendingOperationContext:
        return PendingOperationContext()
