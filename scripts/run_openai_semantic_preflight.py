"""OpenAI Responses API semantic preflight — validates model interpretation.

EARLY_MODEL_SEMANTIC_PREFLIGHT
NO_AGENT_FRAMEWORK
NO_RAG
NOT_FINAL_COGNITIVE_ACCEPTANCE
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


def load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def load_canonical_turn_interpretation_schema() -> dict[str, Any]:
    """Load the canonical schema without modification."""
    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

    schema = json.loads(
        (ROOT / "schemas" / "turn_interpretation.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return schema  # type: ignore[no-any-return]


def build_openai_output_schema(canonical_schema: dict[str, Any]) -> dict[str, Any]:
    """Create a deep copy adapted for OpenAI strict structured output."""
    schema = copy.deepcopy(canonical_schema)
    _adapt_for_openai_strict(schema)
    return schema


def build_contextual_openai_output_schema(
    canonical_schema: dict[str, Any],
    synthetic_context: dict[str, Any],
) -> dict[str, Any]:
    """Build an OpenAI output schema with entity enums derived from context.

    Limits product_ref and currency values to those present in the authorized
    portfolio context. Does NOT interpret raw_text, detect intent, or select
    routes. The AI retains full responsibility for semantic interpretation.

    Never modifies canonical_schema or synthetic_context.
    """
    schema = build_openai_output_schema(canonical_schema)

    # Derive authorized values from context
    products = synthetic_context.get("products", [])
    product_refs = sorted({p["product_ref"] for p in products if "product_ref" in p})
    currencies = sorted({p["currency"] for p in products if "currency" in p})

    # Locate DetectedEntities in schema
    defs = schema.get("$defs", {})
    detected_entities = defs.get("DetectedEntities", {})
    properties = detected_entities.get("properties", {})

    # Apply enum constraints for reference fields
    ref_fields = ("account_ref", "source_account_ref", "destination_account_ref")
    for field in ref_fields:
        if field in properties:
            properties[field] = {"enum": product_refs + [None]}

    # Apply enum constraint for currency
    if "currency" in properties:
        properties["currency"] = {"enum": currencies + [None]}

    return schema


def _adapt_for_openai_strict(obj: Any) -> None:
    """Recursively adapt schema for OpenAI strict mode requirements."""
    if isinstance(obj, dict):
        obj.pop("uniqueItems", None)
        obj.pop("minItems", None)
        obj.pop("minLength", None)
        obj.pop("maxLength", None)
        obj.pop("minimum", None)
        obj.pop("maximum", None)
        obj.pop("pattern", None)
        # OpenAI strict requires all properties listed in required
        if "properties" in obj and "additionalProperties" in obj:
            obj["required"] = list(obj["properties"].keys())
        for v in obj.values():
            _adapt_for_openai_strict(v)
    elif isinstance(obj, list):
        for item in obj:
            _adapt_for_openai_strict(item)


def load_prompt_via_registry() -> tuple[str, str, str]:
    """Load prompt via PromptRegistry, return (instructions_text, prompt_id, prompt_version)."""
    from genesis_cognitive.prompts.prompt_registry import PromptRegistry

    registry = PromptRegistry(ROOT / "prompts", ROOT / "schemas")
    pv = registry.get_current("turn-decision-agent")

    instructions = (
        f"{pv.instructions.role}\n\n"
        "Objectives:\n" + "\n".join(f"- {o}" for o in pv.instructions.objectives) + "\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in pv.instructions.prohibitions)
    )
    return instructions, pv.prompt_id, pv.prompt_version


def build_capability_descriptions() -> str:
    """Build capability catalog description for model context."""
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog

    catalog = CapabilityCatalog()
    descriptions = []
    for m in catalog.get_manifests():
        descriptions.append(
            {
                "intent_id": m.intent_ids[0] if m.intent_ids else "",
                "capability_candidate": m.capability_candidate,
                "selected_route": str(m.selected_route.value) if m.selected_route else "",
                "domain": m.domain,
                "required_entities": list(m.required_entities),
                "optional_entities": list(m.optional_entities),
            }
        )
    return json.dumps(descriptions, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Case: business-knowledge
# ---------------------------------------------------------------------------


def run_business_knowledge_case(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
) -> dict[str, Any]:
    """Run the business-knowledge case."""
    user_input = "¿Cuáles son los requisitos para solicitar un préstamo hipotecario?"

    capabilities = build_capability_descriptions()

    system_content = (
        f"{instructions}\n\n"
        f"Available capabilities:\n{capabilities}\n\n"
        "Allowed detected_entities keys: account_ref, source_account_ref, "
        "destination_account_ref, amount, currency, knowledge_topic.\n\n"
        "The user has no personal products in this context.\n"
        "Do not answer the question. Only interpret the intent, entities, and route.\n"
        "The sequence field starts at 1 for the first action.\n"
        "Respond with a JSON object matching the provided schema."
    )

    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"

    payload: dict[str, Any] = {
        "model": model,
        "instructions": system_content,
        "input": user_input,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "TurnInterpretation",
                "schema": openai_schema,
                "strict": True,
            }
        },
        "store": False,
        "max_output_tokens": 512,
    }

    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{base_url}/responses",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60.0,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        return {"pass": False, "error": f"NETWORK_ERROR: {type(e).__name__}"}

    latency_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return {"pass": False, "error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}

    data = resp.json()
    if data.get("status") != "completed":
        return {"pass": False, "error": f"status={data.get('status')}", "latency_ms": latency_ms}

    output_text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text", "")

    if not output_text:
        return {"pass": False, "error": "no output_text", "latency_ms": latency_ms}

    try:
        interpretation = json.loads(output_text)
    except json.JSONDecodeError:
        return {"pass": False, "error": "invalid JSON from model", "latency_ms": latency_ms}

    # Validate 1: canonical JSON Schema
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(canonical_schema, format_checker=FormatChecker())
    schema_errors = list(validator.iter_errors(interpretation))
    canonical_json_schema_valid = len(schema_errors) == 0

    # Validate 2: Pydantic
    from genesis_cognitive.decision.types import TurnInterpretation

    pydantic_valid = False
    ti = None
    try:
        ti = TurnInterpretation.model_validate_json(output_text)
        pydantic_valid = True
    except Exception:
        pass

    # Validate 3: CapabilityCatalog
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError

    catalog_valid = False
    if ti is not None:
        try:
            catalog = CapabilityCatalog()
            catalog.validate_interpretation(ti)
            catalog_valid = True
        except InvalidModelOutputError:
            pass

    # Check expected values
    passed = True
    actions = interpretation.get("actions", [])
    mode = interpretation.get("mode")

    if mode != "SINGLE":
        passed = False
    if len(actions) != 1:
        passed = False
    if actions:
        a = actions[0]
        if a.get("intent_id") != "BUSINESS_KNOWLEDGE_QUERY":
            passed = False
        if a.get("capability_candidate") != "BUSINESS_KNOWLEDGE":
            passed = False
        if a.get("selected_route") != "BUSINESS_RAG":
            passed = False
        kt = (a.get("detected_entities") or {}).get("knowledge_topic")
        if not kt:
            passed = False
        if a.get("missing_requirements") != []:
            passed = False
        if a.get("depends_on") != []:
            passed = False
    else:
        passed = False

    if interpretation.get("clarifications") != []:
        passed = False
    if interpretation.get("unsupported_segments") != []:
        passed = False

    if not canonical_json_schema_valid or not pydantic_valid or not catalog_valid:
        passed = False

    usage = data.get("usage", {})

    return {
        "pass": passed,
        "input": user_input,
        "model": model,
        "latency_ms": round(latency_ms),
        "usage": usage,
        "canonical_json_schema_valid": canonical_json_schema_valid,
        "pydantic_valid": pydantic_valid,
        "catalog_valid": catalog_valid,
        "turn_interpretation": interpretation,
        "mode": mode,
        "intent_id": actions[0].get("intent_id") if actions else None,
        "capability_candidate": actions[0].get("capability_candidate") if actions else None,
        "selected_route": actions[0].get("selected_route") if actions else None,
        "knowledge_topic": (actions[0].get("detected_entities") or {}).get("knowledge_topic")
        if actions
        else None,
    }


# ---------------------------------------------------------------------------
# Case: account-balance-context
# ---------------------------------------------------------------------------


def run_account_balance_case(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
) -> dict[str, Any]:
    """Run the account-balance-context case with synthetic product context."""
    user_input = "¿Cuánto tengo disponible en mi cuenta principal?"

    synthetic_context = {
        "products": [
            {
                "product_ref": "COR001",
                "product_type": "CHECKING",
                "label": "Cuenta corriente",
                "alias": "cuenta principal",
                "currency": "DOP",
                "operational_state": "ACTIVE",
                "recent_balance": "12500.75",
                "known_reserved_amount": "500.00",
            }
        ]
    }

    capabilities = build_capability_descriptions()

    system_content = (
        f"{instructions}\n\n"
        f"Available capabilities:\n{capabilities}\n\n"
        "Allowed detected_entities keys: account_ref, source_account_ref, "
        "destination_account_ref, amount, currency, knowledge_topic.\n\n"
        f"Authenticated customer products:\n"
        f"{json.dumps(synthetic_context['products'], indent=2, ensure_ascii=False)}\n\n"
        "The product_ref can be used to resolve references like aliases.\n"
        "Do not answer the balance question. Only interpret the intent, entities, and route.\n"
        "Do not invent products that are not in the context.\n"
        "The sequence field starts at 1 for the first action.\n"
        "Respond with a JSON object matching the provided schema."
    )

    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"

    payload: dict[str, Any] = {
        "model": model,
        "instructions": system_content,
        "input": user_input,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "TurnInterpretation",
                "schema": openai_schema,
                "strict": True,
            }
        },
        "store": False,
        "max_output_tokens": 512,
    }

    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{base_url}/responses",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=60.0,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        return {"pass": False, "error": f"NETWORK_ERROR: {type(e).__name__}"}

    latency_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return {"pass": False, "error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}

    data = resp.json()
    if data.get("status") != "completed":
        return {"pass": False, "error": f"status={data.get('status')}", "latency_ms": latency_ms}

    output_text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text", "")

    if not output_text:
        return {"pass": False, "error": "no output_text", "latency_ms": latency_ms}

    try:
        interpretation = json.loads(output_text)
    except json.JSONDecodeError:
        return {"pass": False, "error": "invalid JSON", "latency_ms": latency_ms}

    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(canonical_schema, format_checker=FormatChecker())
    canonical_json_schema_valid = len(list(validator.iter_errors(interpretation))) == 0

    from genesis_cognitive.decision.types import TurnInterpretation

    pydantic_valid = False
    ti = None
    try:
        ti = TurnInterpretation.model_validate_json(output_text)
        pydantic_valid = True
    except Exception:
        pass

    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError

    catalog_valid = False
    if ti is not None:
        try:
            CapabilityCatalog().validate_interpretation(ti)
            catalog_valid = True
        except InvalidModelOutputError:
            pass

    # Evaluate expectations
    passed = True
    actions = interpretation.get("actions", [])
    mode = interpretation.get("mode")

    if mode != "SINGLE":
        passed = False
    if len(actions) != 1:
        passed = False

    resolved_ref = None
    if actions:
        a = actions[0]
        if a.get("intent_id") != "ACCOUNT_BALANCE_READ":
            passed = False
        if a.get("capability_candidate") != "ACCOUNT_BALANCE":
            passed = False
        if a.get("selected_route") != "PERSONAL_READ":
            passed = False
        entities = a.get("detected_entities") or {}
        resolved_ref = entities.get("account_ref")
        if resolved_ref != "COR001":
            passed = False
        # Other entities must be null
        for key in (
            "source_account_ref",
            "destination_account_ref",
            "amount",
            "currency",
            "knowledge_topic",
        ):
            if entities.get(key) is not None:
                passed = False
        if a.get("missing_requirements") != []:
            passed = False
        if a.get("depends_on") != []:
            passed = False
    else:
        passed = False

    if interpretation.get("clarifications") != []:
        passed = False
    if interpretation.get("unsupported_segments") != []:
        passed = False
    if not canonical_json_schema_valid or not pydantic_valid or not catalog_valid:
        passed = False

    usage = data.get("usage", {})

    return {
        "pass": passed,
        "input": user_input,
        "synthetic_context": synthetic_context,
        "model": model,
        "latency_ms": round(latency_ms),
        "usage": usage,
        "canonical_json_schema_valid": canonical_json_schema_valid,
        "pydantic_valid": pydantic_valid,
        "catalog_valid": catalog_valid,
        "turn_interpretation": interpretation,
        "mode": mode,
        "intent_id": actions[0].get("intent_id") if actions else None,
        "capability_candidate": actions[0].get("capability_candidate") if actions else None,
        "selected_route": actions[0].get("selected_route") if actions else None,
        "resolved_account_ref": resolved_ref,
    }


# ---------------------------------------------------------------------------
# Case: transfer-complete-context
# ---------------------------------------------------------------------------


def run_transfer_complete_case(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
) -> dict[str, Any]:
    """Run the transfer-complete-context case with two synthetic products."""
    user_input = "Pasa 500 pesos de mi cuenta principal a mis ahorros."

    synthetic_context: dict[str, Any] = {
        "products": [
            {
                "product_ref": "COR001",
                "product_type": "CHECKING",
                "label": "Cuenta corriente",
                "alias": "cuenta principal",
                "currency": "DOP",
                "operational_state": "ACTIVE",
                "recent_balance": "12500.75",
                "known_reserved_amount": "500.00",
            },
            {
                "product_ref": "AHO001",
                "product_type": "SAVINGS",
                "label": "Cuenta de ahorros",
                "alias": "mis ahorros",
                "currency": "DOP",
                "operational_state": "ACTIVE",
                "recent_balance": "3200.25",
                "known_reserved_amount": "0",
            },
        ]
    }

    capabilities = build_capability_descriptions()

    system_content = (
        f"{instructions}\n\n"
        f"Available capabilities:\n{capabilities}\n\n"
        "Allowed detected_entities keys: account_ref, source_account_ref, "
        "destination_account_ref, amount, currency, knowledge_topic.\n\n"
        "Authenticated customer products:\n"
        f"{json.dumps(synthetic_context['products'], indent=2, ensure_ascii=False)}\n\n"
        "Both products belong to the authenticated customer.\n"
        "Aliases can be resolved using product_ref.\n"
        "In this context, 'pesos' corresponds to DOP.\n"
        "Interpret intent, entities, and route only.\n"
        "Do not execute or confirm that a transfer was completed.\n"
        "Do not invent products that are not in the context.\n"
        "The sequence field starts at 1 for the first action.\n"
        "The amount field must be a decimal string like '500' or '500.00'.\n"
        "Respond with a JSON object matching the provided schema."
    )

    contextual_schema = build_contextual_openai_output_schema(canonical_schema, synthetic_context)

    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"

    payload: dict[str, Any] = {
        "model": model,
        "instructions": system_content,
        "input": user_input,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "TurnInterpretation",
                "schema": contextual_schema,
                "strict": True,
            }
        },
        "store": False,
        "max_output_tokens": 512,
    }

    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{base_url}/responses",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        return {"pass": False, "error": f"NETWORK_ERROR: {type(e).__name__}"}

    latency_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return {"pass": False, "error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}

    data = resp.json()
    if data.get("status") != "completed":
        return {
            "pass": False,
            "error": f"status={data.get('status')}",
            "latency_ms": latency_ms,
        }

    output_text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text", "")

    if not output_text:
        return {"pass": False, "error": "no output_text", "latency_ms": latency_ms}

    try:
        interpretation = json.loads(output_text)
    except json.JSONDecodeError:
        return {"pass": False, "error": "invalid JSON", "latency_ms": latency_ms}

    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(canonical_schema, format_checker=FormatChecker())
    canonical_json_schema_valid = len(list(validator.iter_errors(interpretation))) == 0

    from genesis_cognitive.decision.types import TurnInterpretation

    pydantic_valid = False
    ti = None
    try:
        ti = TurnInterpretation.model_validate_json(output_text)
        pydantic_valid = True
    except Exception:
        pass

    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError

    catalog_valid = False
    if ti is not None:
        try:
            CapabilityCatalog().validate_interpretation(ti)
            catalog_valid = True
        except InvalidModelOutputError:
            pass

    # Evaluate expectations
    passed = True
    actions = interpretation.get("actions", [])
    mode = interpretation.get("mode")

    if mode != "SINGLE":
        passed = False
    if len(actions) != 1:
        passed = False

    resolved_source = None
    resolved_dest = None
    resolved_amount = None
    resolved_currency = None

    if actions:
        a = actions[0]
        if a.get("intent_id") != "TRANSFER_BETWEEN_OWN_ACCOUNTS":
            passed = False
        if a.get("capability_candidate") != "TRANSFER":
            passed = False
        if a.get("selected_route") != "TRANSFER_CONTRACT_BUILDER":
            passed = False
        entities = a.get("detected_entities") or {}
        resolved_source = entities.get("source_account_ref")
        resolved_dest = entities.get("destination_account_ref")
        resolved_amount = entities.get("amount")
        resolved_currency = entities.get("currency")

        if resolved_source != "COR001":
            passed = False
        if resolved_dest != "AHO001":
            passed = False
        # amount must be decimal equivalent to "500"
        if resolved_amount not in ("500", "500.00", "500.0"):
            passed = False
        if resolved_currency != "DOP":
            passed = False
        # These must be null
        if entities.get("account_ref") is not None:
            passed = False
        if entities.get("knowledge_topic") is not None:
            passed = False
        if a.get("missing_requirements") != []:
            passed = False
        if a.get("depends_on") != []:
            passed = False
    else:
        passed = False

    if interpretation.get("clarifications") != []:
        passed = False
    if interpretation.get("unsupported_segments") != []:
        passed = False
    if not canonical_json_schema_valid or not pydantic_valid or not catalog_valid:
        passed = False

    # Currency policy decision
    currency_decision = evaluate_transfer_currency_policy(interpretation, synthetic_context)
    if currency_decision is not TransferCurrencyDecision.SAME_CURRENCY_TRANSFER:
        passed = False

    usage = data.get("usage", {})

    return {
        "pass": passed,
        "input": user_input,
        "synthetic_context": synthetic_context,
        "model": model,
        "latency_ms": round(latency_ms),
        "usage": usage,
        "canonical_json_schema_valid": canonical_json_schema_valid,
        "pydantic_valid": pydantic_valid,
        "catalog_valid": catalog_valid,
        "currency_policy_decision": currency_decision.value,
        "turn_interpretation": interpretation,
        "mode": mode,
        "intent_id": actions[0].get("intent_id") if actions else None,
        "capability_candidate": actions[0].get("capability_candidate") if actions else None,
        "selected_route": actions[0].get("selected_route") if actions else None,
        "resolved_source_account_ref": resolved_source,
        "resolved_destination_account_ref": resolved_dest,
        "resolved_amount": resolved_amount,
        "resolved_currency": resolved_currency,
    }


# ---------------------------------------------------------------------------
# Case: multi-dependent-transfer-balance
# ---------------------------------------------------------------------------


def run_multi_dependent_case(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
) -> dict[str, Any]:
    """Run the multi-dependent-transfer-balance case."""
    user_input = (
        "Transfiere 500 pesos de mi cuenta principal a mis ahorros y, "
        "cuando termine, dime cuánto quedó disponible en mi cuenta principal."
    )

    synthetic_context: dict[str, Any] = {
        "products": [
            {
                "product_ref": "COR001",
                "product_type": "CHECKING",
                "label": "Cuenta corriente",
                "alias": "cuenta principal",
                "currency": "DOP",
                "operational_state": "ACTIVE",
                "recent_balance": "12500.75",
                "known_reserved_amount": "500.00",
            },
            {
                "product_ref": "AHO001",
                "product_type": "SAVINGS",
                "label": "Cuenta de ahorros",
                "alias": "mis ahorros",
                "currency": "DOP",
                "operational_state": "ACTIVE",
                "recent_balance": "3200.25",
                "known_reserved_amount": "0",
            },
        ]
    }

    capabilities = build_capability_descriptions()

    system_content = (
        f"{instructions}\n\n"
        f"Available capabilities:\n{capabilities}\n\n"
        "Allowed detected_entities keys: account_ref, source_account_ref, "
        "destination_account_ref, amount, currency, knowledge_topic.\n\n"
        "Authenticated customer products:\n"
        f"{json.dumps(synthetic_context['products'], indent=2, ensure_ascii=False)}\n\n"
        "Both products belong to the authenticated customer.\n"
        "Aliases can be resolved using product_ref.\n"
        "In this context, 'pesos' corresponds to DOP.\n"
        "Interpret all requested actions.\n"
        "Preserve causal order between actions.\n"
        "The sequence field starts at 1 and increments per action.\n"
        "depends_on contains predecessor sequences that must complete first.\n"
        "Do not execute or confirm that any operation completed.\n"
        "Do not invent products or post-operation balances.\n"
        "The amount field must be a decimal string like '500' or '500.00'.\n"
        "Respond with a JSON object matching the provided schema."
    )

    contextual_schema = build_contextual_openai_output_schema(canonical_schema, synthetic_context)

    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"

    payload: dict[str, Any] = {
        "model": model,
        "instructions": system_content,
        "input": user_input,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "TurnInterpretation",
                "schema": contextual_schema,
                "strict": True,
            }
        },
        "store": False,
        "max_output_tokens": 768,
    }

    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{base_url}/responses",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        return {"pass": False, "error": f"NETWORK_ERROR: {type(e).__name__}"}

    latency_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return {"pass": False, "error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}

    data = resp.json()
    if data.get("status") != "completed":
        return {
            "pass": False,
            "error": f"status={data.get('status')}",
            "latency_ms": latency_ms,
        }

    output_text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text", "")

    if not output_text:
        return {"pass": False, "error": "no output_text", "latency_ms": latency_ms}

    try:
        interpretation = json.loads(output_text)
    except json.JSONDecodeError:
        return {"pass": False, "error": "invalid JSON", "latency_ms": latency_ms}

    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(canonical_schema, format_checker=FormatChecker())
    canonical_json_schema_valid = len(list(validator.iter_errors(interpretation))) == 0

    from genesis_cognitive.decision.types import TurnInterpretation

    pydantic_valid = False
    ti = None
    try:
        ti = TurnInterpretation.model_validate_json(output_text)
        pydantic_valid = True
    except Exception:
        pass

    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError

    catalog_valid = False
    if ti is not None:
        try:
            CapabilityCatalog().validate_interpretation(ti)
            catalog_valid = True
        except InvalidModelOutputError:
            pass

    # Evaluate expectations
    passed = True
    actions = interpretation.get("actions", [])
    mode = interpretation.get("mode")

    if mode != "MULTI_DEPENDENT":
        passed = False
    if len(actions) != 2:
        passed = False

    # ACTION 1 — Transfer
    if len(actions) >= 1:
        a1 = actions[0]
        if a1.get("sequence") != 1:
            passed = False
        if a1.get("intent_id") != "TRANSFER_BETWEEN_OWN_ACCOUNTS":
            passed = False
        if a1.get("capability_candidate") != "TRANSFER":
            passed = False
        if a1.get("selected_route") != "TRANSFER_CONTRACT_BUILDER":
            passed = False
        e1 = a1.get("detected_entities") or {}
        if e1.get("source_account_ref") != "COR001":
            passed = False
        if e1.get("destination_account_ref") != "AHO001":
            passed = False
        if e1.get("amount") not in ("500", "500.00", "500.0"):
            passed = False
        if e1.get("currency") != "DOP":
            passed = False
        if e1.get("account_ref") is not None:
            passed = False
        if e1.get("knowledge_topic") is not None:
            passed = False
        if a1.get("missing_requirements") != []:
            passed = False
        if a1.get("depends_on") != []:
            passed = False
    else:
        passed = False

    # ACTION 2 — Balance query
    if len(actions) >= 2:
        a2 = actions[1]
        if a2.get("sequence") != 2:
            passed = False
        if a2.get("intent_id") != "ACCOUNT_BALANCE_READ":
            passed = False
        if a2.get("capability_candidate") != "ACCOUNT_BALANCE":
            passed = False
        if a2.get("selected_route") != "PERSONAL_READ":
            passed = False
        e2 = a2.get("detected_entities") or {}
        if e2.get("account_ref") != "COR001":
            passed = False
        if e2.get("source_account_ref") is not None:
            passed = False
        if e2.get("destination_account_ref") is not None:
            passed = False
        if e2.get("amount") is not None:
            passed = False
        if e2.get("currency") is not None:
            passed = False
        if e2.get("knowledge_topic") is not None:
            passed = False
        if a2.get("missing_requirements") != []:
            passed = False
        if a2.get("depends_on") != [1]:
            passed = False
    else:
        passed = False

    if interpretation.get("clarifications") != []:
        passed = False
    if interpretation.get("unsupported_segments") != []:
        passed = False
    if not canonical_json_schema_valid or not pydantic_valid or not catalog_valid:
        passed = False

    # Currency policy on first action (transfer)
    transfer_interpretation = {
        "actions": [actions[0]] if actions else [],
    }
    currency_decision = evaluate_transfer_currency_policy(
        transfer_interpretation, synthetic_context
    )
    if currency_decision is not TransferCurrencyDecision.SAME_CURRENCY_TRANSFER:
        passed = False

    # DAG validation
    dag_valid = (
        len(actions) == 2
        and actions[0].get("depends_on") == []
        and actions[1].get("depends_on") == [1]
    )
    if not dag_valid:
        passed = False

    usage = data.get("usage", {})

    return {
        "pass": passed,
        "input": user_input,
        "synthetic_context": synthetic_context,
        "model": model,
        "latency_ms": round(latency_ms),
        "usage": usage,
        "canonical_json_schema_valid": canonical_json_schema_valid,
        "pydantic_valid": pydantic_valid,
        "catalog_valid": catalog_valid,
        "currency_policy_decision": currency_decision.value,
        "dag_valid": dag_valid,
        "turn_interpretation": interpretation,
        "mode": mode,
        "action_count": len(actions),
    }


# ---------------------------------------------------------------------------
# Case: clarification-missing-source
# ---------------------------------------------------------------------------


def run_clarification_missing_source_case(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
) -> dict[str, Any]:
    """Run the clarification-missing-source case."""
    user_input = "Transfiere 500 pesos a mis ahorros."

    synthetic_context: dict[str, Any] = {
        "products": [
            {
                "product_ref": "COR001",
                "product_type": "CHECKING",
                "label": "Cuenta corriente",
                "alias": "cuenta principal",
                "currency": "DOP",
                "operational_state": "ACTIVE",
                "recent_balance": "12500.75",
                "known_reserved_amount": "500.00",
            },
            {
                "product_ref": "AHO001",
                "product_type": "SAVINGS",
                "label": "Cuenta de ahorros",
                "alias": "mis ahorros",
                "currency": "DOP",
                "operational_state": "ACTIVE",
                "recent_balance": "3200.25",
                "known_reserved_amount": "0",
            },
        ]
    }

    capabilities = build_capability_descriptions()

    system_content = (
        f"{instructions}\n\n"
        f"Available capabilities:\n{capabilities}\n\n"
        "Allowed detected_entities keys: account_ref, source_account_ref, "
        "destination_account_ref, amount, currency, knowledge_topic.\n\n"
        "Authenticated customer products:\n"
        f"{json.dumps(synthetic_context['products'], indent=2, ensure_ascii=False)}\n\n"
        "Both products belong to the authenticated customer.\n"
        "Aliases can be resolved using product_ref.\n"
        "In this context, 'pesos' corresponds to DOP.\n"
        "Preserve already-known entities in the action.\n"
        "When a required entity is missing, formulate a minimal clarification.\n"
        "Do not infer a mandatory financial account just because another product "
        "is available in the context.\n"
        "Do not re-ask for amount, currency, or destination if already resolved.\n"
        "The sequence field starts at 1.\n"
        "Do not execute or confirm any operation.\n"
        "Respond with a JSON object matching the provided schema."
    )

    contextual_schema = build_contextual_openai_output_schema(canonical_schema, synthetic_context)

    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"

    payload: dict[str, Any] = {
        "model": model,
        "instructions": system_content,
        "input": user_input,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "TurnInterpretation",
                "schema": contextual_schema,
                "strict": True,
            }
        },
        "store": False,
        "max_output_tokens": 768,
    }

    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{base_url}/responses",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        return {"pass": False, "error": f"NETWORK_ERROR: {type(e).__name__}"}

    latency_ms = (time.perf_counter() - start) * 1000

    if resp.status_code != 200:
        return {"pass": False, "error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}

    data = resp.json()
    if data.get("status") != "completed":
        return {
            "pass": False,
            "error": f"status={data.get('status')}",
            "latency_ms": latency_ms,
        }

    output_text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text", "")

    if not output_text:
        return {"pass": False, "error": "no output_text", "latency_ms": latency_ms}

    try:
        interpretation = json.loads(output_text)
    except json.JSONDecodeError:
        return {"pass": False, "error": "invalid JSON", "latency_ms": latency_ms}

    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(canonical_schema, format_checker=FormatChecker())
    canonical_json_schema_valid = len(list(validator.iter_errors(interpretation))) == 0

    from genesis_cognitive.decision.types import TurnInterpretation

    pydantic_valid = False
    ti = None
    try:
        ti = TurnInterpretation.model_validate_json(output_text)
        pydantic_valid = True
    except Exception:
        pass

    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError

    catalog_valid = False
    if ti is not None:
        try:
            CapabilityCatalog().validate_interpretation(ti)
            catalog_valid = True
        except InvalidModelOutputError:
            pass

    # Evaluate expectations
    passed = True
    actions = interpretation.get("actions", [])
    clarifications = interpretation.get("clarifications", [])
    mode = interpretation.get("mode")

    if mode != "CLARIFICATION":
        passed = False
    if len(actions) != 1:
        passed = False
    if len(clarifications) != 1:
        passed = False
    if interpretation.get("unsupported_segments") != []:
        passed = False

    # PARTIAL ACTION
    suggested_question = ""
    already_known_set: set[str] = set()
    if actions:
        a = actions[0]
        if a.get("sequence") != 1:
            passed = False
        if a.get("intent_id") != "TRANSFER_BETWEEN_OWN_ACCOUNTS":
            passed = False
        if a.get("capability_candidate") != "TRANSFER":
            passed = False
        if a.get("selected_route") != "TRANSFER_CONTRACT_BUILDER":
            passed = False
        entities = a.get("detected_entities") or {}
        # Known entities
        if entities.get("destination_account_ref") != "AHO001":
            passed = False
        if entities.get("amount") not in ("500", "500.00", "500.0"):
            passed = False
        if entities.get("currency") != "DOP":
            passed = False
        # Must be null (missing or not applicable)
        if entities.get("source_account_ref") is not None:
            passed = False
        if entities.get("account_ref") is not None:
            passed = False
        if entities.get("knowledge_topic") is not None:
            passed = False
        # missing_requirements
        if a.get("missing_requirements") != ["source_account_ref"]:
            passed = False
        if a.get("depends_on") != []:
            passed = False
    else:
        passed = False

    # CLARIFICATION
    if clarifications:
        c = clarifications[0]
        if c.get("target_action_sequence") != 1:
            passed = False
        if c.get("missing_requirements") != ["source_account_ref"]:
            passed = False
        already_known_set = set(c.get("already_known", []))
        expected_known = {"destination_account_ref", "amount", "currency"}
        if already_known_set != expected_known:
            passed = False
        suggested_question = c.get("suggested_question", "")
        if not suggested_question or len(suggested_question) < 5:
            passed = False
    else:
        passed = False

    if not canonical_json_schema_valid or not pydantic_valid or not catalog_valid:
        passed = False

    usage = data.get("usage", {})

    return {
        "pass": passed,
        "input": user_input,
        "synthetic_context": synthetic_context,
        "model": model,
        "latency_ms": round(latency_ms),
        "usage": usage,
        "canonical_json_schema_valid": canonical_json_schema_valid,
        "pydantic_valid": pydantic_valid,
        "catalog_valid": catalog_valid,
        "turn_interpretation": interpretation,
        "mode": mode,
        "suggested_question": suggested_question,
        "already_known": sorted(already_known_set),
    }


# ---------------------------------------------------------------------------
# Currency policy validation (pure function, no API calls)
# ---------------------------------------------------------------------------

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class TransferCurrencyDecision(StrEnum):
    SAME_CURRENCY_TRANSFER = "SAME_CURRENCY_TRANSFER"
    FX_OPERATION_REQUIRED = "FX_OPERATION_REQUIRED"
    INVALID_CURRENCY_OUTPUT = "INVALID_CURRENCY_OUTPUT"
    ACCOUNT_REFERENCE_NOT_FOUND = "ACCOUNT_REFERENCE_NOT_FOUND"
    ACTION_CURRENCY_MISMATCH = "ACTION_CURRENCY_MISMATCH"


def evaluate_transfer_currency_policy(
    interpretation: dict[str, Any],
    synthetic_context: dict[str, Any],
) -> TransferCurrencyDecision:
    """Evaluate currency policy for a transfer between own accounts.

    Executed exclusively AFTER AI interpretation. Does not:
    - receive raw_text
    - detect intent
    - extract entities
    - select routes
    - invoke capabilities
    - build contracts
    - execute operations

    Never modifies interpretation or synthetic_context.
    """
    actions = interpretation.get("actions", [])
    if not actions:
        return TransferCurrencyDecision.ACCOUNT_REFERENCE_NOT_FOUND

    action = actions[0]
    entities = action.get("detected_entities") or {}
    source_ref = entities.get("source_account_ref")
    dest_ref = entities.get("destination_account_ref")
    action_currency = entities.get("currency")

    # 1. Missing references
    if not source_ref or not dest_ref:
        return TransferCurrencyDecision.ACCOUNT_REFERENCE_NOT_FOUND

    # 2. Account not found in context
    products = synthetic_context.get("products", [])
    source_product = None
    dest_product = None
    for p in products:
        if p.get("product_ref") == source_ref:
            source_product = p
        if p.get("product_ref") == dest_ref:
            dest_product = p

    if source_product is None or dest_product is None:
        return TransferCurrencyDecision.ACCOUNT_REFERENCE_NOT_FOUND

    # 3. Validate currency format (exactly 3 uppercase letters)
    source_currency = source_product.get("currency")
    dest_currency = dest_product.get("currency")

    if not isinstance(source_currency, str) or not _CURRENCY_PATTERN.match(source_currency):
        return TransferCurrencyDecision.INVALID_CURRENCY_OUTPUT

    if not isinstance(dest_currency, str) or not _CURRENCY_PATTERN.match(dest_currency):
        return TransferCurrencyDecision.INVALID_CURRENCY_OUTPUT

    if not isinstance(action_currency, str) or not _CURRENCY_PATTERN.match(action_currency):
        return TransferCurrencyDecision.INVALID_CURRENCY_OUTPUT

    # 4. Different currencies between products → FX required
    if source_currency != dest_currency:
        return TransferCurrencyDecision.FX_OPERATION_REQUIRED

    # 5. Action currency doesn't match the common product currency
    if action_currency != source_currency:
        return TransferCurrencyDecision.ACTION_CURRENCY_MISMATCH

    # 6. All good
    return TransferCurrencyDecision.SAME_CURRENCY_TRANSFER


def validate_same_currency_transfer(
    interpretation: dict[str, Any],
    synthetic_context: dict[str, Any],
) -> bool:
    """Boolean wrapper for backward compatibility."""
    return (
        evaluate_transfer_currency_policy(interpretation, synthetic_context)
        is TransferCurrencyDecision.SAME_CURRENCY_TRANSFER
    )


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def _run_and_save_business_knowledge(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
    prompt_id: str,
    prompt_version: str,
    canonical_unchanged: bool,
) -> int:
    result = run_business_knowledge_case(
        model, api_key, base_url, canonical_schema, openai_schema, instructions
    )

    if "error" in result:
        print(f"FAIL: {result['error']}")
        return 1

    json_result: dict[str, Any] = {
        "case_id": "business-knowledge",
        "input": result.get("input", ""),
        "model": model,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "store_requested": False,
        "structured_output_strict": True,
        "canonical_schema_unchanged": canonical_unchanged,
        "canonical_json_schema_valid": result.get("canonical_json_schema_valid", False),
        "pydantic_valid": result.get("pydantic_valid", False),
        "catalog_valid": result.get("catalog_valid", False),
        "turn_interpretation": result.get("turn_interpretation"),
        "result": "PASS" if result["pass"] else "FAIL",
    }
    (ROOT / "evidence" / "t08-c7a-business-knowledge-result.json").write_text(
        json.dumps(json_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    evidence = (
        f"date_utc: {datetime.now(tz=UTC).isoformat()}\n"
        f"endpoint: api.openai.com/v1/responses\n"
        f"model: {model}\n"
        f"prompt_id: {prompt_id}\n"
        f"prompt_version: {prompt_version}\n"
        f"canonical_schema_unchanged: {canonical_unchanged}\n"
        f"canonical_json_schema_valid: {result.get('canonical_json_schema_valid')}\n"
        f"pydantic_valid: {result.get('pydantic_valid')}\n"
        f"catalog_valid: {result.get('catalog_valid')}\n"
        f"intent_id: {result.get('intent_id')}\n"
        f"capability_candidate: {result.get('capability_candidate')}\n"
        f"selected_route: {result.get('selected_route')}\n"
        f"mode: {result.get('mode')}\n"
        f"knowledge_topic: {result.get('knowledge_topic')}\n"
        f"latency_ms: {result.get('latency_ms')}\n"
        f"input_tokens: {result.get('usage', {}).get('input_tokens', 'N/A')}\n"
        f"output_tokens: {result.get('usage', {}).get('output_tokens', 'N/A')}\n"
        f"result: {'PASS' if result['pass'] else 'FAIL'}\n"
        f"exit_code: {0 if result['pass'] else 1}\n"
        f"\nEARLY_MODEL_SEMANTIC_PREFLIGHT\nNO_AGENT_FRAMEWORK\nNO_RAG\n"
        f"NOT_FINAL_COGNITIVE_ACCEPTANCE\n"
    )
    (ROOT / "evidence" / "t08-c7a-business-knowledge-validation.txt").write_text(
        evidence, encoding="utf-8"
    )

    _print_result(result)
    return 0 if result["pass"] else 1


def _run_and_save_account_balance(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
    prompt_id: str,
    prompt_version: str,
    canonical_unchanged: bool,
) -> int:
    result = run_account_balance_case(
        model, api_key, base_url, canonical_schema, openai_schema, instructions
    )

    if "error" in result:
        print(f"FAIL: {result['error']}")
        return 1

    json_result: dict[str, Any] = {
        "case_id": "account-balance-context",
        "input": result.get("input", ""),
        "synthetic_context": result.get("synthetic_context"),
        "model": model,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "store_requested": False,
        "structured_output_strict": True,
        "canonical_schema_unchanged": canonical_unchanged,
        "canonical_json_schema_valid": result.get("canonical_json_schema_valid", False),
        "pydantic_valid": result.get("pydantic_valid", False),
        "catalog_valid": result.get("catalog_valid", False),
        "turn_interpretation": result.get("turn_interpretation"),
        "expected_account_ref": "COR001",
        "resolved_account_ref": result.get("resolved_account_ref"),
        "result": "PASS" if result["pass"] else "FAIL",
    }
    (ROOT / "evidence" / "t08-c7b-account-balance-result.json").write_text(
        json.dumps(json_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    evidence = (
        f"date_utc: {datetime.now(tz=UTC).isoformat()}\n"
        f"endpoint: api.openai.com/v1/responses\n"
        f"model: {model}\n"
        f"prompt_id: {prompt_id}\n"
        f"prompt_version: {prompt_version}\n"
        f"input: {result.get('input')}\n"
        f"alias_in_context: cuenta principal\n"
        f"product_ref_available: COR001\n"
        f"intent_id: {result.get('intent_id')}\n"
        f"capability_candidate: {result.get('capability_candidate')}\n"
        f"selected_route: {result.get('selected_route')}\n"
        f"mode: {result.get('mode')}\n"
        f"resolved_account_ref: {result.get('resolved_account_ref')}\n"
        f"canonical_schema_unchanged: {canonical_unchanged}\n"
        f"canonical_json_schema_valid: {result.get('canonical_json_schema_valid')}\n"
        f"pydantic_valid: {result.get('pydantic_valid')}\n"
        f"catalog_valid: {result.get('catalog_valid')}\n"
        f"latency_ms: {result.get('latency_ms')}\n"
        f"input_tokens: {result.get('usage', {}).get('input_tokens', 'N/A')}\n"
        f"output_tokens: {result.get('usage', {}).get('output_tokens', 'N/A')}\n"
        f"result: {'PASS' if result['pass'] else 'FAIL'}\n"
        f"exit_code: {0 if result['pass'] else 1}\n"
        f"\nEARLY_MODEL_SEMANTIC_PREFLIGHT\nCONTEXT_REFERENCE_RESOLUTION\n"
        f"NO_AGENT_FRAMEWORK\nNO_RAG\nNOT_FINAL_COGNITIVE_ACCEPTANCE\n"
    )
    (ROOT / "evidence" / "t08-c7b-account-balance-validation.txt").write_text(
        evidence, encoding="utf-8"
    )

    _print_result(result)
    return 0 if result["pass"] else 1


def _run_and_save_transfer_complete(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
    prompt_id: str,
    prompt_version: str,
    canonical_unchanged: bool,
) -> int:
    result = run_transfer_complete_case(
        model, api_key, base_url, canonical_schema, openai_schema, instructions
    )

    if "error" in result:
        print(f"FAIL: {result['error']}")
        return 1

    json_result: dict[str, Any] = {
        "case_id": "transfer-complete-context",
        "input": result.get("input", ""),
        "synthetic_context": result.get("synthetic_context"),
        "model": model,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "store_requested": False,
        "structured_output_strict": True,
        "canonical_schema_unchanged": canonical_unchanged,
        "canonical_json_schema_valid": result.get("canonical_json_schema_valid", False),
        "pydantic_valid": result.get("pydantic_valid", False),
        "catalog_valid": result.get("catalog_valid", False),
        "turn_interpretation": result.get("turn_interpretation"),
        "contextual_schema": {
            "product_refs": sorted(
                {
                    p["product_ref"]
                    for p in result.get("synthetic_context", {}).get("products", [])
                    if "product_ref" in p
                }
            ),
            "currencies": sorted(
                {
                    p["currency"]
                    for p in result.get("synthetic_context", {}).get("products", [])
                    if "currency" in p
                }
            ),
            "derived_from_authorized_context": True,
        },
        "currency_policy_decision": result.get("currency_policy_decision"),
        "expected": {
            "source_account_ref": "COR001",
            "destination_account_ref": "AHO001",
            "amount": "500",
            "currency": "DOP",
        },
        "resolved": {
            "source_account_ref": result.get("resolved_source_account_ref"),
            "destination_account_ref": result.get("resolved_destination_account_ref"),
            "amount": result.get("resolved_amount"),
            "currency": result.get("resolved_currency"),
        },
        "result": "PASS" if result["pass"] else "FAIL",
    }
    (ROOT / "evidence" / "t08-c7c-transfer-result.json").write_text(
        json.dumps(json_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    evidence = (
        f"date_utc: {datetime.now(tz=UTC).isoformat()}\n"
        f"endpoint: api.openai.com/v1/responses\n"
        f"model: {model}\n"
        f"prompt_id: {prompt_id}\n"
        f"prompt_version: {prompt_version}\n"
        f"input: {result.get('input')}\n"
        f"source_alias_in_context: cuenta principal\n"
        f"destination_alias_in_context: mis ahorros\n"
        f"intent_id: {result.get('intent_id')}\n"
        f"capability_candidate: {result.get('capability_candidate')}\n"
        f"selected_route: {result.get('selected_route')}\n"
        f"mode: {result.get('mode')}\n"
        f"source_account_ref: {result.get('resolved_source_account_ref')}\n"
        f"destination_account_ref: "
        f"{result.get('resolved_destination_account_ref')}\n"
        f"amount: {result.get('resolved_amount')}\n"
        f"currency: {result.get('resolved_currency')}\n"
        f"canonical_schema_unchanged: {canonical_unchanged}\n"
        f"canonical_json_schema_valid: "
        f"{result.get('canonical_json_schema_valid')}\n"
        f"pydantic_valid: {result.get('pydantic_valid')}\n"
        f"catalog_valid: {result.get('catalog_valid')}\n"
        f"currency_policy_decision: {result.get('currency_policy_decision')}\n"
        f"latency_ms: {result.get('latency_ms')}\n"
        f"input_tokens: "
        f"{result.get('usage', {}).get('input_tokens', 'N/A')}\n"
        f"output_tokens: "
        f"{result.get('usage', {}).get('output_tokens', 'N/A')}\n"
        f"attempt_count: 1\n"
        f"result: {'PASS' if result['pass'] else 'FAIL'}\n"
        f"exit_code: {0 if result['pass'] else 1}\n"
        f"\nEARLY_MODEL_SEMANTIC_PREFLIGHT\n"
        f"CONTEXT_REFERENCE_RESOLUTION\n"
        f"TRANSACTION_CONTRACT_PREPARATION_ONLY\n"
        f"NO_EXECUTION\n"
        f"NO_AGENT_FRAMEWORK\nNO_RAG\n"
        f"NOT_FINAL_COGNITIVE_ACCEPTANCE\n"
    )
    (ROOT / "evidence" / "t08-c7c-transfer-validation.txt").write_text(evidence, encoding="utf-8")

    _print_result_transfer(result)
    return 0 if result["pass"] else 1


def _run_and_save_multi_dependent(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
    prompt_id: str,
    prompt_version: str,
    canonical_unchanged: bool,
) -> int:
    result = run_multi_dependent_case(
        model, api_key, base_url, canonical_schema, openai_schema, instructions
    )

    if "error" in result:
        print(f"FAIL: {result['error']}")
        return 1

    ti = result.get("turn_interpretation", {})
    actions = ti.get("actions", [])

    json_result: dict[str, Any] = {
        "case_id": "multi-dependent-transfer-balance",
        "input": result.get("input", ""),
        "synthetic_context": result.get("synthetic_context"),
        "model": model,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "store_requested": False,
        "structured_output_strict": True,
        "contextual_schema": {
            "product_refs": sorted(
                {
                    p["product_ref"]
                    for p in result.get("synthetic_context", {}).get("products", [])
                    if "product_ref" in p
                }
            ),
            "currencies": sorted(
                {
                    p["currency"]
                    for p in result.get("synthetic_context", {}).get("products", [])
                    if "currency" in p
                }
            ),
            "derived_from_authorized_context": True,
        },
        "canonical_schema_unchanged": canonical_unchanged,
        "canonical_json_schema_valid": result.get("canonical_json_schema_valid", False),
        "pydantic_valid": result.get("pydantic_valid", False),
        "catalog_valid": result.get("catalog_valid", False),
        "currency_policy_decision": result.get("currency_policy_decision"),
        "turn_interpretation": ti,
        "dependency_validation": {
            "transfer_sequence": actions[0].get("sequence") if actions else None,
            "balance_sequence": actions[1].get("sequence") if len(actions) > 1 else None,
            "balance_depends_on": actions[1].get("depends_on") if len(actions) > 1 else None,
            "dag_valid": result.get("dag_valid", False),
        },
        "result": "PASS" if result["pass"] else "FAIL",
    }
    (ROOT / "evidence" / "t08-c7d-multi-dependent-result.json").write_text(
        json.dumps(json_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Action details for evidence text
    a1_text = ""
    a2_text = ""
    if len(actions) >= 1:
        a1 = actions[0]
        e1 = a1.get("detected_entities", {})
        a1_text = (
            f"  sequence: {a1.get('sequence')}\n"
            f"  intent_id: {a1.get('intent_id')}\n"
            f"  capability_candidate: {a1.get('capability_candidate')}\n"
            f"  selected_route: {a1.get('selected_route')}\n"
            f"  source_account_ref: {e1.get('source_account_ref')}\n"
            f"  destination_account_ref: {e1.get('destination_account_ref')}\n"
            f"  amount: {e1.get('amount')}\n"
            f"  currency: {e1.get('currency')}\n"
            f"  depends_on: {a1.get('depends_on')}\n"
        )
    if len(actions) >= 2:
        a2 = actions[1]
        e2 = a2.get("detected_entities", {})
        a2_text = (
            f"  sequence: {a2.get('sequence')}\n"
            f"  intent_id: {a2.get('intent_id')}\n"
            f"  capability_candidate: {a2.get('capability_candidate')}\n"
            f"  selected_route: {a2.get('selected_route')}\n"
            f"  account_ref: {e2.get('account_ref')}\n"
            f"  depends_on: {a2.get('depends_on')}\n"
        )

    evidence = (
        f"date_utc: {datetime.now(tz=UTC).isoformat()}\n"
        f"endpoint: api.openai.com/v1/responses\n"
        f"model: {model}\n"
        f"prompt_id: {prompt_id}\n"
        f"prompt_version: {prompt_version}\n"
        f"input: {result.get('input')}\n"
        f"mode: {result.get('mode')}\n"
        f"action_count: {result.get('action_count')}\n"
        f"\naction_1:\n{a1_text}\n"
        f"action_2:\n{a2_text}\n"
        f"dependency: action_2.depends_on = "
        f"{actions[1].get('depends_on') if len(actions) > 1 else 'N/A'}\n"
        f"dag_valid: {result.get('dag_valid')}\n"
        f"canonical_schema_unchanged: {canonical_unchanged}\n"
        f"canonical_json_schema_valid: {result.get('canonical_json_schema_valid')}\n"
        f"pydantic_valid: {result.get('pydantic_valid')}\n"
        f"catalog_valid: {result.get('catalog_valid')}\n"
        f"currency_policy_decision: {result.get('currency_policy_decision')}\n"
        f"latency_ms: {result.get('latency_ms')}\n"
        f"input_tokens: {result.get('usage', {}).get('input_tokens', 'N/A')}\n"
        f"output_tokens: {result.get('usage', {}).get('output_tokens', 'N/A')}\n"
        f"attempt_count: 1\n"
        f"result: {'PASS' if result['pass'] else 'FAIL'}\n"
        f"exit_code: {0 if result['pass'] else 1}\n"
        f"\nEARLY_MODEL_SEMANTIC_PREFLIGHT\n"
        f"MULTI_ACTION_REASONING\n"
        f"DEPENDENCY_DAG\n"
        f"CONTEXT_REFERENCE_RESOLUTION\n"
        f"TRANSACTION_CONTRACT_PREPARATION_ONLY\n"
        f"NO_EXECUTION\n"
        f"NO_AGENT_FRAMEWORK\nNO_RAG\n"
        f"NOT_FINAL_COGNITIVE_ACCEPTANCE\n"
    )
    (ROOT / "evidence" / "t08-c7d-multi-dependent-validation.txt").write_text(
        evidence, encoding="utf-8"
    )

    _print_result_multi(result)
    return 0 if result["pass"] else 1


def _run_and_save_clarification(
    model: str,
    api_key: str,
    base_url: str,
    canonical_schema: dict[str, Any],
    openai_schema: dict[str, Any],
    instructions: str,
    prompt_id: str,
    prompt_version: str,
    canonical_unchanged: bool,
) -> int:
    result = run_clarification_missing_source_case(
        model, api_key, base_url, canonical_schema, openai_schema, instructions
    )

    if "error" in result:
        print(f"FAIL: {result['error']}")
        return 1

    ti = result.get("turn_interpretation", {})
    actions = ti.get("actions", [])
    clarifications = ti.get("clarifications", [])

    json_result: dict[str, Any] = {
        "case_id": "clarification-missing-source",
        "input": result.get("input", ""),
        "synthetic_context": result.get("synthetic_context"),
        "model": model,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "store_requested": False,
        "structured_output_strict": True,
        "contextual_schema": {
            "product_refs": sorted(
                {
                    p["product_ref"]
                    for p in result.get("synthetic_context", {}).get("products", [])
                    if "product_ref" in p
                }
            ),
            "currencies": sorted(
                {
                    p["currency"]
                    for p in result.get("synthetic_context", {}).get("products", [])
                    if "currency" in p
                }
            ),
            "derived_from_authorized_context": True,
        },
        "canonical_schema_unchanged": canonical_unchanged,
        "canonical_json_schema_valid": result.get("canonical_json_schema_valid", False),
        "pydantic_valid": result.get("pydantic_valid", False),
        "catalog_valid": result.get("catalog_valid", False),
        "currency_policy_status": "NOT_APPLICABLE_INCOMPLETE_ACTION",
        "turn_interpretation": ti,
        "clarification_validation": {
            "target_action_sequence": (
                clarifications[0].get("target_action_sequence") if clarifications else None
            ),
            "missing_requirements": (
                clarifications[0].get("missing_requirements") if clarifications else None
            ),
            "already_known": result.get("already_known"),
            "suggested_question_present": bool(result.get("suggested_question")),
            "only_missing_source_requested": (
                clarifications[0].get("missing_requirements") == ["source_account_ref"]
                if clarifications
                else False
            ),
        },
        "result": "PASS" if result["pass"] else "FAIL",
    }
    (ROOT / "evidence" / "t08-c7e-r1-prompt-1.1.0-result.json").write_text(
        json.dumps(json_result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Build action details
    action_text = ""
    if actions:
        a = actions[0]
        e = a.get("detected_entities", {})
        action_text = (
            f"  sequence: {a.get('sequence')}\n"
            f"  intent_id: {a.get('intent_id')}\n"
            f"  capability_candidate: {a.get('capability_candidate')}\n"
            f"  selected_route: {a.get('selected_route')}\n"
            f"  source_account_ref: {e.get('source_account_ref')}\n"
            f"  destination_account_ref: {e.get('destination_account_ref')}\n"
            f"  amount: {e.get('amount')}\n"
            f"  currency: {e.get('currency')}\n"
            f"  account_ref: {e.get('account_ref')}\n"
            f"  knowledge_topic: {e.get('knowledge_topic')}\n"
            f"  missing_requirements: {a.get('missing_requirements')}\n"
            f"  depends_on: {a.get('depends_on')}\n"
        )

    clarification_text = ""
    if clarifications:
        c = clarifications[0]
        clarification_text = (
            f"  target_action_sequence: {c.get('target_action_sequence')}\n"
            f"  missing_requirements: {c.get('missing_requirements')}\n"
            f"  already_known: {c.get('already_known')}\n"
            f"  suggested_question: {c.get('suggested_question')}\n"
        )

    # Extract known entities for evidence
    e0 = actions[0].get("detected_entities", {}) if actions else {}
    known_dest = e0.get("destination_account_ref", "N/A")
    known_amt = e0.get("amount", "N/A")
    known_cur = e0.get("currency", "N/A")

    evidence = (
        f"date_utc: {datetime.now(tz=UTC).isoformat()}\n"
        f"endpoint: api.openai.com/v1/responses\n"
        f"model: {model}\n"
        f"prompt_id: {prompt_id}\n"
        f"prompt_version: {prompt_version}\n"
        f"input: {result.get('input')}\n"
        f"mode: {result.get('mode')}\n"
        f"\npartial_action:\n{action_text}\n"
        f"known_entities:\n"
        f"  destination_account_ref: {known_dest}\n"
        f"  amount: {known_amt}\n"
        f"  currency: {known_cur}\n"
        f"\nmissing_requirement: source_account_ref\n"
        f"\nclarification:\n{clarification_text}\n"
        f"suggested_question: {result.get('suggested_question')}\n"
        f"already_known: {result.get('already_known')}\n"
        f"\ncanonical_schema_unchanged: {canonical_unchanged}\n"
        f"canonical_json_schema_valid: {result.get('canonical_json_schema_valid')}\n"
        f"pydantic_valid: {result.get('pydantic_valid')}\n"
        f"catalog_valid: {result.get('catalog_valid')}\n"
        f"currency_policy_status: NOT_APPLICABLE_INCOMPLETE_ACTION\n"
        f"latency_ms: {result.get('latency_ms')}\n"
        f"input_tokens: {result.get('usage', {}).get('input_tokens', 'N/A')}\n"
        f"output_tokens: {result.get('usage', {}).get('output_tokens', 'N/A')}\n"
        f"attempt_count: 1\n"
        f"result: {'PASS' if result['pass'] else 'FAIL'}\n"
        f"exit_code: {0 if result['pass'] else 1}\n"
        f"\nEARLY_MODEL_SEMANTIC_PREFLIGHT\n"
        f"MINIMAL_CLARIFICATION\n"
        f"BUSINESS_INTENT_PRESERVED\n"
        f"CANONICAL_ALREADY_KNOWN\n"
        f"CONTEXT_AWARENESS\n"
        f"KNOWN_INFORMATION_PRESERVED\n"
        f"NO_UNSAFE_ACCOUNT_INFERENCE\n"
        f"NO_EXECUTION\n"
        f"NO_AGENT_FRAMEWORK\nNO_RAG\n"
        f"NOT_FINAL_COGNITIVE_ACCEPTANCE\n"
    )
    (ROOT / "evidence" / "t08-c7e-r1-prompt-1.1.0-validation.txt").write_text(
        evidence, encoding="utf-8"
    )

    _print_result_clarification(result)
    return 0 if result["pass"] else 1


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------


def _print_result(result: dict[str, Any]) -> None:
    status = "PASS" if result["pass"] else "FAIL"
    print(f"\nResult: {status}")
    print(f"Intent: {result.get('intent_id')}")
    print(f"Candidate: {result.get('capability_candidate')}")
    print(f"Route: {result.get('selected_route')}")
    print(f"Mode: {result.get('mode')}")
    if "knowledge_topic" in result:
        print(f"Knowledge topic: {result.get('knowledge_topic')}")
    if "resolved_account_ref" in result:
        print(f"Resolved account_ref: {result.get('resolved_account_ref')}")
    print(f"Latency: {result.get('latency_ms')}ms")
    usage = result.get("usage", {})
    in_tok = usage.get("input_tokens", "N/A")
    out_tok = usage.get("output_tokens", "N/A")
    print(f"Tokens: input={in_tok}, output={out_tok}")


def _print_result_transfer(result: dict[str, Any]) -> None:
    status = "PASS" if result["pass"] else "FAIL"
    print(f"\nResult: {status}")
    print(f"Intent: {result.get('intent_id')}")
    print(f"Candidate: {result.get('capability_candidate')}")
    print(f"Route: {result.get('selected_route')}")
    print(f"Mode: {result.get('mode')}")
    print(f"Source: {result.get('resolved_source_account_ref')}")
    print(f"Destination: {result.get('resolved_destination_account_ref')}")
    print(f"Amount: {result.get('resolved_amount')}")
    print(f"Currency: {result.get('resolved_currency')}")
    print(f"Latency: {result.get('latency_ms')}ms")
    usage = result.get("usage", {})
    in_tok = usage.get("input_tokens", "N/A")
    out_tok = usage.get("output_tokens", "N/A")
    print(f"Tokens: input={in_tok}, output={out_tok}")


def _print_result_multi(result: dict[str, Any]) -> None:
    status = "PASS" if result["pass"] else "FAIL"
    print(f"\nResult: {status}")
    print(f"Mode: {result.get('mode')}")
    print(f"Actions: {result.get('action_count')}")
    print(f"DAG valid: {result.get('dag_valid')}")
    print(f"Currency policy: {result.get('currency_policy_decision')}")
    print(f"Latency: {result.get('latency_ms')}ms")
    usage = result.get("usage", {})
    in_tok = usage.get("input_tokens", "N/A")
    out_tok = usage.get("output_tokens", "N/A")
    print(f"Tokens: input={in_tok}, output={out_tok}")


def _print_result_clarification(result: dict[str, Any]) -> None:
    status = "PASS" if result["pass"] else "FAIL"
    print(f"\nResult: {status}")
    print(f"Mode: {result.get('mode')}")
    print(f"Suggested question: {result.get('suggested_question')}")
    print(f"Already known: {result.get('already_known')}")
    print(f"Latency: {result.get('latency_ms')}ms")
    usage = result.get("usage", {})
    in_tok = usage.get("input_tokens", "N/A")
    out_tok = usage.get("output_tokens", "N/A")
    print(f"Tokens: input={in_tok}, output={out_tok}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAI semantic preflight runner")
    parser.add_argument("--case", required=True, help="Case to run")
    args = parser.parse_args()

    valid_cases = (
        "business-knowledge",
        "account-balance-context",
        "transfer-complete-context",
        "multi-dependent-transfer-balance",
        "clarification-missing-source",
    )
    if args.case not in valid_cases:
        print(f"Case '{args.case}' not implemented. Valid: {valid_cases}")
        return 1

    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    if not api_key or not model:
        print("FAIL: Missing OPENAI_API_KEY or OPENAI_MODEL")
        return 1

    canonical_schema = load_canonical_turn_interpretation_schema()
    canonical_before = json.dumps(canonical_schema, sort_keys=True, ensure_ascii=False)
    openai_schema = build_openai_output_schema(canonical_schema)
    canonical_after = json.dumps(canonical_schema, sort_keys=True, ensure_ascii=False)
    canonical_unchanged = canonical_before == canonical_after

    instructions, prompt_id, prompt_version = load_prompt_via_registry()

    print(f"Running case: {args.case}")
    print(f"Model: {model}")
    print(f"Prompt: {prompt_id}@{prompt_version}")
    print(f"Canonical schema unchanged: {canonical_unchanged}")

    if args.case == "business-knowledge":
        return _run_and_save_business_knowledge(
            model,
            api_key,
            base_url,
            canonical_schema,
            openai_schema,
            instructions,
            prompt_id,
            prompt_version,
            canonical_unchanged,
        )
    elif args.case == "account-balance-context":
        return _run_and_save_account_balance(
            model,
            api_key,
            base_url,
            canonical_schema,
            openai_schema,
            instructions,
            prompt_id,
            prompt_version,
            canonical_unchanged,
        )
    elif args.case == "transfer-complete-context":
        return _run_and_save_transfer_complete(
            model,
            api_key,
            base_url,
            canonical_schema,
            openai_schema,
            instructions,
            prompt_id,
            prompt_version,
            canonical_unchanged,
        )
    elif args.case == "multi-dependent-transfer-balance":
        return _run_and_save_multi_dependent(
            model,
            api_key,
            base_url,
            canonical_schema,
            openai_schema,
            instructions,
            prompt_id,
            prompt_version,
            canonical_unchanged,
        )
    elif args.case == "clarification-missing-source":
        return _run_and_save_clarification(
            model,
            api_key,
            base_url,
            canonical_schema,
            openai_schema,
            instructions,
            prompt_id,
            prompt_version,
            canonical_unchanged,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
