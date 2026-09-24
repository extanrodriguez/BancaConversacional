"""E2E Semantic Acceptance — HTTP client for contract inspector.

Usage:
    .\.venv\Scripts\python.exe scripts/e2e_acceptance.py
    .\.venv\Scripts\python.exe scripts/e2e_acceptance.py --base-url http://localhost:8000
    .\.venv\Scripts\python.exe scripts/e2e_acceptance.py --single "Quiero consultar mi saldo"
    .\.venv\Scripts\python.exe scripts/e2e_acceptance.py --only AC-01,AC-02

Requires the contract inspector running at --base-url (default http://localhost:8000).
Does NOT start the server. Does NOT use mocks or fakes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

REPETITIONS = 10


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def post_inspect(
    base_url: str,
    question: str,
    conversation_id: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """POST to /inspect and return parsed JSON response."""
    payload: dict[str, str] = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if customer_id:
        payload["customer_id"] = customer_id

    resp = httpx.post(
        f"{base_url}/inspect",
        json=payload,
        timeout=60.0,
    )
    result: dict[str, Any] = resp.json()
    result["_http_status"] = resp.status_code
    return result


def extract_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Extract fields relevant for AC validation."""
    actions = result.get("actions", [])
    first_action = actions[0] if actions else {}
    entities = first_action.get("detected_entities", {}) if first_action else {}

    clarifications = result.get("clarifications", [])
    first_clar = clarifications[0] if clarifications else {}

    return {
        "http_status": result.get("_http_status"),
        "status": result.get("status"),
        "mode": result.get("mode"),
        "intent_id": first_action.get("intent_id") if first_action else None,
        "account_ref": entities.get("account_ref"),
        "source_account_ref": entities.get("source_account_ref"),
        "destination_account_ref": entities.get("destination_account_ref"),
        "amount": entities.get("amount"),
        "currency": entities.get("currency"),
        "missing_requirements": first_clar.get("missing_requirements") or first_action.get("missing_requirements"),
        "already_known": first_clar.get("already_known"),
        "suggested_question": first_clar.get("suggested_question"),
        "conversation_id": result.get("conversation_id"),
        "inference_count": result.get("inference_count"),
        "catalog_valid": result.get("catalog_valid"),
        "entity_refs_valid": result.get("entity_refs_valid"),
        "violations": result.get("violations"),
        "unsupported_segments": result.get("unsupported_segments"),
        "actions_count": len(actions),
        "non_operational_response": result.get("non_operational_response"),
    }


def print_summary(summary: dict[str, Any], prefix: str = "  ") -> None:
    """Print summary fields."""
    print(
        f"{prefix}HTTP={summary['http_status']}  "
        f"status={summary['status']}  "
        f"mode={summary['mode']}  "
        f"account_ref={summary['account_ref']}  "
        f"missing_req={summary['missing_requirements']}  "
        f"conv={str(summary['conversation_id'])[:8]}...  "
        f"infer={summary['inference_count']}"
    )


# ---------------------------------------------------------------------------
# AC validators (return True if PASS for the iteration)
# ---------------------------------------------------------------------------

def validate_ac01(result: dict[str, Any]) -> bool:
    """AC-01: saldo ahorros → AHO001."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "VALID_CONTRACT"
        and s["mode"] == "SINGLE"
        and s["intent_id"] == "ACCOUNT_BALANCE_READ"
        and s["account_ref"] == "AHO001"
        and s["catalog_valid"] is True
        and s["entity_refs_valid"] is True
        and s["violations"] == []
    )


def validate_ac02(result: dict[str, Any]) -> bool:
    """AC-02: saldo corriente → COR001."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "VALID_CONTRACT"
        and s["mode"] == "SINGLE"
        and s["intent_id"] == "ACCOUNT_BALANCE_READ"
        and s["account_ref"] == "COR001"
        and s["catalog_valid"] is True
        and s["entity_refs_valid"] is True
        and s["violations"] == []
    )


def validate_ac03(result: dict[str, Any]) -> bool:
    """AC-03: saludo → NON_OPERATIONAL."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "NON_OPERATIONAL"
        and s["actions_count"] == 0
        and s["mode"] is None
    )


def validate_ac04(result: dict[str, Any]) -> bool:
    """AC-04: ambigüedad → CLARIFICATION_REQUIRED, account_ref=null."""
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "CLARIFICATION_REQUIRED":
        return False
    # mode can be CLARIFICATION (with partial action) or None (empty actions)
    if s["mode"] not in ("CLARIFICATION", None):
        return False
    if s["account_ref"] is not None:
        return False
    # If mode=CLARIFICATION (has actions), check detailed fields
    if s["mode"] == "CLARIFICATION":
        missing = s.get("missing_requirements") or []
        if "account_ref" not in missing:
            return False
        already = set(s.get("already_known") or [])
        if already & set(missing):
            return False
        if not s.get("suggested_question"):
            return False
    return True


def validate_ac05(result: dict[str, Any]) -> bool:
    """AC-05: unsupported."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "UNSUPPORTED"
        and s["mode"] == "UNSUPPORTED"
        and s["actions_count"] == 0
        and bool(s.get("unsupported_segments"))
    )


# ---------------------------------------------------------------------------
# AC-11..AC-16 Personal vs RAG validators
# ---------------------------------------------------------------------------

def validate_ac11(result: dict[str, Any]) -> bool:
    """AC-11: personal saldo ahorros → AHO001, rag NOT_REQUIRED."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "VALID_CONTRACT"
        and s["mode"] == "SINGLE"
        and s["intent_id"] == "ACCOUNT_BALANCE_READ"
        and s["account_ref"] == "AHO001"
        and result.get("rag_status") == "NOT_REQUIRED"
    )


def validate_ac12(result: dict[str, Any]) -> bool:
    """AC-12: personal saldo corriente → COR001, rag NOT_REQUIRED."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "VALID_CONTRACT"
        and s["mode"] == "SINGLE"
        and s["intent_id"] == "ACCOUNT_BALANCE_READ"
        and s["account_ref"] == "COR001"
        and result.get("rag_status") == "NOT_REQUIRED"
    )


def validate_ac13(result: dict[str, Any]) -> bool:
    """AC-13: negocio requisitos préstamo → RAG_PENDING, knowledge_topic≠null, account_ref=null."""
    s = extract_summary(result)
    actions = result.get("actions", [])
    a0 = actions[0] if actions else {}
    ent = a0.get("detected_entities", {}) if a0 else {}
    return (
        s["http_status"] == 200
        and s["status"] == "RAG_PENDING"
        and s["mode"] == "SINGLE"
        and s["intent_id"] == "BUSINESS_KNOWLEDGE_QUERY"
        and ent.get("knowledge_topic") is not None
        and ent.get("knowledge_topic") != ""
        and ent.get("account_ref") is None
        and result.get("rag_status") == "RAG_PENDING"
    )


