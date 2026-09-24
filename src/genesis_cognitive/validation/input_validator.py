"""InputValidator — validates orchestrator payload and produces ValidatedInput."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from genesis_cognitive.context.types import OrchestratorTurnRequest, ValidatedInput
from genesis_cognitive.errors.cognitive_errors import (
    AuthenticationError,
    InputValidationError,
)


class InputValidator:
    """Validates the orchestrator turn request payload.

    Responsibilities:
    - Schema validation via Pydantic strict mode.
    - Authentication check (authenticated must be true).
    - Produces ValidatedInput with all identity and turn fields preserved.

    Does NOT:
    - Normalize, trim, translate, or correct raw_text.
    - Derive language from locale (that belongs to ContextAssembler).
    - Consult context providers.
    - Log or expose subject_token or customer_id.
    """

    def validate(self, payload: Mapping[str, object]) -> ValidatedInput:
        """Validate the incoming payload and return ValidatedInput.

        Raises:
            InputValidationError: If the payload does not conform to schema.
            AuthenticationError: If authenticated is false.
        """
        try:
            request = OrchestratorTurnRequest.model_validate(payload, strict=True)
        except ValidationError as e:
            raise InputValidationError(internal_cause=e) from e

        if not request.channel_context.authenticated:
            raise AuthenticationError()

        return ValidatedInput(
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            conversation_id=request.conversation_id,
            customer_id=request.customer_id,
            subject_token=request.subject_token,
            raw_text=request.user_turn.raw_text,
            locale=request.channel_context.locale,
            authenticated=request.channel_context.authenticated,
            channel=request.channel_context.channel,
            client_slot=request.channel_context.client_slot,
        )
