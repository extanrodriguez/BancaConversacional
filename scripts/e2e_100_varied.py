r"""E2E 100-case varied suite — reads catalog, runs against live server.

Usage:
    .\.venv\Scripts\python.exe scripts/e2e_100_varied.py
    .\.venv\Scripts\python.exe scripts/e2e_100_varied.py --only balance,loan
    .\.venv\Scripts\python.exe scripts/e2e_100_varied.py --threshold 90

Requirements:
    - Contract Inspector running on http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import statistics
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

BASE = os.getenv("GENESIS_TEST_URL", "http://localhost:8445")
DELAY = 2.0  # seconds between LLM-hitting requests
CATALOG_PATH = Path(__file__).parent.parent / "tests" / "e2e" / "catalog_100.json"


def load_catalog(only_groups: set[str] | None = None) -> list[dict[str, Any]]:
    with open(CATALOG_PATH) as f:
        data = json.load(f)
    cases = data["cases"]
    if only_groups:
        cases = [c for c in cases if c["group"] in only_groups]
    return cases


def inspect(question: str, conv_id: str, customer_id: str) -> dict[str, Any]:
    """POST /inspect with retry on 429 and empty responses."""
    for attempt in range(3):
        try:
            r = httpx.post(
                f"{BASE}/inspect",
                json={"question": question, "conversation_id": conv_id, "customer_id": customer_id},
                timeout=90.0,
            )
            if r.status_code == 429:
                wait = 5.0 * (attempt + 1)
                print(f"    [429 rate limit, waiting {wait}s...]")
                time.sleep(wait)
                continue
            if r.status_code >= 500 and not r.text.strip():
                print(f"    [empty {r.status_code}, retrying...]")
                time.sleep(5.0)
                continue
            return r.json()
        except (httpx.ReadTimeout, httpx.ConnectError) as e:
            print(f"    [connection error: {type(e).__name__}, retrying...]")
            time.sleep(5.0)
            continue
        except Exception:
            time.sleep(3.0)
            continue
    return {"status": "PROVIDER_ERROR", "error_detail": "timeout after retries"}


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run a single test case and return result dict."""
    case_id = case["id"]
    customer_id = case["customer_id"]
    turns = case["turns"]
    expect = case["expect"]
    conv_id = f"e100-{case_id}-{int(time.time())}"

    t0 = time.perf_counter()
    last_response: dict[str, Any] = {}

    for i, turn in enumerate(turns):
        if i > 0:
            time.sleep(DELAY)
        last_response = inspect(turn["question"], conv_id, customer_id)

    total_ms = round((time.perf_counter() - t0) * 1000)

    # Extract result
    status = last_response.get("status", "UNKNOWN")
    actions = last_response.get("actions", [])
    a0 = actions[0] if actions else {}
    intent = a0.get("intent_id")
    ref = a0.get("detected_entities", {}).get("account_ref") if a0 else None
    client_response = last_response.get("client_response", "") or ""
    total_req_ms = last_response.get("total_request_ms", 0)
    decision_trace = last_response.get("decision_trace", [])

    # Evaluate
    passed = True
    reasons: list[str] = []

    # Status check
    exp_status = expect.get("status")
    status_any = expect.get("status_any")
    if status_any:
        if status not in status_any:
            passed = False
            reasons.append(f"status={status} (exp one of {status_any})")
    elif exp_status and status != exp_status:
        passed = False
        reasons.append(f"status={status} (exp {exp_status})")

    # Intent check
    exp_intent = expect.get("intent")
    if exp_intent and intent != exp_intent:
        passed = False
        reasons.append(f"intent={intent} (exp {exp_intent})")

    # Ref check
    exp_ref = expect.get("account_ref")
    if exp_ref and ref != exp_ref:
        passed = False
        reasons.append(f"ref={ref} (exp {exp_ref})")

    # client_response_contains
    for substr in expect.get("client_response_contains", []):
        # Flexible number matching: "38000" should match "38000.0" or "38,000"
        found = substr.lower() in client_response.lower()
        if not found and substr.replace(",", "").isdigit():
            # Try with .0 suffix and comma variants
            num = substr.replace(",", "")
            found = (
                num in client_response
                or f"{num}.0" in client_response
                or f"{num}.00" in client_response
                or f"{int(num):,}" in client_response
            )
        if not found:
            passed = False
            reasons.append(f"missing '{substr}' in client_response")

    # client_response_forbids
    for substr in expect.get("client_response_forbids", []):
        if substr.lower() in client_response.lower():
            passed = False
            reasons.append(f"forbidden '{substr}' found in client_response")

    # Extract timing from trace
    step_durations: dict[str, int] = {}
    for step in decision_trace:
        name = step.get("step", "?")
        dur = step.get("duration_ms")
        if dur is not None:
            step_durations[name] = dur

    return {
        "id": case_id,
        "group": case["group"],
        "passed": passed,
        "reason": "; ".join(reasons) if reasons else "OK",
        "total_ms": total_ms,
        "server_ms": total_req_ms,
        "step_durations": step_durations,
        "turns": len(turns),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated group filter", default="")
    parser.add_argument("--threshold", type=int, default=90, help="Min pass count for exit 0")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between requests")
    args = parser.parse_args()

    global DELAY
    DELAY = args.delay

    only_groups = set(args.only.split(",")) if args.only else None
    cases = load_catalog(only_groups)

    print("=" * 70)
    print(f"  GENESIS E2E 100 VARIED - {len(cases)} cases")
    print("=" * 70)

    # Check server
    try:
        httpx.get(f"{BASE}/customers", timeout=5)
    except Exception:
        print("ERROR: Contract Inspector not running on localhost:8000")
        sys.exit(1)

    results: list[dict[str, Any]] = []
    current_group = ""

    for case in cases:
        if case["group"] != current_group:
            current_group = case["group"]
            print(f"\n  [{current_group.upper()}]")

        time.sleep(DELAY)
        result = evaluate_case(case)
        results.append(result)

        icon = "PASS" if result["passed"] else "FAIL"
        timing = f"{result['server_ms']}ms" if result["server_ms"] else f"~{result['total_ms']}ms"
        print(f"    {icon} {result['id']:12s} | {timing:8s} | {result['reason'][:60]}")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    pass_rate = round(100 * passed / total, 1) if total else 0

    all_ms = [r["server_ms"] for r in results if r["server_ms"] > 0]
    p50 = round(statistics.median(all_ms)) if all_ms else 0
    p95 = round(sorted(all_ms)[int(len(all_ms) * 0.95)] if all_ms else 0)
    avg_ms = round(statistics.mean(all_ms)) if all_ms else 0

    print(f"\n{'=' * 70}")
    print(f"  TOTAL: {total} | PASS: {passed} | FAIL: {failed} | RATE: {pass_rate}%")
    print(f"  Latency (server_ms): p50={p50}ms  p95={p95}ms  avg={avg_ms}ms")
    print(f"{'=' * 70}")

    if failed:
        print("\n  FAILURES:")
        for r in results:
            if not r["passed"]:
                print(f"    FAIL {r['id']:12s} [{r['group']}] -- {r['reason']}")

    # Top 10 slowest
    sorted_by_ms = sorted(results, key=lambda r: r["server_ms"], reverse=True)[:10]
    print("\n  TOP 10 SLOWEST:")
    for r in sorted_by_ms:
        steps = ", ".join(f"{k}={v}ms" for k, v in r["step_durations"].items())
        print(f"    {r['id']:12s} {r['server_ms']:5d}ms | {steps[:60]}")

    # Group summary
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        groups.setdefault(r["group"], []).append(r)
    print("\n  BY GROUP:")
    for g, rs in groups.items():
        gp = sum(1 for r in rs if r["passed"])
        print(f"    {g:12s}: {gp}/{len(rs)}")

    threshold = args.threshold
    exit_code = 0 if passed >= threshold else 1
    if exit_code:
        print(f"\n  BELOW THRESHOLD: {passed} < {threshold}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