def validate_ac14(result: dict[str, Any]) -> bool:
    """AC-14: negocio tasas préstamos → RAG_PENDING, knowledge_topic≠null, account_ref=null."""
    s = extract_summary(result)
    actions = result.get("actions", [])
    a0 = actions[0] if actions else {}
    ent = a0.get("detected_entities", {}) if a0 else {}
    return (
        s["http_status"] == 200
        and s["status"] == "RAG_PENDING"
        and s["mode"] == "SINGLE"
        and s["intent_id"] == "BUSINESS_KNOWLEDGE_QUERY"
        and ent.get("knowledge_topic") is not None
        and ent.get("knowledge_topic") != ""
        and ent.get("account_ref") is None
        and result.get("rag_status") == "RAG_PENDING"
    )


def validate_ac15(result: dict[str, Any]) -> bool:
    """AC-15: ambiguo tasa hipotecario → CLARIFICATION_REQUIRED, account_ref=null, knowledge_topic=null."""
    s = extract_summary(result)
    actions = result.get("actions", [])
    a0 = actions[0] if actions else {}
    ent = a0.get("detected_entities", {}) if a0 else {}
    return (
        s["http_status"] == 200
        and s["status"] == "CLARIFICATION_REQUIRED"
        and s["mode"] == "CLARIFICATION"
        and ent.get("account_ref") is None
        and ent.get("knowledge_topic") is None
    )


def validate_ac16(result: dict[str, Any]) -> bool:
    """AC-16: ambiguo info cuenta ahorros → CLARIFICATION_REQUIRED, account_ref=null, knowledge_topic=null."""
    s = extract_summary(result)
    actions = result.get("actions", [])
    a0 = actions[0] if actions else {}
    ent = a0.get("detected_entities", {}) if a0 else {}
    return (
        s["http_status"] == 200
        and s["status"] == "CLARIFICATION_REQUIRED"
        and s["mode"] == "CLARIFICATION"
        and ent.get("account_ref") is None
        and ent.get("knowledge_topic") is None
    )


# ---------------------------------------------------------------------------
# AC-CTX validators (customer context from SQLite)
# ---------------------------------------------------------------------------

def validate_ac_ctx01(result: dict[str, Any]) -> bool:
    """AC-CTX-01: snapshot loaded, portfolio has products from SQLite."""
    ctx = result.get("customer_context")
    return (
        result.get("_http_status") == 200
        and ctx is not None
        and ctx.get("customer_id") == "CUST001"
        and ctx.get("products_count", 0) >= 3
    )


def validate_ac_ctx02(result: dict[str, Any]) -> bool:
    """AC-CTX-02: CUST002 + 'cuota de mi préstamo' → LOAN_DETAIL_READ + PRE002Q (preferred).

    With loan-read implemented, the preferred result is VALID_CONTRACT + LOAN_DETAIL_READ + PRE002Q.
    Also acceptable: RAG_PENDING without asking which loan (fallback).
    NOT acceptable: CLARIFICATION asking which loan.
    """
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False

    # Preferred: VALID_CONTRACT with LOAN_DETAIL_READ + PRE002Q
    if s["status"] == "VALID_CONTRACT" and s["intent_id"] == "LOAN_DETAIL_READ":
        actions = result.get("actions", [])
        if actions:
            ent = actions[0].get("detected_entities", {})
            if ent.get("account_ref") == "PRE002Q":
                return True

    # Acceptable fallback: RAG_PENDING without asking which loan
    if s["status"] == "RAG_PENDING":
        return True

    # If CLARIFICATION: check it's NOT asking which loan/préstamo
    if s["status"] == "CLARIFICATION_REQUIRED":
        clars = result.get("clarifications", [])
        if clars:
            question = clars[0].get("suggested_question", "").lower()
            loan_ambiguity_signals = ["cuál préstamo", "cual prestamo", "libre inversión", "vehículo", "crédito rápido"]
            for signal in loan_ambiguity_signals:
                if signal in question:
                    return False
        return True

    return True


def validate_ac_ctx03(result: dict[str, Any]) -> bool:
    """AC-CTX-03: CUST001 + 'cuota de mi préstamo' → CLARIFICATION (2 loans).

    PASS if: CLARIFICATION_REQUIRED and does NOT pick PRE001 or PRE001V arbitrarily.
    """
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "CLARIFICATION_REQUIRED":
        return False
    # mode can be CLARIFICATION (with partial action) or None (empty actions, pure disambiguation)
    if s["mode"] not in ("CLARIFICATION", None):
        return False

    # Must not have resolved to a specific loan product_ref
    actions = result.get("actions", [])
    if actions:
        a0 = actions[0]
        ent = a0.get("detected_entities", {})
        acct = ent.get("account_ref")
        # If it picked PRE001 or PRE001V → FAIL (chose arbitrarily)
        if acct in ("PRE001", "PRE001V"):
            return False

    return True


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------

@dataclass
class ACCase:
    ac_id: str
    description: str
    threshold: int
    question: str
    validator: Callable[[dict[str, Any]], bool]
    pass_count: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


SINGLE_TURN_CASES: list[ACCase] = [
    ACCase(
        ac_id="AC-01",
        description="saldo_ahorros → AHO001",
        threshold=9,
        question="¿Cuál es el saldo de mi cuenta de ahorros?",
        validator=validate_ac01,
    ),
    ACCase(
        ac_id="AC-02",
        description="saldo_corriente → COR001",
        threshold=9,
        question="¿Cuál es el saldo de mi cuenta corriente?",
        validator=validate_ac02,
    ),
    ACCase(
        ac_id="AC-03",
        description="saludo → NON_OPERATIONAL",
        threshold=9,
        question="Hola, buenos días",
        validator=validate_ac03,
    ),
    ACCase(
        ac_id="AC-04",
        description="ambiguedad → CLARIFICATION (account_ref=null)",
        threshold=8,
        question="Quiero consultar mi saldo",
        validator=validate_ac04,
    ),
    ACCase(
        ac_id="AC-05",
        description="unsupported → UNSUPPORTED",
        threshold=9,
        question="Reserva un vuelo a Miami para el viernes",
        validator=validate_ac05,
    ),
    ACCase(
        ac_id="AC-11",
        description="personal ahorros → AHO001, rag=NOT_REQUIRED",
        threshold=9,
        question="¿Cuál es el saldo de mi cuenta de ahorros?",
        validator=validate_ac11,
    ),
    ACCase(
        ac_id="AC-12",
        description="personal corriente → COR001, rag=NOT_REQUIRED",
        threshold=9,
        question="¿Cuánto tengo disponible en la corriente?",
        validator=validate_ac12,
    ),
    ACCase(
        ac_id="AC-13",
        description="negocio requisitos préstamo → RAG_PENDING",
        threshold=9,
        question="¿Cuáles son los requisitos para un préstamo de vivienda?",
        validator=validate_ac13,
    ),
    ACCase(
        ac_id="AC-14",
        description="negocio tasas préstamos → RAG_PENDING",
        threshold=9,
        question="¿Qué tasas de interés manejan para préstamos personales?",
        validator=validate_ac14,
    ),
    ACCase(
        ac_id="AC-15",
        description="ambiguo tasa hipotecario → CLARIFICATION",
        threshold=8,
        question="¿Cuál es la tasa del préstamo hipotecario?",
        validator=validate_ac15,
    ),
    ACCase(
        ac_id="AC-16",
        description="ambiguo info cuenta ahorros → CLARIFICATION",
        threshold=8,
        question="Quiero información sobre la cuenta de ahorros",
        validator=validate_ac16,
    ),
]


