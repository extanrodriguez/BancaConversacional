"""Typed errors for prompt loading and validation."""


class PromptError(Exception):
    """Base prompt error."""

    def __init__(self, *, internal_cause: Exception | None = None) -> None:
        self.internal_cause = internal_cause
        super().__init__(self.__class__.message)

    message: str = "Error de prompt."


class PromptNotFoundError(PromptError):
    message = "El prompt solicitado no existe."


class PromptInvalidJsonError(PromptError):
    message = "El archivo de prompt no contiene JSON valido."


class PromptSchemaValidationError(PromptError):
    message = "El prompt no cumple el schema requerido."


class PromptReferenceError(PromptError):
    message = "Una referencia del prompt no puede resolverse."


class PromptVersionMismatchError(PromptError):
    message = "La version del prompt no coincide con el directorio."


class UnsafePromptPathError(PromptError):
    message = "La ruta solicitada no es segura."
