"""T09-A — InputValidator unit tests."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest

from genesis_cognitive.context.types import ValidatedInput
from genesis_cognitive.errors.cognitive_errors import (
    AuthenticationError,
    InputValidationError,
)
from genesis_cognitive.validation.input_validator import InputValidator


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "USER_MESSAGE",
        "conversation_id": "conv-001",
        "customer_id": "cust-001",
        "subject_token": "tok-secret-abc",
        "request_id": "req-001",
        "correlation_id": "cor-001",
        "user_turn": {"raw_text": "Quiero consultar mi saldo."},
        "channel_context": {
            "channel": "mobile",
            "client_slot": "slot-001",
            "authenticated": True,
            "locale": "es-DO",
        },
    }
    base.update(overrides)
    return base


class TestValidPayload:
    def test_valid_payload_produces_validated_input(self) -> None:
        validator = InputValidator()
        result = validator.validate(_valid_payload())
        assert isinstance(result, ValidatedInput)

    def test_all_values_preserved_exactly(self) -> None:
        payload = _valid_payload()
        result = InputValidator().validate(payload)
        assert result.request_id == "req-001"
        assert result.correlation_id == "cor-001"
        assert result.conversation_id == "conv-001"
        assert result.customer_id == "cust-001"
        assert result.subject_token == "tok-secret-abc"
        assert result.raw_text == "Quiero consultar mi saldo."
        assert result.locale == "es-DO"
        assert result.authenticated is True
        assert result.channel == "mobile"
        assert result.client_slot == "slot-001"


class TestAuthenticationFailure:
    def test_authenticated_false_raises_authentication_error(self) -> None:
        payload = _valid_payload()
        payload["channel_context"]["authenticated"] = False
        with pytest.raises(AuthenticationError):
            InputValidator().validate(payload)


class TestSchemaValidation:
    def test_missing_required_field_raises_input_validation_error(self) -> None:
        payload = _valid_payload()
        del payload["request_id"]
        with pytest.raises(InputValidationError):
            InputValidator().validate(payload)

    def test_extra_field_raises_input_validation_error(self) -> None:
        payload = _valid_payload()
        payload["unexpected_field"] = "hack"
        with pytest.raises(InputValidationError):
            InputValidator().validate(payload)

    def test_invalid_locale_raises_input_validation_error(self) -> None:
        payload = _valid_payload()
        payload["channel_context"]["locale"] = "INVALID!"
        with pytest.raises(InputValidationError):
            InputValidator().validate(payload)

    def test_empty_raw_text_raises_input_validation_error(self) -> None:
        payload = _valid_payload()
        payload["user_turn"]["raw_text"] = ""
        with pytest.raises(InputValidationError):
            InputValidator().validate(payload)


class TestRawTextPreservation:
    def test_raw_text_preserves_spaces_case_and_punctuation(self) -> None:
        text = "  ¿Cuánto TENGO en mi Cuenta?!  "
        payload = _valid_payload()
        payload["user_turn"]["raw_text"] = text
        result = InputValidator().validate(payload)
        assert result.raw_text == text


class TestSecurityAndIsolation:
    def test_subject_token_not_in_exception_messages(self) -> None:
        payload = _valid_payload()
        del payload["conversation_id"]
        try:
            InputValidator().validate(payload)
        except InputValidationError as e:
            assert "tok-secret-abc" not in str(e)
            assert "tok-secret-abc" not in str(e.internal_cause)

    def test_module_has_no_keyword_routing(self) -> None:
        """The validator module must not contain intent detection logic."""
        source_path = Path(inspect.getfile(InputValidator))
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        source_text = source_path.read_text(encoding="utf-8").lower()
        # No regex-based routing
        assert "re.match" not in source_text
        assert "re.search" not in source_text
        # No keyword lists
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and len(node.elts) > 3:
                # Ensure no list of string literals that look like intents
                str_elts = [
                    e for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                assert len(str_elts) < 5, "Suspicious keyword list found"

    def test_validator_does_not_invoke_context_providers(self) -> None:
        """InputValidator must not import or call context providers."""
        source_path = Path(inspect.getfile(InputValidator))
        source_text = source_path.read_text(encoding="utf-8")
        assert "ContextProvider" not in source_text
        assert "PortfolioContext" not in source_text
        assert "ConversationContext" not in source_text