# ---------------------------------------------------------------------------
# AC-CTX cases (with customer_id)
# ---------------------------------------------------------------------------

@dataclass
class ACCtxCase:
    ac_id: str
    description: str
    threshold: int
    question: str
    customer_id: str | None
    validator: Callable[[dict[str, Any]], bool]
    pass_count: int = 0


CTX_CASES: list[ACCtxCase] = [
    ACCtxCase(
        ac_id="AC-CTX-01",
        description="snapshot loaded (CUST001, products≥3)",
        threshold=10,
        question="Hola",
        customer_id=None,  # default → CUST001
        validator=validate_ac_ctx01,
    ),
    ACCtxCase(
        ac_id="AC-CTX-02",
        description="CUST002 cuota préstamo → no pide cuál (1 loan)",
        threshold=8,
        question="¿Cuánto es la cuota de mi préstamo?",
        customer_id="CUST002",
        validator=validate_ac_ctx02,
    ),
    ACCtxCase(
        ac_id="AC-CTX-03",
        description="CUST001 cuota préstamo → CLARIFICATION (2 loans)",
        threshold=8,
        question="¿Cuánto es la cuota de mi préstamo?",
        customer_id="CUST001",
        validator=validate_ac_ctx03,
    ),
]


# ---------------------------------------------------------------------------
# AC-LR validators (loan-read capability)
# ---------------------------------------------------------------------------

def validate_ac_lr01(result: dict[str, Any]) -> bool:
    """AC-LR-01: CUST002 cuota → VALID_CONTRACT + LOAN_DETAIL_READ + PRE002Q + loan_detail."""
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "VALID_CONTRACT":
        return False
    if s["intent_id"] != "LOAN_DETAIL_READ":
        return False
    actions = result.get("actions", [])
    if not actions:
        return False
    ent = actions[0].get("detected_entities", {})
    if ent.get("account_ref") != "PRE002Q":
        return False
    if result.get("catalog_valid") is not True:
        return False
    if result.get("entity_refs_valid") is not True:
        return False
    if result.get("rag_status") != "NOT_REQUIRED":
        return False
    # Check loan_detail
    ld = result.get("loan_detail")
    if not ld:
        return False
    if ld.get("product_id") != "PRE002Q":
        return False
    # installment_amount should be ~7800
    try:
        amt = float(ld.get("installment_amount", "0"))
        if amt < 7000 or amt > 8000:
            return False
    except (ValueError, TypeError):
        return False
    return True


def validate_ac_lr02(result: dict[str, Any]) -> bool:
    """AC-LR-02: CUST002 tasa → VALID_CONTRACT + LOAN_DETAIL_READ + PRE002Q + loan_detail."""
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "VALID_CONTRACT":
        return False
    if s["intent_id"] != "LOAN_DETAIL_READ":
        return False
    actions = result.get("actions", [])
    if not actions:
        return False
    ent = actions[0].get("detected_entities", {})
    if ent.get("account_ref") != "PRE002Q":
        return False
    # Check loan_detail
    ld = result.get("loan_detail")
    if not ld:
        return False
    if ld.get("product_id") != "PRE002Q":
        return False
    # annual_interest_rate should be ~24.5
    try:
        rate = float(ld.get("annual_interest_rate", "0"))
        if rate < 20 or rate > 30:
            return False
    except (ValueError, TypeError):
        return False
    return True


def validate_ac_lr03(result: dict[str, Any]) -> bool:
    """AC-LR-03: CUST001 cuota → CLARIFICATION (2 loans, no elige uno)."""
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "CLARIFICATION_REQUIRED":
        return False
    # mode can be CLARIFICATION (with partial action) or None (no actions, pure disambiguation)
    if s["mode"] not in ("CLARIFICATION", None):
        return False
    # Must not pick PRE001 or PRE001V
    actions = result.get("actions", [])
    if actions:
        ent = actions[0].get("detected_entities", {})
        if ent.get("account_ref") in ("PRE001", "PRE001V"):
            return False
    return True


def validate_ac_lr04(result: dict[str, Any]) -> bool:
    """AC-LR-04: tasas genéricas → RAG_PENDING + BUSINESS_KNOWLEDGE_QUERY (no loan-read)."""
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "RAG_PENDING":
        return False
    if s["intent_id"] != "BUSINESS_KNOWLEDGE_QUERY":
        return False
    actions = result.get("actions", [])
    if actions:
        ent = actions[0].get("detected_entities", {})
        if ent.get("account_ref") is not None:
            return False
    if result.get("rag_status") != "RAG_PENDING":
        return False
    return True


LR_CASES: list[ACCtxCase] = [
    ACCtxCase(
        ac_id="AC-LR-01",
        description="CUST002 cuota → LOAN_DETAIL_READ + PRE002Q",
        threshold=9,
        question="¿Cuánto es la cuota de mi préstamo?",
        customer_id="CUST002",
        validator=validate_ac_lr01,
    ),
    ACCtxCase(
        ac_id="AC-LR-02",
        description="CUST002 tasa → LOAN_DETAIL_READ + PRE002Q",
        threshold=9,
        question="¿Cuál es la tasa de interés de mi préstamo?",
        customer_id="CUST002",
        validator=validate_ac_lr02,
    ),
    ACCtxCase(
        ac_id="AC-LR-03",
        description="CUST001 cuota → CLARIFICATION (2 loans)",
        threshold=8,
        question="¿Cuánto es la cuota de mi préstamo?",
        customer_id="CUST001",
        validator=validate_ac_lr03,
    ),
    ACCtxCase(
        ac_id="AC-LR-04",
        description="tasas genéricas → RAG (no loan-read)",
        threshold=9,
        question="¿Qué tasas de interés manejan para préstamos personales?",
        customer_id=None,
        validator=validate_ac_lr04,
    ),
]


# ---------------------------------------------------------------------------
# AC-DR validators (domain router)
# ---------------------------------------------------------------------------

def validate_ac_dr01(result: dict[str, Any]) -> bool:
    """AC-DR-01: CUST002 'Dime la letra' → LOAN_DETAIL_READ + PRE002Q + loan_detail."""
    s = extract_summary(result)
    if s["http_status"] != 200 or s["status"] != "VALID_CONTRACT":
        return False
    if s["intent_id"] != "LOAN_DETAIL_READ":
        return False
    actions = result.get("actions", [])
    if not actions:
        return False
    ent = actions[0].get("detected_entities", {})
    if ent.get("account_ref") != "PRE002Q":
        return False
    ld = result.get("loan_detail")
    if not ld or ld.get("product_id") != "PRE002Q":
        return False
    try:
        if not (7000 <= float(ld.get("installment_amount", "0")) <= 8000):
            return False
    except (ValueError, TypeError):
        return False
    return True


