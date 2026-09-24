r"""Local Orchestrator — minimal client that calls POST /turn on Genesis Cognitive.

Routes:
  app_channel  → "hacia App" (prints to stdout)
  core_channel → "hacia Core (no implementado)" (prints to stdout, no simulation)

Usage:
    # Interactive mode (prompts for questions):
    .\.venv\Scripts\python.exe scripts/local_orchestrator.py

    # Single question:
    .\.venv\Scripts\python.exe scripts/local_orchestrator.py --question "hola"

    # Run validation cases A–D:
    .\.venv\Scripts\python.exe scripts/local_orchestrator.py --validate

    # Custom cognitive endpoint:
    .\.venv\Scripts\python.exe scripts/local_orchestrator.py --endpoint http://localhost:8445

Prerequisites:
    Genesis Cognitive must be running on GENESIS_PORT (default 8445).
    Start it with: .\.venv\Scripts\python.exe scripts/run_contract_inspector.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

# Ensure UTF-8 output on Windows (avoid UnicodeEncodeError with cp1252)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx

# Defaults
DEFAULT_ENDPOINT = "http://127.0.0.1:8445"
DEFAULT_CUSTOMER_ID = "CUST001"

# ANSI colors for terminal output
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_RED = "\033[91m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def call_turn(
    endpoint: str,
    question: str,
    conversation_id: str,
    customer_id: str = DEFAULT_CUSTOMER_ID,
    force_core_query: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Call POST /turn on the cognitive layer and return the parsed response."""
    url = f"{endpoint}/turn"
    payload = {
        "question": question,
        "conversation_id": conversation_id,
        "customer_id": customer_id,
        "force_core_query": force_core_query,
    }
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def route_response(data: dict[str, Any], *, verbose: bool = True) -> None:
    """Route app_channel and core_channel to their destinations."""
    app_ch = data.get("app_channel")
    core_ch = data.get("core_channel")
    audit = data.get("audit")

    # Route app_channel → hacia App
    if app_ch:
        print(f"\n{_GREEN}{_BOLD}→ App (app_channel):{_RESET}")
        status = app_ch.get("status", "?")
        client_response = app_ch.get("client_response")
        intent_id = app_ch.get("intent_id")
        print(f"  status: {status}")
        if intent_id:
            print(f"  intent: {intent_id}")
        if client_response:
            print(f"  respuesta: {_CYAN}{client_response}{_RESET}")
        clarifications = app_ch.get("clarifications", [])
        if clarifications:
            print(f"  clarificaciones: {clarifications}")

    # Route core_channel → hacia Core (no implementado)
    if core_ch:
        print(f"\n{_YELLOW}{_BOLD}→ Core (no implementado) — core_channel:{_RESET}")
        print(f"  contrato: {json.dumps(core_ch, indent=2, ensure_ascii=False)[:500]}")
    else:
        if verbose:
            print(f"\n{_YELLOW}→ Core: null (no se requiere consulta Core){_RESET}")

    # Audit
    if audit and verbose:
        print(f"\n  {_BOLD}audit:{_RESET} total_ms={audit.get('total_ms', '?')}, "
              f"slowest={audit.get('slowest_step', '?')} ({audit.get('slowest_step_ms', '?')}ms), "
              f"steps={audit.get('step_count', '?')}")


# --------------- Validation Cases A–D ---------------

VALIDATION_CASES: list[dict[str, Any]] = [
    {
        "label": "A",
        "description": "hola, force=false → NON_OPERATIONAL + saludo; core null",
        "question": "hola",
        "force_core_query": False,
        "expect_status": "NON_OPERATIONAL",
        "expect_core_null": True,
    },
    {
        "label": "B",
        "description": "saldo ahorros, force=false → VALID AHO001; core null",
        "question": "cuál es el saldo de mi cuenta de ahorros",
        "force_core_query": False,
        "expect_status": "VALID_CONTRACT",
        "expect_core_null": True,
    },
    {
        "label": "C",
        "description": "saldo, force=true → VALID AHO001; core ACCOUNT_QUERY / P02",
        "question": "cuál es el saldo de mi cuenta de ahorros",
        "force_core_query": True,
        "expect_status": "VALID_CONTRACT",
        "expect_core_null": False,
    },
    {
        "label": "D",
        "description": "requisitos vivienda → VALID + RAG; core null",
        "question": "cuáles son los requisitos para un préstamo de vivienda",
        "force_core_query": False,
        "expect_status": "VALID_CONTRACT",
        "expect_core_null": True,
    },
]


