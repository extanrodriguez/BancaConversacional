"""Prompt validator — validates prompt against schema and checks references."""

import json
from pathlib import Path
from typing import Any

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
    ValidationError,
)

from genesis_cognitive.prompts.errors import (
    PromptReferenceError,
    PromptSchemaValidationError,
    PromptVersionMismatchError,
)
from genesis_cognitive.prompts.prompt_version import PromptVersion


class PromptValidator:
    """Validates prompt payloads against agent_prompt.schema.json."""

    def __init__(self, prompts_root: Path, schemas_root: Path) -> None:
        self._prompts_root = prompts_root.resolve()
        self._schemas_root = schemas_root.resolve()
        self._schema = self._load_prompt_schema()
        self._validator = Draft202012Validator(self._schema, format_checker=FormatChecker())

    def _load_prompt_schema(self) -> dict[str, Any]:
        schema_path = self._prompts_root / "schemas" / "agent_prompt.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return schema  # type: ignore[no-any-return]

    def validate(
        self, payload: dict[str, Any], expected_agent_id: str, expected_version: str
    ) -> PromptVersion:
        """Validate payload and return immutable PromptVersion."""
        # Schema validation
        try:
            self._validator.validate(payload)
        except ValidationError as e:
            raise PromptSchemaValidationError(internal_cause=e) from e

        # Consistency checks
        if payload.get("agent_id") != expected_agent_id:
            raise PromptVersionMismatchError()
        if payload.get("prompt_version") != expected_version:
            raise PromptVersionMismatchError()

        # Verify output_schema reference exists and is valid
        output_ref = payload["contracts"]["output_schema"]
        self._verify_output_schema(output_ref)

        # Dataset reference: register as pending (do not require existence yet)
        # CA-29 dataset existence is PENDING_T19

        # Build immutable model using model_validate_json for strict tuple handling
        return PromptVersion.model_validate_json(json.dumps(payload, ensure_ascii=False))

    def _verify_output_schema(self, ref: str) -> None:
        """Verify the referenced output schema exists and is valid.

        Accepts only: schemas/<safe-path>.schema.json@1.0
        """
        parts = ref.split("@")
        if len(parts) != 2:
            raise PromptReferenceError()

        schema_path_str, version = parts
        if version != "1.0":
            raise PromptReferenceError()
        if not schema_path_str.startswith("schemas/"):
            raise PromptReferenceError()
        if not schema_path_str.endswith(".schema.json"):
            raise PromptReferenceError()

        relative_part = schema_path_str[len("schemas/") :]
        if not relative_part or "\\" in relative_part or ".." in relative_part:
            raise PromptReferenceError()
        if relative_part.startswith("/") or "//" in relative_part:
            raise PromptReferenceError()

        schema_file = (self._schemas_root / relative_part).resolve()
        if not schema_file.is_relative_to(self._schemas_root):
            raise PromptReferenceError()
        if not schema_file.is_file():
            raise PromptReferenceError()

        try:
            schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema_data)
        except Exception as e:
            raise PromptReferenceError(internal_cause=e) from e