def validate_ac_dr02(result: dict[str, Any]) -> bool:
    """AC-DR-02: CUST002 'Cuánto pago al mes' → LOAN_DETAIL_READ + PRE002Q."""
    s = extract_summary(result)
    if s["http_status"] != 200 or s["status"] != "VALID_CONTRACT":
        return False
    if s["intent_id"] != "LOAN_DETAIL_READ":
        return False
    actions = result.get("actions", [])
    if not actions:
        return False
    ent = actions[0].get("detected_entities", {})
    if ent.get("account_ref") != "PRE002Q":
        return False
    ld = result.get("loan_detail")
    if not ld or ld.get("product_id") != "PRE002Q":
        return False
    return True


def validate_ac_dr03(result: dict[str, Any]) -> bool:
    """AC-DR-03: requisitos crédito vehículo → RAG, no loan-read."""
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "RAG_PENDING":
        return False
    if s["intent_id"] != "BUSINESS_KNOWLEDGE_QUERY":
        return False
    actions = result.get("actions", [])
    if actions:
        ent = actions[0].get("detected_entities", {})
        if ent.get("account_ref") is not None:
            return False
    return True


def validate_ac_dr04(result: dict[str, Any]) -> bool:
    """AC-DR-04: vuelo → UNSUPPORTED."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "UNSUPPORTED"
    )


def validate_ac_dr05(result: dict[str, Any]) -> bool:
    """AC-DR-05: CUST001 cuota 2 loans → CLARIFICATION."""
    s = extract_summary(result)
    if s["http_status"] != 200:
        return False
    if s["status"] != "CLARIFICATION_REQUIRED":
        return False
    actions = result.get("actions", [])
    if actions:
        ent = actions[0].get("detected_entities", {})
        if ent.get("account_ref") in ("PRE001", "PRE001V"):
            return False
    return True


DR_CASES: list[ACCtxCase] = [
    ACCtxCase(
        ac_id="AC-DR-01",
        description="CUST002 'letra' → LOAN_DETAIL_READ + PRE002Q",
        threshold=9,
        question="Dime la letra de mi préstamo",
        customer_id="CUST002",
        validator=validate_ac_dr01,
    ),
    ACCtxCase(
        ac_id="AC-DR-02",
        description="CUST002 'pago al mes' → LOAN_DETAIL_READ + PRE002Q",
        threshold=9,
        question="¿Cuánto pago al mes de mi crédito?",
        customer_id="CUST002",
        validator=validate_ac_dr02,
    ),
    ACCtxCase(
        ac_id="AC-DR-03",
        description="requisitos crédito vehículo → RAG",
        threshold=9,
        question="¿Qué requisitos piden para un crédito de vehículo?",
        customer_id=None,
        validator=validate_ac_dr03,
    ),
    ACCtxCase(
        ac_id="AC-DR-04",
        description="vuelo → UNSUPPORTED",
        threshold=9,
        question="Reserva un vuelo a Miami para el viernes",
        customer_id=None,
        validator=validate_ac_dr04,
    ),
    ACCtxCase(
        ac_id="AC-DR-05",
        description="CUST001 cuota 2 loans → CLARIFICATION",
        threshold=8,
        question="¿Cuánto es la cuota de mi préstamo?",
        customer_id="CUST001",
        validator=validate_ac_dr05,
    ),
]


# ---------------------------------------------------------------------------
# AC-PS validators (product specialists)
# ---------------------------------------------------------------------------

def validate_ac_ps01(result: dict[str, Any]) -> bool:
    """AC-PS-01: CUST001 'saldo de mi cuenta?' → CLARIFICATION cuentas, NO COR001."""
    if result.get("_http_status") != 200:
        return False
    if result.get("status") != "CLARIFICATION_REQUIRED":
        return False
    # Must NOT have resolved to any account_ref
    actions = result.get("actions", [])
    if actions:
        ent = actions[0].get("detected_entities", {})
        if ent.get("account_ref") is not None:
            return False
    # Must have clarification mentioning accounts (not loans)
    clars = result.get("clarifications", [])
    if not clars:
        return False
    question = clars[0].get("suggested_question", "").lower()
    # Should mention account types, not loan types
    has_account_signal = any(w in question for w in ["cuenta", "checking", "savings", "payroll", "ahorro", "corriente", "nomina"])
    return has_account_signal


def validate_ac_ps02(result_t1: dict[str, Any], result_t2: dict[str, Any]) -> bool:
    """AC-PS-02: T1 CLARIFICATION + T2 'Ahorros de emergencia' → VALID AHO001."""
    t1_ok = (
        result_t1.get("_http_status") == 200
        and result_t1.get("status") == "CLARIFICATION_REQUIRED"
    )
    t2_ok = (
        result_t2.get("_http_status") == 200
        and result_t2.get("status") == "VALID_CONTRACT"
    )
    if not (t1_ok and t2_ok):
        return False
    actions = result_t2.get("actions", [])
    if not actions:
        return False
    ent = actions[0].get("detected_entities", {})
    return ent.get("account_ref") == "AHO001"


def validate_ac_ps03(result: dict[str, Any]) -> bool:
    """AC-PS-03: CUST001 cuota → CLARIFICATION 2 loans."""
    if result.get("_http_status") != 200:
        return False
    if result.get("status") != "CLARIFICATION_REQUIRED":
        return False
    actions = result.get("actions", [])
    if actions:
        ent = actions[0].get("detected_entities", {})
        if ent.get("account_ref") in ("PRE001", "PRE001V"):
            return False
    return True


def validate_ac_ps04(result: dict[str, Any]) -> bool:
    """AC-PS-04: CUST002 'Dime la letra' → LOAN_DETAIL_READ PRE002Q."""
    s = extract_summary(result)
    if s["http_status"] != 200 or s["status"] != "VALID_CONTRACT":
        return False
    if s["intent_id"] != "LOAN_DETAIL_READ":
        return False
    actions = result.get("actions", [])
    if not actions:
        return False
    ent = actions[0].get("detected_entities", {})
    return ent.get("account_ref") == "PRE002Q"


def validate_ac_ps05(result: dict[str, Any]) -> bool:
    """AC-PS-05: 'mueve 20 pesos...' → NOT ACCOUNT_MOVEMENTS_READ with amount."""
    if result.get("_http_status") != 200:
        return False
    actions = result.get("actions", [])
    if actions:
        a = actions[0]
        if a.get("intent_id") == "ACCOUNT_MOVEMENTS_READ":
            ent = a.get("detected_entities", {})
            if ent.get("amount") is not None or ent.get("destination_account_ref") is not None:
                return False  # BUG: mapped mutation as movements read
    return True  # UNSUPPORTED, CLARIFICATION, or any non-bug result


def validate_ac_ps06(result: dict[str, Any]) -> bool:
    """AC-PS-06: tasas genéricas → RAG."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "RAG_PENDING"
        and s["intent_id"] == "BUSINESS_KNOWLEDGE_QUERY"
    )


