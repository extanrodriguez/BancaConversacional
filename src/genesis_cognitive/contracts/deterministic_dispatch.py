"""Deterministic contract dispatch — canonical Genesis 1.2 operation_request.

Source of truth: contratos/GENESIS_Contratos_Canonicos_Capa_Cognitiva_v1.md
+ Catalogo JSON Proyecto Genesis 1.2.0.

NO LLM. NO Capa 0/1. Pure regex-based parser for structured Lab commands.
Cognitiva NEVER executes Core. Only emits the operation_request.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

# Simulated customer pattern: CUST001..CUST010
_SIMULATED_PATTERN = re.compile(r"^CUST0(0[1-9]|10)$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------

_ACCENT_MAP = str.maketrans("áéíóúñü", "aeiounu")


def _normalize(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower().translate(_ACCENT_MAP))


# ---------------------------------------------------------------------------
# Command patterns (case-insensitive, accents optional)
# ---------------------------------------------------------------------------

# === QUERIES ===
_P01 = re.compile(r"^consulta\s+portafolio$")
_P09 = re.compile(r"^consulta\s+portafolio\s+activo$")
_P02 = re.compile(r"^consulta\s+(?:saldo\s+)?cuenta\s+(?:ahorros?\s+)?(\S+)(?:\s+moneda\s+(\S+))?$")
_P03 = re.compile(r"^consulta\s+cuenta\s+corriente\s+(\S+)(?:\s+moneda\s+(\S+))?$")
_P04 = re.compile(r"^consulta\s+cdt\s+(\S+)(?:\s+moneda\s+(\S+))?$")
_P10 = re.compile(r"^consulta\s+tarjeta\s+(\S+)$")
_P12 = re.compile(r"^consulta\s+prestamo\s+(\S+)$")
_P12B = re.compile(r"^consulta\s+cuota\s+prestamo\s+(\S+)$")
_P13 = re.compile(r"^simula\s+prestamo\s+tipo\s+(\S+)\s+monto\s+([\d.,]+)\s+plazo\s+(\d+)\s+moneda\s+(\S+)$")
_P15_REQ = re.compile(r"^consulta\s+requisitos\s+prestamo$")
_P15_APP = re.compile(r"^consulta\s+estado\s+solicitud\s+(\S+)$")
_P05 = re.compile(r"^rastrea\s+transferencia\s+(\S+)$")

# === MUTANTS ===
_M01 = re.compile(
    r"^dispara\s+movimiento\s+cuenta\s+origen\s+(\S+)\s+a\s+cuenta\s+destino\s+(\S+)"
    r"\s+valor\s+([\d.,]+)\s+moneda\s+(\S+)"
)
_M10 = re.compile(r"^paga\s+prestamo\s+(\S+)\s+valor\s+([\d.,]+)\s+moneda\s+(\S+)\s+desde\s+(\S+)$")
_P14_ABONO = re.compile(
    r"^abono\s+capital\s+prestamo\s+(\S+)\s+valor\s+([\d.,]+)\s+moneda\s+(\S+)"
    r"(?:\s+regla\s+(reducir_plazo|reducir_cuota))?"
)
_P11_REDIFERIR = re.compile(
    r"^rediferir\s+tarjeta\s+(\S+)\s+monto\s+([\d.,]+)\s+cuotas\s+(\d+)\s+moneda\s+(\S+)$"
)
_P11_AVANCE = re.compile(
    r"^avance\s+tarjeta\s+(\S+)\s+monto\s+([\d.,]+)\s+moneda\s+(\S+)$"
)

# ---------------------------------------------------------------------------
# Templates for error messages
# ---------------------------------------------------------------------------

COMMAND_TEMPLATES = [
    "Consulta portafolio",
    "Consulta portafolio activo",
    "Consulta saldo cuenta {account_id} [moneda {ccy}]",
    "Consulta cuenta corriente {account_id}",
    "Consulta cdt {cdt_id}",
    "Consulta tarjeta {card_id}",
    "Consulta prestamo {loan_id}",
    "Consulta cuota prestamo {loan_id}",
    "Simula prestamo tipo {VEHICLE|MORTGAGE|CONSUMO} monto {n} plazo {meses} moneda {ccy}",
    "Consulta requisitos prestamo",
    "Consulta estado solicitud {app_id}",
    "Rastrea transferencia {ref}",
    "Dispara movimiento cuenta origen {A} a cuenta destino {B} valor {N} moneda {CCY}",
    "Paga prestamo {id} valor {N} moneda {CCY} desde {cuenta_origen}",
    "Abono capital prestamo {id} valor {N} moneda {CCY} [regla REDUCIR_PLAZO|REDUCIR_CUOTA]",
    "Rediferir tarjeta {id} monto {N} cuotas {K} moneda {CCY}",
    "Avance tarjeta {id} monto {N} moneda {CCY}",
]

# ---------------------------------------------------------------------------
# Phase config
# ---------------------------------------------------------------------------

VALID_PHASES = ("ANALYZE", "VALIDATE", "EXECUTE")

_PHASE_CONFIG: dict[str, dict[str, Any]] = {
    "ANALYZE": {"requires_confirmation": False, "next_action": "review_or_validate"},
    "VALIDATE": {"requires_confirmation": True, "next_action": "await_confirmation"},
    "EXECUTE": {"requires_confirmation": False, "next_action": "execute_operation"},
}

# ---------------------------------------------------------------------------
# Parser → canonical parsed dict
# ---------------------------------------------------------------------------


def parse_command(command: str) -> dict[str, Any] | None:  # noqa: C901
    """Parse a deterministic command into canonical operation metadata."""
    norm = _normalize(command)

    # --- P01 ---
    if _P01.match(norm):
        return _q("PASSIVE_PORTFOLIO_QUERY", "P01", "PORTFOLIO_LIST", cap="PORTFOLIO",
                  scope="BLOCK", family="PASSIVE", group="PORTFOLIO_PASSIVE",
                  contract={"include_savings": True, "include_checking": True, "include_investments": True,
                            "currency_view": "ORIGINAL_AND_BASE", "base_currency": None})

    # --- P09 ---
    if _P09.match(norm):
        return _q("ACTIVE_PORTFOLIO_QUERY", "P09", "PORTFOLIO_LIST", cap="PORTFOLIO",
                  scope="BLOCK", family="ACTIVE", group="PORTFOLIO_ACTIVE",
                  contract={"include_credit_cards": True, "include_loans": True,
                            "currency_view": "ORIGINAL_AND_BASE", "base_currency": None})

    # --- P03 (before P02 — more specific) ---
    m = _P03.match(norm)
    if m:
        return _q("CHECKING_ACCOUNT_QUERY", "P03", "ACCOUNT_BALANCE_READ", cap="ACCOUNTS",
                  scope="ITEM", family="PASSIVE", group="CHECKING",
                  contract=_acct_contract(m.group(1).upper(), m.group(2), include_overdraft=True))

    # --- P02 ---
    m = _P02.match(norm)
    if m:
        return _q("SAVINGS_ACCOUNT_QUERY", "P02", "ACCOUNT_BALANCE_READ", cap="ACCOUNTS",
                  scope="ITEM", family="PASSIVE", group="SAVINGS",
                  contract=_acct_contract(m.group(1).upper(), m.group(2)))

    # --- P04 ---
    m = _P04.match(norm)
    if m:
        return _q("CDT_QUERY", "P04", "CDT_QUERY", cap="INVESTMENTS",
                  scope="ITEM", family="PASSIVE", group="CDT",
                  contract={"cdt_selector": {"cdt_id": m.group(1).upper(), "currency": (m.group(2) or "").upper() or None},
                            "query_scope": {"include_principal": True, "include_rates": True, "include_accrued_interest": True,
                                            "include_dates": True, "include_penalties": True, "include_auto_renewal": True,
                                            "include_tax_information": True}})

    # --- P10 ---
    m = _P10.match(norm)
    if m:
        return _q("CREDIT_CARD_QUERY", "P10", "CREDIT_CARD_QUERY", cap="CREDIT_CARD",
                  scope="ITEM", family="ACTIVE", group="CREDIT_CARD",
                  contract={"card_selector": {"card_id": m.group(1).upper()},
                            "query_scope": {"include_identity": True, "include_balances": True, "include_billing": True,
                                            "include_pricing": True, "include_rewards": True, "include_documents": False}})

    # --- P12B (cuota — before P12) ---
    m = _P12B.match(norm)
    if m:
        return _q("LOAN_QUERY", "P12", "LOAN_DETAIL_READ", cap="LOAN",
                  scope="ITEM", family="ACTIVE", group="LOAN",
                  contract={"loan_selector": {"loan_id": m.group(1).upper(), "loan_type": None, "currency": None},
                            "query_scope": {"include_identity": True, "include_balances": False, "include_rates": False,
                                            "include_next_installment": True, "include_term_summary": False,
                                            "include_guarantees": False, "include_insurance": False}})

    # --- P12 ---
    m = _P12.match(norm)
    if m:
        return _q("LOAN_QUERY", "P12", "LOAN_DETAIL_READ", cap="LOAN",
                  scope="ITEM", family="ACTIVE", group="LOAN",
                  contract={"loan_selector": {"loan_id": m.group(1).upper(), "loan_type": None, "currency": None},
                            "query_scope": {"include_identity": True, "include_balances": True, "include_rates": True,
                                            "include_next_installment": True, "include_term_summary": True,
                                            "include_guarantees": False, "include_insurance": False}})

    # --- P13 ---
    m = _P13.match(norm)
    if m:
        return _q("LOAN_SIMULATION_QUERY", "P13", "LOAN_SIMULATION", cap="LOAN",
                  scope="ITEM", family="ACTIVE", group="LOAN",
                  contract={"loan_type": m.group(1).upper(), "requested_amount": m.group(2).replace(",", ""),
                            "term_months": int(m.group(3)), "currency": m.group(4).upper(),
                            "down_payment_amount": None, "include_insurance_estimate": False})

    # --- P15 requisitos ---
    if _P15_REQ.match(norm):
        return _q("LOAN_APPLICATION_AND_DOCUMENT_QUERY", "P15", "LOAN_REQUIREMENTS", cap="LOAN",
                  scope="GROUP", family="ACTIVE", group="LOAN",
                  contract={"query_type": "REQUIREMENTS", "loan_context": {"loan_type": None}})

    # --- P15 estado solicitud ---
    m = _P15_APP.match(norm)
    if m:
        return _q("LOAN_APPLICATION_AND_DOCUMENT_QUERY", "P15", "LOAN_APPLICATION_STATUS", cap="LOAN",
                  scope="ITEM", family="ACTIVE", group="LOAN",
                  contract={"query_type": "APPLICATION_STATUS", "application_context": {"application_id": m.group(1).upper()}})

    # --- P05 ---
    m = _P05.match(norm)
    if m:
        return _q("TRANSFER_POLICY_AND_TRACKING_QUERY", "P05", "TRANSFER_TRACKING", cap="ACCOUNTS",
                  scope="ITEM", family="NA", group="TRANSFER",
                  contract={"query_type": "TRACK_STATUS", "query_payload": {"transfer_reference": m.group(1).upper(), "transfer_rail": "ACH"}})

    # === MUTANTS ===

    # --- M01 ---
    m = _M01.match(norm)
    if m:
        return _mut("TRANSFER_OWN_VALIDATE", "M01", "TRANSFER_BETWEEN_OWN_ACCOUNTS",
                    cap="ACCOUNTS", group="TRANSFER", category="TRANSFER_OWN",
                    contract={"source_account_id": m.group(1).upper(), "destination_account_id": m.group(2).upper(),
                              "amount": m.group(3).replace(",", ""), "currency": m.group(4).upper()})

    # --- P14 abono capital ---
    m = _P14_ABONO.match(norm)
    if m:
        rule = (m.group(4) or "REDUCE_TERM").upper().replace("REDUCIR_PLAZO", "REDUCE_TERM").replace("REDUCIR_CUOTA", "REDUCE_INSTALLMENT")
        return _mut("LOAN_SERVICING_VALIDATE", "P14", "LOAN_PAYMENT_VALIDATE",
                    cap="LOAN", group="LOAN", category="LOAN_PAYMENT", subtype=None,
                    contract={"service_type": "EXTRAORDINARY_PRINCIPAL_PAYMENT", "loan_id": m.group(1).upper(),
                              "source_account_id": None,
                              "service_parameters": {"payment_amount": m.group(2).replace(",", ""), "currency": m.group(3).upper(),
                                                    "application_rule": rule}})

    # --- M10 pago cuota ---
    m = _M10.match(norm)
    if m:
        return _mut("LOAN_SERVICING_VALIDATE", "M10", "LOAN_PAYMENT_VALIDATE",
                    cap="LOAN", group="LOAN", category="LOAN_PAYMENT",
                    contract={"service_type": "INSTALLMENT_PAYMENT", "loan_id": m.group(1).upper(),
                              "source_account_id": m.group(4).upper(),
                              "service_parameters": {"payment_amount": m.group(2).replace(",", ""), "currency": m.group(3).upper()}})

    # --- P11 rediferir ---
    m = _P11_REDIFERIR.match(norm)
    if m:
        return _mut("CREDIT_CARD_SERVICING_VALIDATE", "P11", "CARD_SERVICING_VALIDATE",
                    cap="CREDIT_CARD", group="CREDIT_CARD", category="CARD_SERVICING",
                    contract={"service_type": "REDIFFER_BALANCE", "card_id": m.group(1).upper(),
                              "service_parameters": {"target_amount": m.group(2).replace(",", ""),
                                                    "requested_installments": int(m.group(3)), "currency": m.group(4).upper()}})

    # --- P11 avance ---
    m = _P11_AVANCE.match(norm)
    if m:
        return _mut("CREDIT_CARD_SERVICING_VALIDATE", "P11", "CARD_SERVICING_VALIDATE",
                    cap="CREDIT_CARD", group="CREDIT_CARD", category="CARD_SERVICING",
                    contract={"service_type": "CASH_ADVANCE", "card_id": m.group(1).upper(),
                              "service_parameters": {"target_amount": m.group(2).replace(",", ""), "currency": m.group(3).upper()}})

    return None


# ---------------------------------------------------------------------------
# Helpers for building parsed dicts
# ---------------------------------------------------------------------------

def _q(op_type: str, code: str, intent: str, *, cap: str, scope: str, family: str, group: str,
       contract: dict[str, Any], subtype: str | None = None) -> dict[str, Any]:
    """Build a query parsed result."""
    return {"operation_type": op_type, "contract_code": code, "intent_id": intent,
            "nature": "query", "capability": cap,
            "scope_level": scope, "product_family": family, "product_group": group, "product_subtype": subtype,
            "requires_confirmation": False, "next_action": "execute_operation",
            "contract": contract}


def _mut(op_type: str, code: str, intent: str, *, cap: str, group: str, category: str,
         contract: dict[str, Any], subtype: str | None = None) -> dict[str, Any]:
    """Build a mutant parsed result."""
    return {"operation_type": op_type, "contract_code": code, "intent_id": intent,
            "nature": "mutant", "capability": cap, "category": category,
            "scope_level": "ITEM", "product_family": "ACTIVE" if group in ("LOAN", "CREDIT_CARD") else "PASSIVE",
            "product_group": group, "product_subtype": subtype,
            "phase": "VALIDATE", "requires_confirmation": True, "next_action": "await_confirmation",
            "contract": contract}


def _acct_contract(account_id: str, currency_raw: str | None, *, include_overdraft: bool = False) -> dict[str, Any]:
    """Build canonical account query contract (P02/P03)."""
    ccy = currency_raw.upper() if currency_raw else None
    scope: dict[str, Any] = {
        "include_identity": True, "include_balances": True, "include_recent_movements": False,
        "include_fees": False, "include_status": True, "include_interest_conditions": False,
        "include_tax_flags": False, "include_frozen_funds": False, "include_limits": False,
        "include_alerts": False, "include_documents": False,
    }
    if include_overdraft:
        scope["include_overdraft_details"] = True
    return {
        "account_selector": {"account_id": account_id, "account_role": "PRIMARY", "currency": ccy},
        "query_scope": scope,
        "movement_filters": {"limit": 10, "include_flagged_only": False},
        "document_options": {"statement_month": None, "certificate_with_balance": False},
    }


# ---------------------------------------------------------------------------
# Full operation_request builder
# ---------------------------------------------------------------------------

def build_dispatch_request(
    *,
    customer_id: str,
    conversation_id: str | None,
    turn_number: int,
    command: str,
    phase: str | None = None,
    allow_execute: bool = False,
    use_canonical_catalog: bool = False,
    correlation_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build Genesis 1.2 canonical operation_request.

    Sandbox rule: CUST001-010 keep legacy-compatible fields unless use_canonical_catalog=True.
    """
    parsed = parse_command(command)
    if parsed is None:
        raise ValueError(f"Comando no reconocido: '{command}'")

    conv_id = conversation_id or str(uuid.uuid4())
    is_simulated = bool(_SIMULATED_PATTERN.match(customer_id))
    is_mutant = parsed["nature"] == "mutant"

    # Phase resolution
    if is_mutant:
        effective_phase = (phase or "VALIDATE").upper()
        if effective_phase not in VALID_PHASES:
            raise ValueError(f"Phase invalido: '{effective_phase}'. Validos: {VALID_PHASES}")
        if effective_phase == "EXECUTE" and not allow_execute:
            raise ValueError("Phase EXECUTE no permitido en GENESIS_ENV=prod. Solo en dev/test.")
        pcfg = _PHASE_CONFIG[effective_phase]
        eff_confirm = pcfg["requires_confirmation"]
        eff_next = pcfg["next_action"]
    else:
        effective_phase = "QUERY"
        eff_confirm = False
        eff_next = "execute_operation"

    # Contract note
    if is_mutant:
        if effective_phase == "EXECUTE":
            parsed["contract"]["note"] = "DEV/TEST ONLY - orquestador puede ejecutar en entorno controlado."
        elif effective_phase == "ANALYZE":
            parsed["contract"]["note"] = "ANALYZE - revision sin confirmacion fuerte."
        else:
            parsed["contract"]["note"] = "VALIDATE ONLY - Cognitiva no ejecuta Core."

    txn_id = str(uuid.uuid4())
    req_id = request_id or str(uuid.uuid4())
    corr_id = correlation_id or str(uuid.uuid4())

    # Canonical envelope (section 2 of MD)
    operation_request: dict[str, Any] = {
        "contract_version": "1.2",
        "transaction_id": txn_id,
        "request_id": req_id,
        "correlation_id": corr_id,
        "session_id": conv_id,
        "customer_id": customer_id,
        "turn_number": turn_number,
        "output_type": "operation_request",
        "capability": parsed.get("capability", "GENERAL"),
        "operation": parsed["operation_type"],
        "requires_confirmation": eff_confirm,
        "next_action": eff_next,
        "telemetry": {
            "client_request_timestamp": datetime.now(tz=UTC).isoformat(),
            "cognitive_processing_time_ms": 0,
            "total_elapsed_time_ms": 0,
            "dispatch_type": "lab_deterministic",
            "genesis_env_execute_allowed": allow_execute,
        },
        "contract": parsed["contract"],
        # Cognitive extensions
        "scope_level": parsed.get("scope_level"),
        "product_family": parsed.get("product_family"),
        "product_group": parsed.get("product_group"),
        "product_subtype": parsed.get("product_subtype"),
        "nature": parsed["nature"],
        "phase": effective_phase,
        "category": parsed.get("category"),
        "simulated": is_simulated,
    }

    # Response note
    if is_mutant:
        if effective_phase == "EXECUTE":
            note = "DEV/TEST EXECUTE. Orquestador puede ejecutar en entorno controlado. Sandbox simulated=true: no asentar prod."
        elif effective_phase == "ANALYZE":
            note = "ANALYZE: contrato emitido para revision. Sin confirmacion fuerte."
        else:
            note = "Mutante VALIDATE ONLY. Orquestador confirma y ejecuta. Sandbox no surte efecto real."
    else:
        note = "Cognitiva no ejecuta. Orquestador: si simulated=true, no ejecutar Core."

    return {
        "status": "CONTRACT_EMITTED",
        "simulated": is_simulated,
        "pair_id": parsed["contract_code"],
        "note": note,
        "operation_request": operation_request,
    }
