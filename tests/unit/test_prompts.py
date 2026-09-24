"""T04 — Prompt JSON validation tests."""

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
SCHEMA_PATH = PROMPTS_DIR / "schemas" / "agent_prompt.schema.json"
PROMPT_PATH = PROMPTS_DIR / "turn-decision-agent" / "1.0.0" / "prompt.json"
CURRENT_PATH = PROMPTS_DIR / "turn-decision-agent" / "current.json"

# Patterns for secret/PII scanning
_SECRET_PATTERNS = [
    re.compile(r"(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY)", re.IGNORECASE),
    re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9+/]{40,}\b"),  # base64-like long strings
    re.compile(r"\b\d{12}\b"),  # AWS account IDs
    re.compile(r"(customer_id|subject_token)\s*[:=]\s*\".+\"", re.IGNORECASE),
]


@pytest.fixture()
def prompt_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def prompt_data() -> dict:
    return json.loads(PROMPT_PATH.read_text(encoding="utf-8"))


class TestPromptSchemaValid:
    def test_schema_is_valid_draft_2020_12(self, prompt_schema: dict) -> None:
        Draft202012Validator.check_schema(prompt_schema)

    def test_schema_has_dollar_schema(self, prompt_schema: dict) -> None:
        assert "$schema" in prompt_schema
        assert prompt_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_schema_has_dollar_id(self, prompt_schema: dict) -> None:
        assert "$id" in prompt_schema


class TestPromptValidatesAgainstSchema:
    def test_prompt_validates(self, prompt_schema: dict, prompt_data: dict) -> None:
        """CA-24: prompt JSON validates against agent_prompt.schema.json."""
        validator = Draft202012Validator(prompt_schema, format_checker=FormatChecker())
        validator.validate(prompt_data)

    def test_prompt_version_is_semver(self, prompt_data: dict) -> None:
        """CA-26: prompt_version matches semver."""
        assert re.match(r"^\d+\.\d+\.\d+$", prompt_data["prompt_version"])

    def test_prompt_references_output_schema(self, prompt_data: dict) -> None:
        """CA-28: prompt references an output_schema."""
        assert prompt_data["contracts"]["output_schema"]
        assert "turn_interpretation" in prompt_data["contracts"]["output_schema"]

    def test_prompt_references_evaluation_suite(self, prompt_data: dict) -> None:
        """CA-29: prompt references a suite_id."""
        assert prompt_data["evaluation"]["suite_id"]
        assert prompt_data["evaluation"]["dataset_ref"]


class TestPromptNoSecrets:
    def test_no_secrets_or_pii(self, prompt_data: dict) -> None:
        """CA-30: scan for secrets and PII."""
        content = json.dumps(prompt_data)
        for pattern in _SECRET_PATTERNS:
            match = pattern.search(content)
            assert match is None, f"Secret/PII pattern found: {match.group()}"

    def test_no_credentials_in_instructions(self, prompt_data: dict) -> None:
        instructions = json.dumps(prompt_data["instructions"])
        forbidden = ["password", "secret", "api_key", "AWS_", "bearer"]
        for word in forbidden:
            assert word.lower() not in instructions.lower()


class TestPromptNegative:
    def test_extra_field_rejected(self, prompt_schema: dict, prompt_data: dict) -> None:
        data = {**prompt_data, "extra": "bad"}
        validator = Draft202012Validator(prompt_schema, format_checker=FormatChecker())
        assert not validator.is_valid(data)

    def test_missing_required_field(self, prompt_schema: dict, prompt_data: dict) -> None:
        data = {k: v for k, v in prompt_data.items() if k != "instructions"}
        validator = Draft202012Validator(prompt_schema, format_checker=FormatChecker())
        assert not validator.is_valid(data)

    def test_invalid_prompt_version(self, prompt_schema: dict, prompt_data: dict) -> None:
        data = {**prompt_data, "prompt_version": "v1.0"}
        validator = Draft202012Validator(prompt_schema, format_checker=FormatChecker())
        assert not validator.is_valid(data)

    def test_invalid_status(self, prompt_schema: dict, prompt_data: dict) -> None:
        data = {**prompt_data, "status": "active"}
        validator = Draft202012Validator(prompt_schema, format_checker=FormatChecker())
        assert not validator.is_valid(data)


class TestCurrentJson:
    def test_current_only_references_version(self) -> None:
        """current.json must only contain active_version reference."""
        data = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
        assert data == {"active_version": "1.2.0"}
        assert len(data) == 1


class TestNoPromptInCode:
    def test_no_full_prompt_embedded_in_source(self) -> None:
        """CA-25: no production prompt embedded as string in code."""
        src_dir = Path(__file__).parent.parent.parent / "src"
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            # A full prompt would contain the role instruction
            assert "Interpretar turnos bancarios" not in content, (
                f"Prompt content found embedded in {py_file}"
            )
