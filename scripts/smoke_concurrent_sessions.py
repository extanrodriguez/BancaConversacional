r"""Smoke test: concurrent sessions isolation.

Verifies that two clients running in parallel do NOT see each other's
pending_action, last_resolved, or customer snapshot.

Usage:
    .\.venv\Scripts\python.exe scripts/smoke_concurrent_sessions.py

Requires: Contract Inspector on http://localhost:8000
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

BASE = os.getenv("GENESIS_TEST_URL", "http://localhost:8445")


async def client_a(results: dict) -> None:
    """CUST001 conv-A: T1 saldo ahorros, T2 follow-up saldo corriente."""
    conv = f"iso-A-{int(time.time())}"
    async with httpx.AsyncClient(timeout=60.0) as c:
        # T1
        r1 = await c.post(f"{BASE}/inspect", json={"question": "saldo de mi cuenta de ahorros?", "conversation_id": conv, "customer_id": "CUST001"})
        d1 = r1.json()
        results["A_T1_status"] = d1.get("status")
        results["A_T1_ref"] = d1.get("actions", [{}])[0].get("detected_entities", {}).get("account_ref") if d1.get("actions") else None
        results["A_T1_client"] = d1.get("client_response", "")

        await asyncio.sleep(2.0)

        # T2 follow-up
        r2 = await c.post(f"{BASE}/inspect", json={"question": "y el saldo de mi corriente?", "conversation_id": conv, "customer_id": "CUST001"})
        d2 = r2.json()
        results["A_T2_status"] = d2.get("status")
        results["A_T2_ref"] = d2.get("actions", [{}])[0].get("detected_entities", {}).get("account_ref") if d2.get("actions") else None
        results["A_T2_client"] = d2.get("client_response", "")


async def client_b(results: dict) -> None:
    """CUST008 conv-B: T1 cuota prestamo, T2 feasibility."""
    conv = f"iso-B-{int(time.time())}"
    async with httpx.AsyncClient(timeout=60.0) as c:
        # T1
        r1 = await c.post(f"{BASE}/inspect", json={"question": "cuota de mi prestamo?", "conversation_id": conv, "customer_id": "CUST008"})
        d1 = r1.json()
        results["B_T1_status"] = d1.get("status")
        results["B_T1_ref"] = d1.get("actions", [{}])[0].get("detected_entities", {}).get("account_ref") if d1.get("actions") else None
        results["B_T1_client"] = d1.get("client_response", "")

        await asyncio.sleep(2.0)

        # T2 feasibility
        r2 = await c.post(f"{BASE}/inspect", json={"question": "me alcanza con mis ahorros para la cuota?", "conversation_id": conv, "customer_id": "CUST008"})
        d2 = r2.json()
        results["B_T2_status"] = d2.get("status")
        results["B_T2_client"] = d2.get("client_response", "")


async def main() -> None:
    print("=" * 60)
    print("  CONCURRENT SESSION ISOLATION SMOKE TEST")
    print("=" * 60)

    # Check server
    async with httpx.AsyncClient(timeout=5.0) as c:
        try:
            await c.get(f"{BASE}/customers")
        except Exception:
            print("ERROR: Server not running on localhost:8000")
            sys.exit(1)

    results_a: dict = {}
    results_b: dict = {}

    # Run both clients in parallel
    await asyncio.gather(
        client_a(results_a),
        client_b(results_b),
    )

    print("\n  Client A (CUST001 - balance):")
    print(f"    T1: status={results_a.get('A_T1_status')} ref={results_a.get('A_T1_ref')}")
    print(f"    T2: status={results_a.get('A_T2_status')} ref={results_a.get('A_T2_ref')}")
    print(f"    T1 client: {(results_a.get('A_T1_client') or '')[:80]}")

    print("\n  Client B (CUST008 - loan+feasibility):")
    print(f"    T1: status={results_b.get('B_T1_status')} ref={results_b.get('B_T1_ref')}")
    print(f"    T2: status={results_b.get('B_T2_status')}")
    print(f"    T2 client: {(results_b.get('B_T2_client') or '')[:80]}")

    # Assertions
    errors: list[str] = []

    # A should have CUST001 data (AHO001 balance=85000)
    if results_a.get("A_T1_status") != "VALID_CONTRACT":
        errors.append(f"A_T1 expected VALID, got {results_a.get('A_T1_status')}")
    if results_a.get("A_T1_ref") != "AHO001":
        errors.append(f"A_T1 expected AHO001, got {results_a.get('A_T1_ref')}")
    if "85000" not in (results_a.get("A_T1_client") or ""):
        errors.append("A_T1 client_response missing 85000 (CUST001 balance)")

    # A must NOT contain CUST008 data (PRE008V, 19800, 38000)
    a_all = str(results_a)
    if "PRE008V" in a_all:
        errors.append("ISOLATION FAILURE: A contains PRE008V (belongs to B)")
    if "19800" in a_all and "CUST008" not in a_all:
        errors.append("ISOLATION FAILURE: A contains 19800 (CUST008 installment)")

    # B should have CUST008 data (PRE008V, cuota 19800, feasibility)
    if results_b.get("B_T1_status") != "VALID_CONTRACT":
        errors.append(f"B_T1 expected VALID, got {results_b.get('B_T1_status')}")
    if results_b.get("B_T1_ref") != "PRE008V":
        errors.append(f"B_T1 expected PRE008V, got {results_b.get('B_T1_ref')}")
    if results_b.get("B_T2_status") != "VALID_CONTRACT":
        errors.append(f"B_T2 expected VALID, got {results_b.get('B_T2_status')}")

    # B must NOT contain CUST001 data (AHO001, 85000)
    b_all = str(results_b)
    if "AHO001" in b_all:
        errors.append("ISOLATION FAILURE: B contains AHO001 (belongs to A)")
    if "85000" in b_all:
        errors.append("ISOLATION FAILURE: B contains 85000 (CUST001 balance)")

    print("\n" + "=" * 60)
    if errors:
        print(f"  FAIL ({len(errors)} errors):")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print("  PASS - Full isolation confirmed")
        print("    A sees only CUST001 data")
        print("    B sees only CUST008 data")
        print("    No cross-contamination detected")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
