"""ContextAssembler — assembles authorized context from providers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from genesis_cognitive.context.context_types import (
    ConversationContext,
    PendingOperationContext,
    PortfolioContext,
)
from genesis_cognitive.context.ports.capability_context_provider import (
    CapabilityContextProvider,
)
from genesis_cognitive.context.ports.conversation_context_provider import (
    ConversationContextProvider,
)
from genesis_cognitive.context.ports.pending_operation_context_provider import (
    PendingOperationContextProvider,
)
from genesis_cognitive.context.ports.portfolio_context_provider import (
    PortfolioContextProvider,
)
from genesis_cognitive.context.types import ValidatedInput
from genesis_cognitive.decision.capability_types import (
    CapabilityManifest,
    CapabilityQueryContext,
)
from genesis_cognitive.errors.cognitive_errors import ContextProviderError


class AssembledContext(BaseModel):
    """Aggregated context assembled from all providers for a single turn."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    # Identity (preserved from ValidatedInput)
    request_id: str
    correlation_id: str
    conversation_id: str
    customer_id: str
    subject_token: str

    # Turn data
    raw_text: str
    locale: str
    language: str
    channel: str
    client_slot: str
    authenticated: bool

    # Provider results
    conversation: ConversationContext
    portfolio: PortfolioContext
    pending_operations: PendingOperationContext
    effective_capabilities: tuple[CapabilityManifest, ...]


class ContextAssembler:
    """Assembles the authorized context for a cognitive turn.

    Injects the four context providers and queries each with the
    appropriate isolation keys from ValidatedInput.

    Does NOT:
    - Interpret raw_text.
    - Consult HistoricalActivityProvider (directive 164).
    - Fall back to another customer or conversation on failure.
    - Log subject_token, customer_id, or raw_text.
    """

    def __init__(
        self,
        conversation_provider: ConversationContextProvider,
        portfolio_provider: PortfolioContextProvider,
        pending_provider: PendingOperationContextProvider,
        capability_provider: CapabilityContextProvider,
    ) -> None:
        self._conversation = conversation_provider
        self._portfolio = portfolio_provider
        self._pending = pending_provider
        self._capability = capability_provider

    async def assemble(self, validated: ValidatedInput) -> AssembledContext:
        """Assemble context from all providers.

        Args:
            validated: Already-authenticated ValidatedInput from InputValidator.

        Returns:
            AssembledContext with all provider results and derived language.

        Raises:
            ContextProviderError: If any provider fails.
        """
        # Derive language from locale (primary subtag only)
        language = _derive_language(validated.locale)

        try:
            conversation = await self._conversation.get(
                conversation_id=validated.conversation_id,
                customer_id=validated.customer_id,
            )
        except Exception as e:
            raise ContextProviderError(internal_cause=e) from e

        try:
            portfolio = await self._portfolio.get(
                customer_id=validated.customer_id,
            )
        except Exception as e:
            raise ContextProviderError(internal_cause=e) from e

        try:
            pending = await self._pending.get(
                conversation_id=validated.conversation_id,
                customer_id=validated.customer_id,
            )
        except Exception as e:
            raise ContextProviderError(internal_cause=e) from e

        try:
            query_context = CapabilityQueryContext(
                channel=validated.channel,
                authenticated=validated.authenticated,
                authentication_level=None,
                customer_segment=None,
                app_capabilities=(),
                orchestrator_capabilities=(),
            )
            capabilities = await self._capability.get_effective_capabilities(
                context=query_context,
            )
        except Exception as e:
            raise ContextProviderError(internal_cause=e) from e

        return AssembledContext(
            request_id=validated.request_id,
            correlation_id=validated.correlation_id,
            conversation_id=validated.conversation_id,
            customer_id=validated.customer_id,
            subject_token=validated.subject_token,
            raw_text=validated.raw_text,
            locale=validated.locale,
            language=language,
            channel=validated.channel,
            client_slot=validated.client_slot,
            authenticated=validated.authenticated,
            conversation=conversation,
            portfolio=portfolio,
            pending_operations=pending,
            effective_capabilities=capabilities,
        )


def _derive_language(locale: str) -> str:
    """Extract the primary language subtag from a locale string.

    Examples:
        es-DO → es
        en-US → en
        pt → pt
    """
    return locale.split("-")[0]
