"""T08-C5A — Verify adapters satisfy their Protocol ports and methods are async."""

import inspect

from genesis_cognitive.context.adapters.in_memory_capability_context import (
    InMemoryCapabilityContextProvider,
)
from genesis_cognitive.context.adapters.in_memory_conversation_context import (
    InMemoryConversationContextProvider,
)
from genesis_cognitive.context.adapters.in_memory_historical_activity import (
    InMemoryHistoricalActivityProvider,
)
from genesis_cognitive.context.adapters.in_memory_pending_operation_context import (
    InMemoryPendingOperationContextProvider,
)
from genesis_cognitive.context.adapters.in_memory_portfolio_context import (
    InMemoryPortfolioContextProvider,
)
from genesis_cognitive.context.ports.capability_context_provider import (
    CapabilityContextProvider,
)
from genesis_cognitive.context.ports.conversation_context_provider import (
    ConversationContextProvider,
)
from genesis_cognitive.context.ports.historical_activity_provider import (
    HistoricalActivityProvider,
)
from genesis_cognitive.context.ports.pending_operation_context_provider import (
    PendingOperationContextProvider,
)
from genesis_cognitive.context.ports.portfolio_context_provider import (
    PortfolioContextProvider,
)

# --- Static type assignments for Mypy structural check ---


def _static_type_check() -> tuple[
    ConversationContextProvider,
    PortfolioContextProvider,
    PendingOperationContextProvider,
    CapabilityContextProvider,
    HistoricalActivityProvider,
]:
    """Mypy verifies these assignments at type-check time."""
    conversation_port: ConversationContextProvider = InMemoryConversationContextProvider()
    portfolio_port: PortfolioContextProvider = InMemoryPortfolioContextProvider()
    pending_port: PendingOperationContextProvider = InMemoryPendingOperationContextProvider()
    capability_port: CapabilityContextProvider = InMemoryCapabilityContextProvider()
    historical_port: HistoricalActivityProvider = InMemoryHistoricalActivityProvider()
    return (conversation_port, portfolio_port, pending_port, capability_port, historical_port)


# --- isinstance checks (runtime_checkable Protocol) ---


class TestProtocolSatisfaction:
    def test_conversation_satisfies_protocol(self) -> None:
        adapter = InMemoryConversationContextProvider()
        assert isinstance(adapter, ConversationContextProvider)

    def test_portfolio_satisfies_protocol(self) -> None:
        adapter = InMemoryPortfolioContextProvider()
        assert isinstance(adapter, PortfolioContextProvider)

    def test_pending_operation_satisfies_protocol(self) -> None:
        adapter = InMemoryPendingOperationContextProvider()
        assert isinstance(adapter, PendingOperationContextProvider)

    def test_capability_satisfies_protocol(self) -> None:
        adapter = InMemoryCapabilityContextProvider()
        assert isinstance(adapter, CapabilityContextProvider)

    def test_historical_satisfies_protocol(self) -> None:
        adapter = InMemoryHistoricalActivityProvider()
        assert isinstance(adapter, HistoricalActivityProvider)


# --- iscoroutinefunction checks ---


class TestMethodsAreAsync:
    def test_conversation_get_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(InMemoryConversationContextProvider.get)

    def test_portfolio_get_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(InMemoryPortfolioContextProvider.get)

    def test_pending_operation_get_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(InMemoryPendingOperationContextProvider.get)

    def test_capability_get_effective_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(
            InMemoryCapabilityContextProvider.get_effective_capabilities
        )

    def test_historical_get_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(InMemoryHistoricalActivityProvider.get)
