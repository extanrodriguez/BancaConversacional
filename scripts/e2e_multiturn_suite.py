r"""Multiturno E2E acceptance suite — loans, accounts, follow-up, mismatch.

Validates conversation continuity across turns against live Azure OpenAI.

Usage:
    .\.venv\Scripts\python.exe scripts/e2e_multiturn_suite.py

Requirements:
    - Contract Inspector running on http://localhost:8000
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

BASE = os.getenv("GENESIS_TEST_URL", "http://localhost:8445")
DELAY = 2.0  # seconds between LLM requests (rate limit safety)


@dataclass
class TurnResult:
    turn_label: str
    status: str
    account_ref: str | None
    client_response: str | None
    decision_trace: list[dict[str, Any]]
    raw: dict[str, Any]


def inspect(question: str, conv_id: str, customer_id: str) -> dict[str, Any]:
    """POST /inspect and return parsed JSON."""
    r = httpx.post(
        f"{BASE}/inspect",
        json={"question": question, "conversation_id": conv_id, "customer_id": customer_id},
        timeout=60.0,
    )
    return r.json()


def extract(data: dict[str, Any], label: str) -> TurnResult:
    actions = data.get("actions", [])
    ref = actions[0].get("detected_entities", {}).get("account_ref") if actions else None
    return TurnResult(
        turn_label=label,
        status=data.get("status", "UNKNOWN"),
        account_ref=ref,
        client_response=data.get("client_response"),
        decision_trace=data.get("decision_trace", []),
        raw=data,
    )


# ---------------------------------------------------------------------------
# Suite definitions
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    id: str
    customer: str
    turns: list[tuple[str, str, str | None, str | None]]
    # Each turn: (question, expected_status, expected_ref_or_None, expected_in_client_response_or_None)


SUITE_L = [
    TestCase(
        id="L1-L2-L3a",
        customer="CUST001",
        turns=[
            ("fecha de pago de mi prestamo?", "CLARIFICATION_REQUIRED", None, "préstamo"),
            ("el de libre inversion", "VALID_CONTRACT", "PRE001", None),
            ("y el valor total de la deuda?", "VALID_CONTRACT", "PRE001", "278000"),
        ],
    ),
    TestCase(
        id="L1-L2-L3b",
        customer="CUST001",
        turns=[
            ("cuota de mi prestamo?", "CLARIFICATION_REQUIRED", None, None),
            ("Prestamo Libre Inversion", "VALID_CONTRACT", "PRE001", None),
            ("y la tasa?", "VALID_CONTRACT", "PRE001", "17.5"),
        ],
    ),
    TestCase(
        id="L1-L2-L3c",
        customer="CUST001",
        turns=[
            ("informacion de mi prestamo", "CLARIFICATION_REQUIRED", None, None),
            ("el de libre inversion", "VALID_CONTRACT", "PRE001", None),
            ("esta en mora?", "VALID_CONTRACT", "PRE001", None),  # delinquency_days=0
        ],
    ),
    TestCase(
        id="L1-L2-L3d",
        customer="CUST001",
        turns=[
            ("datos de mi credito", "CLARIFICATION_REQUIRED", None, None),
            ("credito vehiculo", "VALID_CONTRACT", "PRE001V", None),
            ("proxima fecha de pago?", "VALID_CONTRACT", "PRE001V", None),
        ],
    ),
]

SUITE_M = [
    TestCase(
        id="M1-direct",
        customer="CUST008",
        turns=[
            ("fecha de pago de mi prestamo?", "VALID_CONTRACT", "PRE008V", None),
        ],
    ),
    TestCase(
        id="M1-M2-deuda",
        customer="CUST008",
        turns=[
            ("cuota de mi prestamo?", "VALID_CONTRACT", "PRE008V", None),
            ("y la deuda total?", "VALID_CONTRACT", "PRE008V", "690000"),
        ],
    ),
    TestCase(
        id="M1-M2-tasa",
        customer="CUST008",
        turns=[
            ("tasa de mi prestamo?", "VALID_CONTRACT", "PRE008V", None),
            ("y la tasa?", "VALID_CONTRACT", "PRE008V", "16.2"),
        ],
    ),
]

SUITE_C = [
    TestCase(
        id="C1-C2-nomina",
        customer="CUST001",
        turns=[
            ("saldo de mi cuenta?", "CLARIFICATION_REQUIRED", None, None),
            ("de mi cuenta de nomina", "VALID_CONTRACT", "NOM001", None),
        ],
    ),
    TestCase(
        id="C1-C2-corriente",
        customer="CUST001",
        turns=[
            ("saldo de mi cuenta?", "CLARIFICATION_REQUIRED", None, None),
            ("la cuenta corriente principal", "VALID_CONTRACT", "COR001", None),
        ],
    ),
    TestCase(
        id="C1-C2-id",
        customer="CUST001",
        turns=[
            ("saldo de mi cuenta?", "CLARIFICATION_REQUIRED", None, None),
            ("COR001", "VALID_CONTRACT", "COR001", None),
        ],
    ),
]

SUITE_X = [
    TestCase(
        id="X1-topic-change-loan-to-savings",
        customer="CUST008",
        turns=[
            # CUST008 has 1 loan → direct VALID
            ("cuota de mi prestamo?", "VALID_CONTRACT", "PRE008V", None),
            # Topic change: asks about savings → should NOT reuse PRE008V
            # Should go through full pipeline and resolve AHO008
            ("saldo de mis ahorros personales?", "VALID_CONTRACT", "AHO008", None),
        ],
    ),
]


def run_case(tc: TestCase) -> list[tuple[str, str, bool, str]]:
    """Run a test case and return results per turn."""
    conv_id = f"suite-{tc.id}-{int(time.time())}"
    results = []

    for i, (question, exp_status, exp_ref, exp_in_client) in enumerate(tc.turns):
        time.sleep(DELAY)
        data = inspect(question, conv_id, tc.customer)
        tr = extract(data, f"{tc.id}/T{i+1}")

        # Check status
        status_ok = tr.status == exp_status
        ref_ok = True if exp_ref is None else (tr.account_ref == exp_ref)
        client_ok = True
        if exp_in_client and tr.client_response:
            client_ok = exp_in_client.lower() in tr.client_response.lower()
        elif exp_in_client and not tr.client_response:
            client_ok = False

        passed = status_ok and ref_ok and client_ok
        reason_parts = []
        if not status_ok:
            reason_parts.append(f"status={tr.status} (expected {exp_status})")
        if not ref_ok:
            reason_parts.append(f"ref={tr.account_ref} (expected {exp_ref})")
        if not client_ok:
            reason_parts.append(f"client_response missing '{exp_in_client}'")

        reason = "; ".join(reason_parts) if reason_parts else "OK"
        results.append((f"{tc.id}/T{i+1}", question[:50], passed, reason))

        # If a turn fails hard (wrong status), we may not be able to continue
        if not status_ok and exp_status == "VALID_CONTRACT" and tr.status == "CLARIFICATION_REQUIRED":
            # Continuation turns won't make sense
            for j in range(i + 1, len(tc.turns)):
                results.append((f"{tc.id}/T{j+1}", tc.turns[j][0][:50], False, "SKIPPED (prior turn failed)"))
            break

    return results


def main() -> None:
    print("=" * 80)
    print("GENESIS MULTITURN E2E SUITE")
    print("=" * 80)

    # Check server is up
    try:
        httpx.get(f"{BASE}/customers", timeout=5)
    except Exception:
        print("ERROR: Contract Inspector not running on localhost:8000")
        sys.exit(1)

    all_results: list[tuple[str, str, bool, str]] = []

    suites = [
        ("Suite L (CUST001 2 loans)", SUITE_L),
        ("Suite M (CUST008 1 loan)", SUITE_M),
        ("Suite C (CUST001 accounts)", SUITE_C),
        ("Suite X (mismatch/topic change)", SUITE_X),
    ]

    for suite_name, cases in suites:
        print(f"\n{'─' * 60}")
        print(f"  {suite_name}")
        print(f"{'─' * 60}")
        for tc in cases:
            results = run_case(tc)
            all_results.extend(results)
            for label, q, passed, reason in results:
                icon = "✓" if passed else "✗"
                print(f"  {icon} {label:30s} | {q:50s} | {reason}")

    # Summary
    total = len(all_results)
    passed = sum(1 for _, _, p, _ in all_results if p)
    failed = total - passed
    print(f"\n{'=' * 80}")
    print(f"TOTAL: {total} | PASS: {passed} | FAIL: {failed}")
    print(f"{'=' * 80}")

    if failed > 0:
        print("\nFAILED CASES:")
        for label, q, p, reason in all_results:
            if not p:
                print(f"  ✗ {label}: {reason}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
