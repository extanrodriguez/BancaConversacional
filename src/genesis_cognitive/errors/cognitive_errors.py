"""Typed cognitive errors — fixed static messages, no arbitrary public text."""


class CognitiveError(Exception):
    """Base error for cognitive layer."""

    error_code: str
    message: str
    internal_cause: Exception | None

    def __init__(self, *, internal_cause: Exception | None = None) -> None:
        self.internal_cause = internal_cause
        super().__init__(self.message)


class InputValidationError(CognitiveError):
    """Payload does not conform to orchestrator_turn_request schema."""

    error_code = "INVALID_INPUT"
    message = "La solicitud no es estructuralmente valida."


class AuthenticationError(CognitiveError):
    """authenticated is false or absent."""

    error_code = "AUTHENTICATION_REQUIRED"
    message = "Se requiere autenticacion."


class ContextProviderError(CognitiveError):
    """A context adapter failed."""

    error_code = "CONTEXT_PROVIDER_ERROR"
    message = "Error al obtener contexto."


class ModelInvocationError(CognitiveError):
    """The model could not be invoked."""

    error_code = "MODEL_INVOCATION_ERROR"
    message = "Error al invocar el modelo."


class InvalidModelOutputError(CognitiveError):
    """Model output is invalid."""

    error_code = "INVALID_MODEL_OUTPUT"
    message = "La respuesta del modelo no es valida."
