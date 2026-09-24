"""In-memory ConversationContextProvider."""

import uuid

from genesis_cognitive.context.context_types import ConversationContext
from genesis_cognitive.enums import SessionStatus


class InMemoryConversationContextProvider:
    """Deterministic in-memory conversation context."""

    def __init__(self, data: dict[tuple[str, str], ConversationContext] | None = None) -> None:
        self._data: dict[tuple[str, str], ConversationContext] = data or {}

    async def get(self, conversation_id: str, customer_id: str) -> ConversationContext:
        key = (conversation_id, customer_id)
        if key in self._data:
            return self._data[key]
        # Unknown conversation: deterministic defaults
        return ConversationContext(
            session_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{conversation_id}:{customer_id}")),
            turn_number=1,
            session_status=SessionStatus.ACTIVE,
            recent_turns=(),
        )