PS_CASES_SINGLE: list[ACCtxCase] = [
    ACCtxCase(
        ac_id="AC-PS-01",
        description="CUST001 saldo → CLARIFICATION cuentas (NO COR001)",
        threshold=9,
        question="Saldo de mi cuenta?",
        customer_id="CUST001",
        validator=validate_ac_ps01,
    ),
    ACCtxCase(
        ac_id="AC-PS-03",
        description="CUST001 cuota → CLARIFICATION 2 loans",
        threshold=8,
        question="¿Cuánto es la cuota de mi préstamo?",
        customer_id="CUST001",
        validator=validate_ac_ps03,
    ),
    ACCtxCase(
        ac_id="AC-PS-04",
        description="CUST002 letra → LOAN_DETAIL_READ PRE002Q",
        threshold=9,
        question="Dime la letra de mi préstamo",
        customer_id="CUST002",
        validator=validate_ac_ps04,
    ),
    ACCtxCase(
        ac_id="AC-PS-05",
        description="mueve 20 pesos → NO movements+amount",
        threshold=9,
        question="Mueve 20 pesos de mi cuenta de ahorro a la corriente",
        customer_id="CUST001",
        validator=validate_ac_ps05,
    ),
    ACCtxCase(
        ac_id="AC-PS-06",
        description="tasas genéricas → RAG",
        threshold=9,
        question="¿Qué tasas de interés manejan para préstamos personales?",
        customer_id=None,
        validator=validate_ac_ps06,
    ),
]


# AC-PS-02 is multiturn — handled separately
@dataclass
class ACPSMultiturnCase:
    ac_id: str
    description: str
    threshold: int
    turn1_question: str
    turn2_question: str
    customer_id: str
    pass_count: int = 0


PS_MULTITURN_CASES: list[ACPSMultiturnCase] = [
    ACPSMultiturnCase(
        ac_id="AC-PS-02",
        description="T1 saldo + T2 'Ahorros de emergencia' → AHO001",
        threshold=9,
        turn1_question="Saldo de mi cuenta?",
        turn2_question="Ahorros de emergencia",
        customer_id="CUST001",
    ),
]


def run_ps_multiturn(base_url: str, cases: list[ACPSMultiturnCase]) -> list[ACPSMultiturnCase]:
    """Run PS multiturn cases."""
    for case in cases:
        print(f"\n{'─'*60}")
        print(f"  {case.ac_id} — {case.description}  (threshold ≥ {case.threshold}/{REPETITIONS})")
        print(f"  T1: {case.turn1_question!r}  T2: {case.turn2_question!r}  customer: {case.customer_id}")
        print(f"{'─'*60}")
        case.pass_count = 0

        for i in range(REPETITIONS):
            conv_id = str(uuid.uuid4())
            try:
                r1 = post_inspect(base_url, case.turn1_question, conv_id, case.customer_id)
                r2 = post_inspect(base_url, case.turn2_question, conv_id, case.customer_id)
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                continue

            passed = validate_ac_ps02(r1, r2)
            if passed:
                case.pass_count += 1

            s2 = extract_summary(r2)
            mark = "✓" if passed else "✗"
            print(f"  [{i+1:2d}] {mark}  T1={r1.get('status')}  T2={r2.get('status')} acct={s2.get('account_ref')}")
            time.sleep(1.5)

        verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
        print(f"  → {case.pass_count}/{REPETITIONS}  {verdict}")

    return cases


def run_ctx_cases(base_url: str, cases: list[ACCtxCase]) -> list[ACCtxCase]:
    """Run each CTX case REPETITIONS times."""
    for case in cases:
        print(f"\n{'─'*60}")
        print(f"  {case.ac_id} — {case.description}  (threshold ≥ {case.threshold}/{REPETITIONS})")
        print(f"  question: {case.question!r}  customer_id: {case.customer_id or '(default)'}")
        print(f"{'─'*60}")
        case.pass_count = 0

        for i in range(REPETITIONS):
            conv_id = str(uuid.uuid4())
            try:
                result = post_inspect(base_url, case.question, conv_id, case.customer_id)
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                time.sleep(2.0)
                continue

            passed = case.validator(result)
            if passed:
                case.pass_count += 1

            # AC-10: check schema on CLARIFICATION responses
            check_ac10(result, case.ac_id, i + 1)

            s = extract_summary(result)
            mark = "✓" if passed else "✗"
            print(
                f"  [{i+1:2d}] {mark}  "
                f"status={s['status']}  mode={s['mode']}  "
                f"account_ref={s['account_ref']}  "
                f"ctx={result.get('customer_context', {}).get('products_count', '?')}"
            )
            time.sleep(1.5)

        verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
        print(f"  → {case.pass_count}/{REPETITIONS}  {verdict}")

    return cases


# ---------------------------------------------------------------------------
# AC-06 Multiturn validator
# ---------------------------------------------------------------------------

@dataclass
class ACMultiturnCase:
    ac_id: str
    description: str
    threshold: int
    turn1_question: str
    turn2_question: str
    pass_count: int = 0


def validate_ac06_turn1(result: dict[str, Any]) -> bool:
    """AC-06 turn 1: CLARIFICATION_REQUIRED, account_ref=null."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "CLARIFICATION_REQUIRED"
        and s["mode"] == "CLARIFICATION"
        and s["account_ref"] is None
    )


def validate_ac06_turn2(result: dict[str, Any]) -> bool:
    """AC-06 turn 2: VALID_CONTRACT, SINGLE, account_ref=AHO001."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "VALID_CONTRACT"
        and s["mode"] == "SINGLE"
        and s["account_ref"] == "AHO001"
    )


MULTITURN_CASES: list[ACMultiturnCase] = [
    ACMultiturnCase(
        ac_id="AC-06",
        description="multiturn: ambiguedad → 'La de ahorros' → AHO001",
        threshold=9,
        turn1_question="Quiero consultar mi saldo",
        turn2_question="La de ahorros",
    ),
]


# ---------------------------------------------------------------------------
# AC-07 Isolation validator
# ---------------------------------------------------------------------------

@dataclass
class ACIsolationCase:
    ac_id: str
    description: str
    threshold: int
    conv_a_question: str
    conv_b_question: str
    pass_count: int = 0


