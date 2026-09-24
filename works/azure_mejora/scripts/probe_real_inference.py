# -*- coding: utf-8 -*-
"""Prueba real de dependencias Azure desde esta PC. Sin imprimir secretos."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "Test_local" / ".env.local")

    report: dict = {
        "azure_openai": {"status": "UNKNOWN"},
        "azure_search": {"status": "UNKNOWN"},
        "redis_qa": {"status": "UNREACHABLE_PENDING", "note": "TCP timeout a bsc-cognitive-redis-qa:10000"},
    }

    # --- Azure OpenAI real inference ---
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    print("AOAI endpoint host:", endpoint.split("//")[-1][:40] if endpoint else "missing")
    print("AOAI deployment:", deployment)
    print("AOAI key present:", bool(key))

    if endpoint and key:
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=key,
                api_version=api_version,
                azure_endpoint=endpoint,
            )
            t0 = time.perf_counter()
            # Pregunta de comprensión (paráfrasis), no un atajo determinista
            resp = client.chat.completions.create(
                model=deployment,
                temperature=0,
                max_tokens=200,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un clasificador bancario. Responde SOLO JSON con keys: "
                            "intent, products, needs_temporal_window, rationale_short."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Mensaje: 'Oye, se me vence algo pronto? Dime si tengo que pagar "
                            "algún préstamo o tarjeta en estos días y cuánto.' "
                            "¿Qué intención es y qué productos toca?"
                        ),
                    },
                ],
            )
            ms = int((time.perf_counter() - t0) * 1000)
            choice = resp.choices[0]
            content = (choice.message.content or "").strip()
            report["azure_openai"] = {
                "status": "REAL_OK",
                "deployment": deployment,
                "latency_ms": ms,
                "finish_reason": getattr(choice, "finish_reason", None),
                "model_invoked": True,
                "content_preview": content[:240],
                "usage": {
                    "prompt_tokens": getattr(resp.usage, "prompt_tokens", None),
                    "completion_tokens": getattr(resp.usage, "completion_tokens", None),
                },
            }
            print("AOAI REAL_OK", ms, "ms")
            print("AOAI preview:", content[:200])
        except Exception as exc:
            report["azure_openai"] = {
                "status": "REAL_FAIL",
                "error_class": type(exc).__name__,
                "error": str(exc)[:200],
                "model_invoked": False,
            }
            print("AOAI FAIL", type(exc).__name__, str(exc)[:200])
    else:
        report["azure_openai"] = {"status": "MISSING_CONFIG", "model_invoked": False}
        print("AOAI missing config")

    # --- Azure Search ---
    search_ep = (os.getenv("AZURE_SEARCH_ENDPOINT") or "").rstrip("/")
    search_idx = os.getenv("AZURE_SEARCH_INDEX") or ""
    search_key = os.getenv("AZURE_SEARCH_API_KEY") or ""
    print("Search host:", search_ep.split("//")[-1][:50] if search_ep else "missing")
    print("Search index:", search_idx or "missing")
    print("Search key present:", bool(search_key))
    if search_ep and search_key and search_idx:
        try:
            import httpx

            r = httpx.get(
                f"{search_ep}/indexes/{search_idx}/docs/$count?api-version=2024-07-01",
                headers={"api-key": search_key},
                timeout=15.0,
            )
            if r.status_code == 200:
                report["azure_search"] = {
                    "status": "REAL_OK",
                    "index": search_idx,
                    "doc_count": int(r.text.strip()),
                    "http": 200,
                }
                print("SEARCH REAL_OK count=", r.text.strip())
            else:
                report["azure_search"] = {
                    "status": "REAL_FAIL",
                    "http": r.status_code,
                    "body": r.text[:120],
                }
                print("SEARCH FAIL", r.status_code, r.text[:120])
        except Exception as exc:
            report["azure_search"] = {
                "status": "REAL_FAIL",
                "error_class": type(exc).__name__,
                "error": str(exc)[:200],
            }
            print("SEARCH FAIL", type(exc).__name__, str(exc)[:200])
    else:
        report["azure_search"] = {"status": "MISSING_CONFIG"}

    out = ROOT / "works" / "azure_mejora" / "DEPENDENCIAS_REAL_VS_SIMULADO.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0 if report.get("azure_openai", {}).get("status") == "REAL_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
