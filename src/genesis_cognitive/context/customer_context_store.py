"""CustomerContextStore — in-memory store keyed by conversation_id."""

from __future__ import annotations

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot


class CustomerContextStore:
    """In-memory customer context store.

    Keyed by conversation_id. One snapshot per conversation.
    NOT Redis. NOT persistent across restarts.
    """

    def __init__(self) -> None:
        self._data: dict[str, CustomerContextSnapshot] = {}

    def get(self, conversation_id: str) -> CustomerContextSnapshot | None:
        """Get snapshot for a conversation, or None if not loaded yet."""
        return self._data.get(conversation_id)

    def put(self, conversation_id: str, snapshot: CustomerContextSnapshot) -> None:
        """Store snapshot for a conversation. Overwrites if exists."""
        self._data[conversation_id] = snapshot