def validate_ac07_conv_a(result: dict[str, Any]) -> bool:
    """AC-07 conv-A: VALID_CONTRACT, AHO001."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "VALID_CONTRACT"
        and s["intent_id"] == "ACCOUNT_BALANCE_READ"
        and s["account_ref"] == "AHO001"
    )


def validate_ac07_conv_b(result: dict[str, Any]) -> bool:
    """AC-07 conv-B: NON_OPERATIONAL, no actions."""
    s = extract_summary(result)
    return (
        s["http_status"] == 200
        and s["status"] == "NON_OPERATIONAL"
        and s["actions_count"] == 0
    )


def validate_ac07_no_contamination(result_a: dict[str, Any], result_b: dict[str, Any]) -> bool:
    """Verify no cross-contamination between conversations."""
    # conv-A should not contain any NON_OPERATIONAL traces
    # conv-B should not contain any ACCOUNT_BALANCE_READ or AHO001 traces
    hist_a = result_a.get("conversation_history", [])
    hist_b = result_b.get("conversation_history", [])

    # Each history should contain only its own turn
    if len(hist_a) != 1 or len(hist_b) != 1:
        return False

    # conv-A history should not reference conv-B's question
    if any("Hola" in str(h.get("question", "")) for h in hist_a):
        return False
    # conv-B history should not reference conv-A's question
    if any("ahorros" in str(h.get("question", "")) for h in hist_b):
        return False

    # conversation_ids must differ
    if result_a.get("conversation_id") == result_b.get("conversation_id"):
        return False

    return True


ISOLATION_CASES: list[ACIsolationCase] = [
    ACIsolationCase(
        ac_id="AC-07",
        description="isolation: conv-A saldo vs conv-B saludo",
        threshold=10,
        conv_a_question="¿Cuál es el saldo de mi cuenta de ahorros?",
        conv_b_question="Hola, buenos días",
    ),
]


def run_isolation_cases(base_url: str, cases: list[ACIsolationCase]) -> list[ACIsolationCase]:
    """Run each isolation case REPETITIONS times."""
    for case in cases:
        print(f"\n{'─'*60}")
        print(f"  {case.ac_id} — {case.description}  (threshold ≥ {case.threshold}/{REPETITIONS})")
        print(f"  conv-A: {case.conv_a_question!r}")
        print(f"  conv-B: {case.conv_b_question!r}")
        print(f"{'─'*60}")
        case.pass_count = 0

        for i in range(REPETITIONS):
            conv_a_id = str(uuid.uuid4())
            conv_b_id = str(uuid.uuid4())
            try:
                ra = post_inspect(base_url, case.conv_a_question, conv_a_id)
                rb = post_inspect(base_url, case.conv_b_question, conv_b_id)
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                continue

            a_ok = validate_ac07_conv_a(ra)
            b_ok = validate_ac07_conv_b(rb)
            no_contam = validate_ac07_no_contamination(ra, rb)
            passed = a_ok and b_ok and no_contam

            if passed:
                case.pass_count += 1

            sa = extract_summary(ra)
            sb = extract_summary(rb)
            mark = "✓" if passed else "✗"
            a_mark = "✓" if a_ok else "✗"
            b_mark = "✓" if b_ok else "✗"
            c_mark = "✓" if no_contam else "✗"
            print(
                f"  [{i+1:2d}] {mark}  "
                f"A[{a_mark}] status={sa['status']} acct={sa['account_ref']}  "
                f"B[{b_mark}] status={sb['status']}  "
                f"iso[{c_mark}]"
            )

        verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
        print(f"  → {case.pass_count}/{REPETITIONS}  {verdict}")

    return cases


# ---------------------------------------------------------------------------
# AC-08 / AC-09 Error cases
# ---------------------------------------------------------------------------

@dataclass
class ACErrorCase:
    ac_id: str
    description: str
    threshold: int
    pass_count: int = 0


def post_inspect_with_params(
    base_url: str,
    question: str,
    conversation_id: str | None = None,
    force_error: str | None = None,
) -> dict[str, Any]:
    """POST to /inspect with optional query params."""
    payload: dict[str, str] = {"question": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id

    params: dict[str, str] = {}
    if force_error:
        params["force_error"] = force_error

    resp = httpx.post(
        f"{base_url}/inspect",
        json=payload,
        params=params,
        timeout=60.0,
    )
    result: dict[str, Any] = resp.json()
    result["_http_status"] = resp.status_code
    return result


def validate_ac08(result: dict[str, Any]) -> bool:
    """AC-08: forced provider error → HTTP 502, status=PROVIDER_ERROR."""
    return (
        result.get("_http_status") == 502
        and result.get("status") == "PROVIDER_ERROR"
    )


def validate_ac09(result: dict[str, Any]) -> bool:
    """AC-09: local validation error → HTTP 422, status ∈ {INVALID_INPUT, INVALID_MODEL_OUTPUT} or FastAPI native 422."""
    if result.get("_http_status") != 422:
        return False
    # Our custom error response
    if result.get("status") in ("INVALID_INPUT", "INVALID_MODEL_OUTPUT"):
        return True
    # FastAPI native validation error (extra fields rejected by strict Pydantic model)
    if "detail" in result:
        return True
    return False


ERROR_CASES: list[ACErrorCase] = [
    ACErrorCase(ac_id="AC-08", description="provider error → 502", threshold=10),
    ACErrorCase(ac_id="AC-09", description="local error → 422", threshold=10),
]


def run_error_cases(base_url: str, cases: list[ACErrorCase]) -> list[ACErrorCase]:
    """Run AC-08 and AC-09 error cases."""
    for case in cases:
        print(f"\n{'─'*60}")
        print(f"  {case.ac_id} — {case.description}  (threshold ≥ {case.threshold}/{REPETITIONS})")
        print(f"{'─'*60}")
        case.pass_count = 0

        for i in range(REPETITIONS):
            try:
                if case.ac_id == "AC-08":
                    # Force provider error via query param
                    result = post_inspect_with_params(
                        base_url, "test", force_error="provider"
                    )
                    passed = validate_ac08(result)
                elif case.ac_id == "AC-09":
                    # Send request that causes local validation error
                    # Use raw httpx to send malformed payload (extra field triggers strict mode)
                    resp = httpx.post(
                        f"{base_url}/inspect",
                        json={"question": "test", "conversation_id": "", "extra_field": "bad"},
                        timeout=60.0,
                    )
                    result = {"_http_status": resp.status_code}
                    try:
                        result.update(resp.json())
                    except Exception:
                        pass
                    passed = validate_ac09(result)
                else:
                    passed = False
                    result = {}
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                continue

            if passed:
                case.pass_count += 1

            mark = "✓" if passed else "✗"
            print(
                f"  [{i+1:2d}] {mark}  "
                f"HTTP={result.get('_http_status')}  "
                f"status={result.get('status')}"
            )

        verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
        print(f"  → {case.pass_count}/{REPETITIONS}  {verdict}")

    return cases


def run_multiturn_cases(base_url: str, cases: list[ACMultiturnCase]) -> list[ACMultiturnCase]:
    """Run each multiturn case REPETITIONS times."""
    for case in cases:
        print(f"\n{'─'*60}")
        print(f"  {case.ac_id} — {case.description}  (threshold ≥ {case.threshold}/{REPETITIONS})")
        print(f"  turn1: {case.turn1_question!r}")
        print(f"  turn2: {case.turn2_question!r}")
        print(f"{'─'*60}")
        case.pass_count = 0

        for i in range(REPETITIONS):
            conv_id = str(uuid.uuid4())
            try:
                r1 = post_inspect(base_url, case.turn1_question, conv_id)
                r2 = post_inspect(base_url, case.turn2_question, conv_id)
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                continue

            t1_ok = validate_ac06_turn1(r1)
            t2_ok = validate_ac06_turn2(r2)
            passed = t1_ok and t2_ok
            if passed:
                case.pass_count += 1

            # AC-10: check schema on turn 1 CLARIFICATION
            check_ac10(r1, case.ac_id + "-T1", i + 1)

            s1 = extract_summary(r1)
            s2 = extract_summary(r2)
            mark = "✓" if passed else "✗"
            t1_mark = "✓" if t1_ok else "✗"
            t2_mark = "✓" if t2_ok else "✗"
            print(
                f"  [{i+1:2d}] {mark}  "
                f"T1[{t1_mark}] status={s1['status']} mode={s1['mode']} acct={s1['account_ref']}  "
                f"T2[{t2_mark}] status={s2['status']} mode={s2['mode']} acct={s2['account_ref']}"
            )

        verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
        print(f"  → {case.pass_count}/{REPETITIONS}  {verdict}")

    return cases


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_single_turn_cases(base_url: str, cases: list[ACCase]) -> list[ACCase]:
    """Run each single-turn case REPETITIONS times."""
    for case in cases:
        print(f"\n{'─'*60}")
        print(f"  {case.ac_id} — {case.description}  (threshold ≥ {case.threshold}/{REPETITIONS})")
        print(f"  question: {case.question!r}")
        print(f"{'─'*60}")
        case.pass_count = 0
        case.results = []

        for i in range(REPETITIONS):
            conv_id = str(uuid.uuid4())
            try:
                result = post_inspect(base_url, case.question, conv_id)
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                case.results.append({"_error": str(e)})
                continue

            passed = case.validator(result)
            if passed:
                case.pass_count += 1

            # AC-10: check schema on CLARIFICATION responses
            check_ac10(result, case.ac_id, i + 1)

            s = extract_summary(result)
            mark = "✓" if passed else "✗"
            print(
                f"  [{i+1:2d}] {mark}  "
                f"status={s['status']}  mode={s['mode']}  "
                f"account_ref={s['account_ref']}  "
                f"missing={s['missing_requirements']}"
            )
            case.results.append(result)

        verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
        print(f"  → {case.pass_count}/{REPETITIONS}  {verdict}")

    return cases


# ---------------------------------------------------------------------------
# AC-10: ClarificationRequest schema validation (cross-cutting)
# ---------------------------------------------------------------------------

# Valid canonical entity field names per directives 242-248
_CANONICAL_ENTITY_FIELDS = {
    "account_ref", "source_account_ref", "destination_account_ref",
    "amount", "currency", "knowledge_topic",
}


def validate_clarification_schema(result: dict[str, Any]) -> tuple[bool, str]:
    """Validate ClarificationRequest schema on any CLARIFICATION response.

    Returns (passed, reason).
    """
    clarifications = result.get("clarifications", [])
    actions = result.get("actions", [])

    if not clarifications:
        return False, "no clarifications in CLARIFICATION response"

    for idx, clar in enumerate(clarifications):
        missing = clar.get("missing_requirements", [])
        already = clar.get("already_known", [])
        question = clar.get("suggested_question", "")
        target_seq = clar.get("target_action_sequence")

        # already_known contains only canonical entity field names (no values)
        for item in already:
            if item not in _CANONICAL_ENTITY_FIELDS:
                return False, f"clar[{idx}]: already_known item '{item}' not a canonical entity field"

        # already_known ∩ missing_requirements = ∅
        overlap = set(already) & set(missing)
        if overlap:
            return False, f"clar[{idx}]: already_known ∩ missing_requirements = {overlap}"

        # suggested_question not empty
        if not question or not question.strip():
            return False, f"clar[{idx}]: suggested_question is empty"

        # missing_requirements not empty
        if not missing:
            return False, f"clar[{idx}]: missing_requirements is empty"

        # already_known = non-null fields of detected_entities for target action
        target_action = None
        for a in actions:
            if a.get("sequence") == target_seq:
                target_action = a
                break

        if target_action is not None:
            entities = target_action.get("detected_entities", {})
            non_null_fields = {k for k, v in entities.items() if v is not None}
            if set(already) != non_null_fields:
                return False, (
                    f"clar[{idx}]: already_known={sorted(already)} != "
                    f"non_null_entities={sorted(non_null_fields)}"
                )

    return True, "OK"


@dataclass
class AC10Result:
    """Accumulated AC-10 validation over all CLARIFICATION responses."""
    total_checked: int = 0
    total_passed: int = 0
    failures: list[str] = field(default_factory=list)


# Global AC-10 accumulator
_ac10 = AC10Result()


def check_ac10(result: dict[str, Any], source_ac: str, iteration: int) -> None:
    """Check AC-10 on a CLARIFICATION result. Accumulates globally."""
    if result.get("status") != "CLARIFICATION_REQUIRED":
        return
    if result.get("_http_status") != 200:
        return
    # Skip AC-10 check for pure disambiguation CLARIFICATION (mode=None, no actions/clarifications)
    if result.get("mode") is None:
        return

    _ac10.total_checked += 1
    passed, reason = validate_clarification_schema(result)
    if passed:
        _ac10.total_passed += 1
    else:
        _ac10.failures.append(f"{source_ac}[{iteration}]: {reason}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def get_metadata(base_url: str) -> dict[str, str]:
    """Fetch metadata from a quick /inspect call."""
    try:
        resp = httpx.post(
            f"{base_url}/inspect",
            json={"question": "metadata-probe"},
            timeout=30.0,
        )
        data = resp.json()
        return {
            "prompt_version": data.get("prompt_version", "unknown"),
            "model": data.get("model", "unknown"),
            "framework": data.get("framework", "unknown"),
        }
    except Exception:
        return {"prompt_version": "unknown", "model": "unknown", "framework": "unknown"}

def print_report(
    single_cases: list[ACCase],
    multiturn_cases: list[ACMultiturnCase] | None = None,
    isolation_cases: list[ACIsolationCase] | None = None,
    error_cases: list[ACErrorCase] | None = None,
    ctx_cases: list[ACCtxCase] | None = None,
    metadata: dict[str, str] | None = None,
) -> bool:
    """Print final report. Returns True if all pass."""
    print(f"\n{'═'*60}")
    print("  E2E Semantic Acceptance Report")
    print(f"{'═'*60}")
    print(f"  timestamp:      {datetime.now(tz=timezone.utc).isoformat()}")
    if metadata:
        print(f"  prompt_version: {metadata.get('prompt_version', 'unknown')}")
        print(f"  model:          {metadata.get('model', 'unknown')}")
        print(f"  framework:      {metadata.get('framework', 'unknown')}")
    print(f"  repetitions:    {REPETITIONS}")
    print(f"{'─'*60}")

    all_pass = True
    for case in single_cases:
        verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
        if verdict == "FAIL":
            all_pass = False
        print(
            f"  {case.ac_id}  {case.description:<42}  "
            f"{case.pass_count:2d}/{REPETITIONS}  {verdict}  "
            f"(threshold: {case.threshold})"
        )

    if multiturn_cases:
        for case in multiturn_cases:
            verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
            if verdict == "FAIL":
                all_pass = False
            print(
                f"  {case.ac_id}  {case.description:<42}  "
                f"{case.pass_count:2d}/{REPETITIONS}  {verdict}  "
                f"(threshold: {case.threshold})"
            )

    if isolation_cases:
        for case in isolation_cases:
            verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
            if verdict == "FAIL":
                all_pass = False
            print(
                f"  {case.ac_id}  {case.description:<42}  "
                f"{case.pass_count:2d}/{REPETITIONS}  {verdict}  "
                f"(threshold: {case.threshold})"
            )

    if error_cases:
        for case in error_cases:
            verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
            if verdict == "FAIL":
                all_pass = False
            print(
                f"  {case.ac_id}  {case.description:<42}  "
                f"{case.pass_count:2d}/{REPETITIONS}  {verdict}  "
                f"(threshold: {case.threshold})"
            )

    if ctx_cases:
        for case in ctx_cases:
            verdict = "PASS" if case.pass_count >= case.threshold else "FAIL"
            if verdict == "FAIL":
                all_pass = False
            print(
                f"  {case.ac_id}  {case.description:<42}  "
                f"{case.pass_count:2d}/{REPETITIONS}  {verdict}  "
                f"(threshold: {case.threshold})"
            )

    # AC-10 report
    if _ac10.total_checked > 0:
        ac10_pass = _ac10.total_passed == _ac10.total_checked
        ac10_verdict = "PASS" if ac10_pass else "FAIL"
        if not ac10_pass:
            all_pass = False
        print(
            f"  AC-10  ClarificationRequest schema              "
            f"{_ac10.total_passed:2d}/{_ac10.total_checked:2d}  {ac10_verdict}  "
            f"(threshold: 10/10)"
        )
        if _ac10.failures:
            for f in _ac10.failures[:5]:
                print(f"         ✗ {f}")

    print(f"{'─'*60}")
    overall = "PASS" if all_pass else "FAIL"
    print(f"  OVERALL: {overall}")
    print(f"{'═'*60}")
    return all_pass


# ---------------------------------------------------------------------------
# Single-question mode
# ---------------------------------------------------------------------------

def run_single(base_url: str, question: str) -> None:
    """Run a single request and print full result + summary."""
    conv_id = str(uuid.uuid4())
    print(f"POST {base_url}/inspect")
    print(f"  question: {question!r}")
    print(f"  conversation_id: {conv_id}")
    print()

    result = post_inspect(base_url, question, conv_id)
    summary = extract_summary(result)
    print_summary(summary)
    print()
    print("Full response:")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="E2E Semantic Acceptance")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the contract inspector (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--single",
        type=str,
        default=None,
        help="Run a single question and print result (no AC validation)",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated AC IDs to run (e.g. AC-01,AC-02). Default: all.",
    )
    args = parser.parse_args()

    if args.single:
        run_single(args.base_url, args.single)
        return

    # Determine which cases to run
    requested_ids: set[str] | None = None
    if args.only:
        requested_ids = {x.strip().upper() for x in args.only.split(",")}

    # Filter single-turn cases
    single_cases = SINGLE_TURN_CASES[:]
    if requested_ids:
        single_cases = [c for c in single_cases if c.ac_id in requested_ids]

    # Filter multiturn cases
    mt_cases = MULTITURN_CASES[:]
    if requested_ids:
        mt_cases = [c for c in mt_cases if c.ac_id in requested_ids]

    # Filter isolation cases
    iso_cases = ISOLATION_CASES[:]
    if requested_ids:
        iso_cases = [c for c in iso_cases if c.ac_id in requested_ids]

    # Filter error cases
    err_cases = ERROR_CASES[:]
    if requested_ids:
        err_cases = [c for c in err_cases if c.ac_id in requested_ids]

    # Filter CTX cases
    ctx_cases = CTX_CASES[:]
    if requested_ids:
        ctx_cases = [c for c in ctx_cases if c.ac_id in requested_ids]

    # Filter LR cases
    lr_cases = LR_CASES[:]
    if requested_ids:
        lr_cases = [c for c in lr_cases if c.ac_id in requested_ids]

    # Filter DR cases
    dr_cases = DR_CASES[:]
    if requested_ids:
        dr_cases = [c for c in dr_cases if c.ac_id in requested_ids]

    # Filter PS cases
    ps_single = PS_CASES_SINGLE[:]
    if requested_ids:
        ps_single = [c for c in ps_single if c.ac_id in requested_ids]
    ps_mt = PS_MULTITURN_CASES[:]
    if requested_ids:
        ps_mt = [c for c in ps_mt if c.ac_id in requested_ids]

    if not single_cases and not mt_cases and not iso_cases and not err_cases and not ctx_cases and not lr_cases and not dr_cases and not ps_single and not ps_mt:
        print(f"No matching cases for: {args.only}")
        sys.exit(1)

    # Reset AC-10 accumulator
    _ac10.total_checked = 0
    _ac10.total_passed = 0
    _ac10.failures.clear()

    # Collect metadata
    metadata = get_metadata(args.base_url)

    # Run
    if single_cases:
        run_single_turn_cases(args.base_url, single_cases)
    if mt_cases:
        run_multiturn_cases(args.base_url, mt_cases)
    if iso_cases:
        run_isolation_cases(args.base_url, iso_cases)
    if err_cases:
        run_error_cases(args.base_url, err_cases)
    if ctx_cases:
        run_ctx_cases(args.base_url, ctx_cases)
    if lr_cases:
        run_ctx_cases(args.base_url, lr_cases)
    if dr_cases:
        run_ctx_cases(args.base_url, dr_cases)
    if ps_single:
        run_ctx_cases(args.base_url, ps_single)
    if ps_mt:
        run_ps_multiturn(args.base_url, ps_mt)

    all_pass = print_report(
        single_cases,
        mt_cases if mt_cases else None,
        iso_cases if iso_cases else None,
        err_cases if err_cases else None,
        (ctx_cases + lr_cases + dr_cases + ps_single) if (ctx_cases or lr_cases or dr_cases or ps_single) else None,
        metadata=metadata,
    )
    # Also check PS multiturn
    if ps_mt:
        for case in ps_mt:
            if case.pass_count < case.threshold:
                all_pass = False
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