def run_validation(endpoint: str) -> bool:
    """Run cases A–D through the orchestrator and report pass/fail."""
    print(f"\n{'='*60}")
    print(f"{_BOLD}Orquestador Local — Validación A–D{_RESET}")
    print(f"Endpoint cognitivo: {endpoint}")
    print(f"{'='*60}")

    all_pass = True
    conv_id = f"orch-validate-{uuid.uuid4().hex[:8]}"

    for case in VALIDATION_CASES:
        label = case["label"]
        print(f"\n{'─'*50}")
        print(f"{_BOLD}Caso {label}:{_RESET} {case['description']}")
        print(f"  question: \"{case['question']}\"")
        print(f"  force_core_query: {case['force_core_query']}")

        try:
            data = call_turn(
                endpoint=endpoint,
                question=case["question"],
                conversation_id=f"{conv_id}-{label}",
                force_core_query=case["force_core_query"],
            )
        except httpx.HTTPStatusError as e:
            print(f"  {_RED}FAIL — HTTP {e.response.status_code}{_RESET}")
            all_pass = False
            continue
        except httpx.ReadTimeout:
            print(f"  {_RED}FAIL — Timeout (>120s) esperando respuesta{_RESET}")
            all_pass = False
            continue
        except httpx.ConnectError:
            print(f"  {_RED}FAIL — No se pudo conectar a {endpoint}{_RESET}")
            print(f"  ¿Está corriendo el servicio cognitivo?")
            return False

        # Route and display
        route_response(data, verbose=False)

        # Verify expectations
        app_ch = data.get("app_channel", {})
        core_ch = data.get("core_channel")
        actual_status = app_ch.get("status", "")

        passed = True

        # Check status
        if case["expect_status"] == "NON_OPERATIONAL":
            # Accept both NON_OPERATIONAL and UNSUPPORTED for greetings
            if actual_status not in ("NON_OPERATIONAL", "UNSUPPORTED"):
                print(f"  {_RED}FAIL status esperado NON_OPERATIONAL|UNSUPPORTED, obtenido: {actual_status}{_RESET}")
                passed = False
        elif actual_status != case["expect_status"]:
            print(f"  {_RED}FAIL status esperado {case['expect_status']}, obtenido: {actual_status}{_RESET}")
            passed = False

        # Check core_channel
        if case["expect_core_null"] and core_ch is not None:
            print(f"  {_RED}FAIL core_channel esperado null, obtenido algo{_RESET}")
            passed = False
        elif not case["expect_core_null"] and core_ch is None:
            print(f"  {_RED}FAIL core_channel esperado contrato, obtenido null{_RESET}")
            passed = False

        if passed:
            print(f"  {_GREEN}OK PASS{_RESET}")
        else:
            all_pass = False
            print(f"  {_RED}FAIL FAIL{_RESET}")

    print(f"\n{'='*60}")
    if all_pass:
        print(f"{_GREEN}{_BOLD}Validación A–D: TODOS PASS{_RESET}")
    else:
        print(f"{_RED}{_BOLD}Validación A–D: ALGUNO FALLÓ{_RESET}")
    print(f"{'='*60}\n")

    return all_pass


def interactive_mode(endpoint: str) -> None:
    """Interactive REPL: prompt for questions, call /turn, route responses."""
    print(f"\n{_BOLD}Orquestador Local — Modo Interactivo{_RESET}")
    print(f"Endpoint cognitivo: {endpoint}")
    print(f"Customer: {DEFAULT_CUSTOMER_ID}")
    print(f"Escribe 'q' para salir, 'force' para alternar force_core_query.\n")

    conv_id = f"orch-{uuid.uuid4().hex[:8]}"
    force_core = False
    turn = 0

    while True:
        try:
            prompt_label = f"[T{turn+1}|force={'on' if force_core else 'off'}] > "
            question = input(prompt_label).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSaliendo.")
            break

        if not question:
            continue
        if question.lower() == "q":
            print("Saliendo.")
            break
        if question.lower() == "force":
            force_core = not force_core
            print(f"  force_core_query = {force_core}")
            continue

        turn += 1
        try:
            data = call_turn(
                endpoint=endpoint,
                question=question,
                conversation_id=conv_id,
                force_core_query=force_core,
            )
            route_response(data)
        except httpx.ConnectError:
            print(f"  {_RED}Error: No se pudo conectar a {endpoint}{_RESET}")
            print(f"  ¿Está corriendo el servicio cognitivo?")
        except httpx.HTTPStatusError as e:
            print(f"  {_RED}Error HTTP {e.response.status_code}: {e.response.text[:200]}{_RESET}")


