"""WRITE PATH: persist orchestrator context into session store (Redis).

Does not call Core/BUS — only validates and maps payload already sent by the orchestrator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio
from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot
from genesis_cognitive.context.reactive_store import SessionConflictError, SessionState


class SessionStoreProtocol(Protocol):
    def get_session(self, conversation_id: str) -> SessionState | None: ...

    def create_session(self, conversation_id: str, customer_id: str) -> SessionState: ...

    def put_session(
        self,
        conversation_id: str,
        session: SessionState,
        *,
        expected_revision: int | None = None,
    ) -> None: ...


class ContextPersistenceService:
    """Validate → map → CAS persist orchestrator context."""

    SCHEMA_VERSION = 2
    SOURCE_ORCHESTRATOR = "ORCHESTRATOR"

    def __init__(self, store: SessionStoreProtocol) -> None:
        self._store = store

    @staticmethod
    def validate_context_payload(ctx: dict[str, Any] | None) -> dict[str, Any]:
        if not ctx or not isinstance(ctx.get("data"), dict):
            raise ValueError("context.data is required")
        return ctx["data"]

    def persist_orchestrator_context(
        self,
        *,
        customer_id: str,
        conversation_id: str,
        ctx_data: dict[str, Any],
        op: str = "load",
    ) -> dict[str, Any]:
        """REPLACE session snapshot from full orchestrator payload (existing contract)."""
        if op not in ("load", "refresh"):
            raise ValueError(f"context_op must be load or refresh, got {op!r}")

        mapped = map_core_portfolio(ctx_data)
        snapshot_with_id = CustomerContextSnapshot(
            customer_id=customer_id,
            display_name=mapped.snapshot.display_name,
            default_currency=mapped.snapshot.default_currency,
            products=mapped.snapshot.products,
            loans=mapped.snapshot.loans,
        )

        sess = self._store.get_session(conversation_id)
        if sess is None:
            try:
                sess = self._store.create_session(conversation_id, customer_id)
            except SessionConflictError:
                sess = self._store.get_session(conversation_id)
                if sess is None:
                    raise

        expected = int(getattr(sess, "revision", 0) or 0)
        sess.customer_id = customer_id
        sess.snapshot = snapshot_with_id
        sess.schema_version = self.SCHEMA_VERSION
        sess.snapshot_source_fetched_at = datetime.now(tz=UTC).timestamp()

        self._store.put_session(conversation_id, sess, expected_revision=expected)

        status_label = "CONTEXT_LOADED" if op == "load" else "CONTEXT_REFRESHED"
        return {
            "status": status_label,
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "display_name": snapshot_with_id.display_name,
            "context_op": op,
            "context_stamp": datetime.now(tz=UTC).isoformat(),
            "products_count": mapped.total_count,
            "active_count": mapped.active_count,
            "schema_version": self.SCHEMA_VERSION,
            "revision": int(getattr(sess, "revision", expected + 1) or expected + 1),
            "source": self.SOURCE_ORCHESTRATOR,
            "core_channel": None,
        }
