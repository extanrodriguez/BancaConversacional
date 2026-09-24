"""Unit tests for build_contextual_openai_output_schema.

Validates that entity enums are derived dynamically from the portfolio context
and that the canonical schema and context are never mutated.
No API calls. No model invocations.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from run_openai_semantic_preflight import (  # noqa: E402
    build_contextual_openai_output_schema,
    load_canonical_turn_interpretation_schema,
)


def _load_canonical() -> dict[str, Any]:
    return load_canonical_turn_interpretation_schema()


def _make_context(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    return {"products": products}


def _get_detected_entities_properties(schema: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = (
        schema.get("$defs", {}).get("DetectedEntities", {}).get("properties", {})
    )
    return result


class TestContextualOpenAISchema:
    """Tests for build_contextual_openai_output_schema."""

    def test_contextual_schema_does_not_mutate_canonical_schema(self) -> None:
        """Canonical schema must remain unchanged after building contextual."""
        canonical = _load_canonical()
        canonical_before = json.dumps(canonical, sort_keys=True)

        context = _make_context(
            [
                {"product_ref": "X1", "currency": "EUR"},
                {"product_ref": "X2", "currency": "USD"},
            ]
        )
        build_contextual_openai_output_schema(canonical, context)

        canonical_after = json.dumps(canonical, sort_keys=True)
        assert canonical_before == canonical_after

    def test_contextual_schema_does_not_mutate_product_context(self) -> None:
        """Synthetic context must remain unchanged."""
        canonical = _load_canonical()
        context = _make_context(
            [
                {"product_ref": "A1", "currency": "GBP"},
                {"product_ref": "A2", "currency": "GBP"},
            ]
        )
        context_before = copy.deepcopy(context)

        build_contextual_openai_output_schema(canonical, context)

        assert context == context_before

    def test_product_reference_enums_are_derived_from_context(self) -> None:
        """product_ref enums come from context, not hardcoded."""
        canonical = _load_canonical()
        context = _make_context(
            [
                {"product_ref": "CTX-CHECK-9", "currency": "EUR"},
                {"product_ref": "CTX-SAVE-4", "currency": "EUR"},
            ]
        )

        schema = build_contextual_openai_output_schema(canonical, context)
        props = _get_detected_entities_properties(schema)

        expected_refs = ["CTX-CHECK-9", "CTX-SAVE-4", None]

        assert props["account_ref"]["enum"] == expected_refs
        assert props["source_account_ref"]["enum"] == expected_refs
        assert props["destination_account_ref"]["enum"] == expected_refs

    def test_currency_enum_is_derived_from_context(self) -> None:
        """Currency enum derives from unique currencies in context."""
        canonical = _load_canonical()
        context = _make_context(
            [
                {"product_ref": "P1", "currency": "USD"},
                {"product_ref": "P2", "currency": "EUR"},
                {"product_ref": "P3", "currency": "USD"},
            ]
        )

        schema = build_contextual_openai_output_schema(canonical, context)
        props = _get_detected_entities_properties(schema)

        # Sorted unique currencies + null
        assert props["currency"]["enum"] == ["EUR", "USD", None]

    def test_null_remains_allowed_for_optional_entity_fields(self) -> None:
        """Null must be in the enum for optional entity fields."""
        canonical = _load_canonical()
        context = _make_context([{"product_ref": "ONLY1", "currency": "JPY"}])

        schema = build_contextual_openai_output_schema(canonical, context)
        props = _get_detected_entities_properties(schema)

        assert None in props["account_ref"]["enum"]
        assert None in props["source_account_ref"]["enum"]
        assert None in props["destination_account_ref"]["enum"]
        assert None in props["currency"]["enum"]

    def test_unknown_product_refs_and_currencies_not_in_contextual_enums(
        self,
    ) -> None:
        """Values not in context must not appear in the enums."""
        canonical = _load_canonical()
        context = _make_context(
            [
                {"product_ref": "VALID1", "currency": "CHF"},
                {"product_ref": "VALID2", "currency": "CHF"},
            ]
        )

        schema = build_contextual_openai_output_schema(canonical, context)
        props = _get_detected_entities_properties(schema)

        # These should NOT be in the enums
        assert "COR001" not in props["account_ref"]["enum"]
        assert "AHO001" not in props["source_account_ref"]["enum"]
        assert "DOP" not in props["currency"]["enum"]
        assert "USD" not in props["currency"]["enum"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
