"""Port: ConversationContextProvider."""

from typing import Protocol, runtime_checkable

from genesis_cognitive.context.context_types import ConversationContext


@runtime_checkable
class ConversationContextProvider(Protocol):
    async def get(self, conversation_id: str, customer_id: str) -> ConversationContext: ...
