#!/usr/bin/env python3
"""Captura conversaciones reales en /pruebas (Chrome) → images/fix/<run_id>/<case>_turno_NN.png

No inyecta respuestas en el DOM. Usa la UI QA y selecciona solo opciones presentadas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASOS = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes" / "evaluacion" / "casos_236.json"
P0 = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes" / "evaluacion" / "aceptacion_p0.json"
FIX_ROOT = ROOT / "works" / "validacion_guia_fix"
CUSTOMER = "726588"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cases(scope: str, only: list[str] | None) -> list[dict[str, Any]]:
    casos = json.loads(CASOS.read_text(encoding="utf-8"))
    if isinstance(casos, dict):
        casos = casos.get("cases") or []
    by_id = {str(c["case_id"]): c for c in casos if c.get("case_id")}
    p0 = json.loads(P0.read_text(encoding="utf-8"))
    if only:
        out = []
        have: set[str] = set()
        for i in only:
            if i in by_id:
                out.append(by_id[i])
                have.add(i)
            else:
                for p in p0:
                    if p.get("acceptance_id") == i and i not in have:
                        out.append({
                            "case_id": i,
                            "question": (p.get("turns") or [""])[0],
                            "turns": p.get("turns") or [],
                        })
                        have.add(i)
        return out
    if scope == "p0":
        ids = [str(x["acceptance_id"]) for x in p0]
        # Incluir P* del catálogo guía + MIX/CC + L* sintéticos
        extra = [
            "P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10",
            "P11", "P12", "P13", "P14", "P15", "TC03", "GR03", "GR09", "IG01",
            "MIX07", "MIX09", "MIX10", "CC02", "CC03",
        ]
        ordered = list(dict.fromkeys(ids + extra))
        out = []
        have: set[str] = set()
        for i in ordered:
            if i in by_id and i not in have:
                out.append(by_id[i])
                have.add(i)
            elif i not in have:
                for p in p0:
                    if p.get("acceptance_id") == i:
                        out.append({
                            "case_id": i,
                            "question": (p.get("turns") or [""])[0],
                            "turns": p.get("turns") or [],
                        })
                        have.add(i)
                        break
        return out
    return list(by_id.values())


def split_turns(case: dict[str, Any]) -> list[str]:
    turns = case.get("turns")
    if isinstance(turns, list) and turns:
        out: list[str] = []
        for t in turns:
            if not isinstance(t, str):
                continue
            parts = [p.strip() for p in re.split(r"\s*(?:→|->|⇒)\s*", t) if p.strip()]
            out.extend(parts or [t.strip()])
        return out
    q = str(case.get("question") or "").strip()
    return [q] if q else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://20.127.25.24:8447")
    ap.add_argument("--scope", choices=["p0", "all"], default="p0")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright no instalado", file=sys.stderr)
        return 2

    only = [x.strip() for x in args.only.split(",") if x.strip()]
    cases = load_cases(args.scope, only or None)
    if args.limit:
        cases = cases[: args.limit]

    run_id = args.run_id or f"{utc_now()}_{uuid.uuid4().hex[:8]}"
    img_dir = FIX_ROOT / "images" / "fix" / run_id
    img_dir.mkdir(parents=True, exist_ok=True)
    meta_path = FIX_ROOT / "qa_runs_ui" / run_id
    meta_path.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    url = args.base.rstrip("/") + "/pruebas"
    print(f"UI capture run={run_id} base={url} cases={len(cases)}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 420, "height": 900},
            device_scale_factor=2,
        )
        page = context.new_page()
        page.set_default_timeout(120_000)

        for idx, case in enumerate(cases, start=1):
            cid = str(case["case_id"])
            turns = split_turns(case)
            case_meta: dict[str, Any] = {
                "case_id": cid,
                "turns": [],
                "screenshots": [],
                "status": "STARTED",
                "error": None,
            }
            print(f"[{idx}/{len(cases)}] {cid} turns={len(turns)}", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.fill("#loginUser", CUSTOMER)
                # Preferir lab fallback: no marcar requireCore
                page.uncheck("#requireCore") if page.is_checked("#requireCore") else None
                page.click("#btnLogin")
                # Passkey skip si aparece
                try:
                    page.wait_for_selector("#screenChat:not([hidden]), #btnSkipPasskey, #chatInput", timeout=20000)
                except Exception:
                    pass
                if page.locator("#btnSkipPasskey").count():
                    try:
                        page.click("#btnSkipPasskey", timeout=3000)
                    except Exception:
                        pass
                # Esperar chat + input habilitado (id real: #input)
                page.wait_for_selector("#screenChat:not([hidden])", timeout=45000)
                if page.locator("#btnSkipPasskey").count() and page.locator("#screenPasskey:not([hidden])").count():
                    try:
                        page.click("#btnSkipPasskey", timeout=3000)
                    except Exception:
                        pass
                page.wait_for_selector("#input:not([disabled])", timeout=60000)
                input_sel = "#input"
                # Asegurar chat visible
                for t_i, user_text in enumerate(turns, start=1):
                    page.fill(input_sel, user_text)
                    # Enviar
                    if page.locator("#btnSend").count():
                        page.click("#btnSend")
                    else:
                        page.locator(input_sel).press("Enter")
                    # Esperar fin de typing
                    try:
                        page.wait_for_selector("#typingRow", state="detached", timeout=90000)
                    except Exception:
                        page.wait_for_timeout(2500)
                    page.wait_for_timeout(800)
                    # Si hay opciones de selección, tomar la primera visible
                    opts = page.locator(".option-btn, button.option, .chip-option, [data-option]")
                    if opts.count() > 0 and t_i < len(turns):
                        # No auto-seleccionar si el siguiente turno es la aclaración textual
                        pass
                    elif opts.count() > 0:
                        try:
                            opts.first.click(timeout=2000)
                            try:
                                page.wait_for_selector("#typingRow", state="detached", timeout=90000)
                            except Exception:
                                page.wait_for_timeout(1500)
                        except Exception:
                            pass
                    shot = img_dir / f"{cid}_turno_{t_i:02d}.png"
                    # Capturar el dispositivo/chat completo
                    target = page.locator(".device").first if page.locator(".device").count() else page
                    target.screenshot(path=str(shot))
                    case_meta["screenshots"].append({
                        "path": str(shot.relative_to(FIX_ROOT)).replace("\\", "/"),
                        "sha256": sha256_file(shot),
                        "turn": t_i,
                    })
                    case_meta["turns"].append({"question": user_text, "screenshot": shot.name})
                # Captura final de conversación completa
                final = img_dir / f"{cid}_full.png"
                target = page.locator(".device").first if page.locator(".device").count() else page
                # Scroll chat al inicio y fin para evidencia; una captura del viewport
                chat = page.locator("#chat, .chat-body").first
                if chat.count():
                    chat.evaluate("el => { el.scrollTop = 0 }")
                    page.wait_for_timeout(200)
                target.screenshot(path=str(final))
                case_meta["screenshots"].append({
                    "path": str(final.relative_to(FIX_ROOT)).replace("\\", "/"),
                    "sha256": sha256_file(final),
                    "turn": "full",
                })
                case_meta["status"] = "CAPTURED"
            except Exception as exc:
                case_meta["status"] = "CAPTURE_FAILED"
                case_meta["error"] = str(exc)[:500]
                print(f"  ERROR {cid}: {exc}", flush=True)
            results.append(case_meta)
            (meta_path / "capturas.jsonl").open("a", encoding="utf-8").write(
                json.dumps(case_meta, ensure_ascii=False) + "\n"
            )

        browser.close()

    manifest = {
        "run_id": run_id,
        "base": args.base,
        "customer": CUSTOMER,
        "scope": args.scope,
        "generated_utc": utc_now(),
        "cases": len(results),
        "captured": sum(1 for r in results if r["status"] == "CAPTURED"),
        "failed": sum(1 for r in results if r["status"] != "CAPTURED"),
        "images_dir": str(img_dir.relative_to(FIX_ROOT)).replace("\\", "/"),
    }
    (meta_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0 if manifest["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
