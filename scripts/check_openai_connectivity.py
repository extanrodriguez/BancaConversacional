"""OpenAI Responses API connectivity preflight — validates inference without exposing secrets."""

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> int:
    # Load env from project .env without printing values
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    if not api_key:
        print("RESULT: FAIL")
        print("ERROR: MISSING_OPENAI_API_KEY")
        return 1

    if not model:
        print("RESULT: FAIL")
        print("ERROR: MISSING_OPENAI_MODEL")
        return 1

    # Normalize: ensure base_url ends with /v1 but not /v1/v1
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"

    endpoint = f"{base_url}/responses"
    host = base_url.split("//")[-1].split("/")[0]

    payload = {
        "model": model,
        "instructions": "Return exactly GENESIS_CONNECTIVITY_OK.",
        "input": "Connectivity check.",
        "store": False,
        "max_output_tokens": 32,
    }

    start = time.perf_counter()
    try:
        resp = httpx.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    except httpx.ConnectError:
        print("RESULT: FAIL")
        print("ERROR: NETWORK_ERROR")
        return 1
    except httpx.TimeoutException:
        print("RESULT: FAIL")
        print("ERROR: NETWORK_ERROR (timeout)")
        return 1

    latency_ms = (time.perf_counter() - start) * 1000

    if resp.status_code == 401:
        print("RESULT: FAIL")
        print("ERROR: AUTHENTICATION_FAILED")
        return 1
    if resp.status_code in (403, 404):
        print("RESULT: FAIL")
        print("ERROR: MODEL_NOT_FOUND_OR_FORBIDDEN")
        return 1
    if resp.status_code == 429:
        print("RESULT: FAIL")
        print("ERROR: RATE_LIMITED")
        return 1
    if resp.status_code != 200:
        print("RESULT: FAIL")
        print(f"ERROR: UNEXPECTED_RESPONSE (HTTP {resp.status_code})")
        return 1

    data = resp.json()
    status = data.get("status")
    if status != "completed":
        print("RESULT: FAIL")
        print(f"ERROR: INCOMPLETE_RESPONSE (status={status})")
        return 1

    # Extract output_text from Responses API structure
    output_text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text", "")

    if not output_text:
        print("RESULT: FAIL")
        print("ERROR: UNEXPECTED_RESPONSE (no output_text)")
        return 1

    output_match = output_text.strip() == "GENESIS_CONNECTIVITY_OK"
    if not output_match:
        print("RESULT: FAIL")
        print("ERROR: UNEXPECTED_OUTPUT")
        return 1

    # Extract usage
    usage = data.get("usage", {})
    input_tokens = usage.get("input_tokens", "N/A")
    output_tokens = usage.get("output_tokens", "N/A")

    # Write sanitized evidence
    evidence_path = (
        Path(__file__).parent.parent / "evidence" / "t08-c6-openai-responses-connectivity.txt"
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence = (
        f"date_utc: {datetime.now(tz=UTC).isoformat()}\n"
        f"endpoint_host: {host}\n"
        f"endpoint_path: /v1/responses\n"
        f"model: {model}\n"
        f"http_status: {resp.status_code}\n"
        f"response_status: {status}\n"
        f"output_match: {output_match}\n"
        f"latency_ms: {latency_ms:.0f}\n"
        f"input_tokens: {input_tokens}\n"
        f"output_tokens: {output_tokens}\n"
        f"store_requested: false\n"
        f"result: PASS\n"
        f"exit_code: 0\n"
    )
    evidence_path.write_text(evidence, encoding="utf-8")

    print("RESULT: PASS")
    print(f"model: {model}")
    print(f"endpoint: {host}/v1/responses")
    print(f"output_match: {output_match}")
    print(f"latency_ms: {latency_ms:.0f}")
    print(f"tokens: {input_tokens}/{output_tokens}")
    print("store: false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