def check_health(endpoint: str) -> None:
    """Check cognitive service health."""
    url = f"{endpoint}/health"
    try:
        resp = httpx.get(url, timeout=10)
        data = resp.json()
        status = data.get("status", "?")
        if resp.status_code == 200 and status == "ok":
            print(f"{_GREEN}OK HEALTH OK{_RESET} — {json.dumps(data, ensure_ascii=False)}")
        else:
            print(f"{_RED}FAIL HEALTH FAIL{_RESET} — HTTP {resp.status_code}: {data}")
            sys.exit(1)
    except httpx.ConnectError:
        print(f"{_RED}FAIL HEALTH FAIL — No se pudo conectar a {endpoint}{_RESET}")
        sys.exit(1)


# --------------- Context Load/Refresh ---------------


def call_context(
    endpoint: str,
    customer_id: str,
    conversation_id: str,
    context_op: str,
    context_data: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST /turn with context_info=true (load or refresh)."""
    url = f"{endpoint}/turn"
    payload = {
        "customer_id": customer_id,
        "conversation_id": conversation_id,
        "question": None,
        "force_core_query": False,
        "context_info": True,
        "context_op": context_op,
        "context": {"data": context_data},
    }
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def load_context_cmd(endpoint: str, customer_id: str, conversation_id: str, file_path: str) -> None:
    """Load context from a JSON file into the cognitive layer."""
    from pathlib import Path

    p = Path(file_path)
    if not p.exists():
        print(f"{_RED}FAIL File not found: {file_path}{_RESET}")
        sys.exit(1)

    context_data = json.loads(p.read_text(encoding="utf-8"))
    print(f"{_BOLD}load-context{_RESET}")
    print(f"  endpoint:        {endpoint}")
    print(f"  customer_id:     {customer_id}")
    print(f"  conversation_id: {conversation_id}")
    print(f"  file:            {file_path}")

    try:
        data = call_context(endpoint, customer_id, conversation_id, "load", context_data)
        print(f"\n  {_GREEN}OK {data.get('status')}{_RESET}")
        print(f"  products_count: {data.get('products_count')}")
        print(f"  active_count:   {data.get('active_count')}")
        print(f"  context_stamp:  {data.get('context_stamp')}")
    except httpx.ConnectError:
        print(f"  {_RED}FAIL No se pudo conectar a {endpoint}{_RESET}")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"  {_RED}FAIL HTTP {e.response.status_code}: {e.response.text[:200]}{_RESET}")
        sys.exit(1)


def refresh_context_cmd(endpoint: str, customer_id: str, conversation_id: str, file_path: str) -> None:
    """Refresh context from a JSON file."""
    from pathlib import Path

    p = Path(file_path)
    if not p.exists():
        print(f"{_RED}FAIL File not found: {file_path}{_RESET}")
        sys.exit(1)

    context_data = json.loads(p.read_text(encoding="utf-8"))
    print(f"{_BOLD}refresh-context{_RESET}")
    print(f"  endpoint:        {endpoint}")
    print(f"  customer_id:     {customer_id}")
    print(f"  conversation_id: {conversation_id}")
    print(f"  file:            {file_path}")

    try:
        data = call_context(endpoint, customer_id, conversation_id, "refresh", context_data)
        print(f"\n  {_GREEN}OK {data.get('status')}{_RESET}")
        print(f"  products_count: {data.get('products_count')}")
        print(f"  active_count:   {data.get('active_count')}")
        print(f"  context_stamp:  {data.get('context_stamp')}")
    except httpx.ConnectError:
        print(f"  {_RED}FAIL No se pudo conectar a {endpoint}{_RESET}")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"  {_RED}FAIL HTTP {e.response.status_code}: {e.response.text[:200]}{_RESET}")
        sys.exit(1)


def demo_session(endpoint: str, customer_id: str, file_path: str) -> None:
    """Run a full demo: load → hola → productos → refresh → saldo."""
    from pathlib import Path

    p = Path(file_path)
    if not p.exists():
        print(f"{_RED}FAIL File not found: {file_path}{_RESET}")
        sys.exit(1)

    context_data = json.loads(p.read_text(encoding="utf-8"))
    conv_id = f"demo-{uuid.uuid4().hex[:8]}"

    print(f"\n{'='*60}")
    print(f"{_BOLD}Orquestador — Demo Session{_RESET}")
    print(f"  endpoint: {endpoint}")
    print(f"  customer: {customer_id}")
    print(f"  conv_id:  {conv_id}")
    print(f"  file:     {file_path}")
    print(f"{'='*60}")

    # Step 1: Load context
    print(f"\n{'─'*50}")
    print(f"{_BOLD}1. load-context{_RESET}")
    data = call_context(endpoint, customer_id, conv_id, "load", context_data)
    print(f"  {_GREEN}OK {data.get('status')}{_RESET} | products={data.get('products_count')} active={data.get('active_count')}")

    # Step 2: hola
    print(f"\n{'─'*50}")
    print(f"{_BOLD}2. turn: 'hola'{_RESET}")
    r2 = call_turn(endpoint, "hola", conv_id, customer_id)
    route_response(r2, verbose=False)

    # Step 3: productos
    print(f"\n{'─'*50}")
    print(f"{_BOLD}3. turn: 'que productos tengo'{_RESET}")
    r3 = call_turn(endpoint, "que productos tengo", conv_id, customer_id)
    route_response(r3, verbose=False)

    # Step 4: refresh with modified balance
    print(f"\n{'─'*50}")
    print(f"{_BOLD}4. refresh-context (balance changed){_RESET}")
    # Modify first product balance for demo
    refreshed_data = json.loads(json.dumps(context_data))
    if refreshed_data.get("products"):
        refreshed_data["products"][0]["availableBalance"] = 99999.99
        refreshed_data["primerNombre"] = context_data.get("primerNombre", "Cliente") + " (refreshed)"
    data4 = call_context(endpoint, customer_id, conv_id, "refresh", refreshed_data)
    print(f"  {_GREEN}OK {data4.get('status')}{_RESET} | products={data4.get('products_count')}")

    # Step 5: saldo after refresh
    print(f"\n{'─'*50}")
    print(f"{_BOLD}5. turn: 'saldo de mi cuenta'{_RESET}")
    r5 = call_turn(endpoint, "saldo de mi cuenta", conv_id, customer_id)
    route_response(r5, verbose=False)

    print(f"\n{'='*60}")
    print(f"{_GREEN}{_BOLD}Demo completo{_RESET}")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local Orchestrator — calls POST /turn on Genesis Cognitive"
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Cognitive layer base URL (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--question", "-q",
        help="Single question to send (non-interactive)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation cases A–D",
    )
    parser.add_argument(
        "--force-core",
        action="store_true",
        help="Set force_core_query=true for single question mode",
    )
    parser.add_argument(
        "--customer-id",
        default=DEFAULT_CUSTOMER_ID,
        help=f"Customer ID (default: {DEFAULT_CUSTOMER_ID})",
    )
    parser.add_argument(
        "--conversation-id",
        default="",
        help="Conversation ID (auto-generated if empty)",
    )
    parser.add_argument(
        "--file", "-f",
        default="",
        help="Path to portfolio JSON file (for load-context/refresh-context/demo)",
    )
    # Subcommand-style positional (optional for backward compat)
    parser.add_argument(
        "command",
        nargs="?",
        choices=["health", "validate-ad", "turn", "dispatch", "load-context", "refresh-context", "demo"],
        help="Subcommand: health, validate-ad, load-context, refresh-context, demo",
    )

    args = parser.parse_args()

    endpoint = os.environ.get("COGNITIVE_BASE_URL", args.endpoint)
    customer_id = args.customer_id
    conversation_id = args.conversation_id or f"orch-{uuid.uuid4().hex[:8]}"

    # Subcommand routing
    if args.command == "health":
        check_health(endpoint)
    elif args.command == "validate-ad" or args.validate:
        success = run_validation(endpoint)
        sys.exit(0 if success else 1)
    elif args.command == "load-context":
        if not args.file:
            print(f"{_RED}--file required for load-context{_RESET}")
            sys.exit(1)
        load_context_cmd(endpoint, customer_id, conversation_id, args.file)
    elif args.command == "refresh-context":
        if not args.file:
            print(f"{_RED}--file required for refresh-context{_RESET}")
            sys.exit(1)
        refresh_context_cmd(endpoint, customer_id, conversation_id, args.file)
    elif args.command == "demo":
        if not args.file:
            # Default fixture
            from pathlib import Path
            default_fixture = Path(__file__).parent.parent / "tests" / "fixtures" / "core_portfolio_sample.json"
            file_path = str(default_fixture)
        else:
            file_path = args.file
        demo_session(endpoint, customer_id, file_path)
    elif args.question:
        # Single question mode
        try:
            data = call_turn(
                endpoint=endpoint,
                question=args.question,
                conversation_id=conversation_id,
                customer_id=customer_id,
                force_core_query=args.force_core,
            )
            route_response(data)
        except httpx.ConnectError:
            print(f"{_RED}Error: No se pudo conectar a {endpoint}{_RESET}")
            sys.exit(1)
        except httpx.HTTPStatusError as e:
            print(f"{_RED}Error HTTP {e.response.status_code}{_RESET}")
            sys.exit(1)
    else:
        interactive_mode(endpoint)


if __name__ == "__main__":
    main()
