"""Valida Excel KB VF01 desde fila 79 contra 8447: respuesta real vs esperada.

Uso:
  $env:GENESIS_VALIDATE_BASE=\"http://20.127.25.24:8447\"
  $env:GENESIS_VALIDATE_CUSTOMER=\"726588\"
  .\\.venv\\Scripts\\python.exe Test_local\\validate_excel_from_row79.py
  .\\.venv\\Scripts\\python.exe Test_local\\validate_excel_from_row79.py --limit 40
  .\\.venv\\Scripts\\python.exe Test_local\\validate_excel_from_row79.py --all-exprs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

try:
    import openpyxl
except ImportError:
    print("ERROR: pip install openpyxl")
    raise SystemExit(1)

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "726588")
DEFAULT_EXCEL = os.getenv(
    "GENESIS_KB_EXCEL_PATH",
    r"c:\Users\zeusa\Downloads\Base de Conocimiento IA VF01.xlsx",
)
FROM_ROW = 79
RESULTS = Path(__file__).resolve().parent / "results"


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _tokens(text: str) -> set[str]:
    stop = {
        "de", "la", "el", "los", "las", "un", "una", "y", "o", "en", "del", "al",
        "por", "para", "con", "que", "se", "su", "sus", "es", "son", "como", "mas",
        "este", "esta", "estos", "estas", "tu", "tus", "mi", "mis", "the", "a",
    }
    return {w for w in _norm(text).split() if len(w) > 2 and w not in stop}


def _split_expressions(raw: str) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in re.split(r"\s*\|\s*", str(raw)) if p and p.strip()]


def _is_weak(answer: str, topic: str) -> bool:
    a = (answer or "").strip()
    if not a or len(a) < 40:
        return True
    low = a.lower()
    if low.startswith("tema de información general") or low.startswith("tema de informacion general"):
        return True
    if "basada exclusivamente en el contexto aprobado" in low:
        return True
    if "[respuesta" in low:
        return True
    if "la misma respuesta funcional" in low:
        return True
    if a.lower() == (topic or "").strip().lower():
        return True
    return False


def _is_placeholder_expr(expr: str) -> bool:
    e = (expr or "").lower()
    return "[" in e or "]" in e


def _is_garbage_section_expr(expr: str) -> bool:
    """Excel a veces pega el mismo 'Cuéntame sobre 4.2.5...' en muchos topics."""
    e = (expr or "").strip()
    if not e:
        return True
    if re.search(r"\d+\.\d+(\.\d+)?", e) and re.search(r"(cu[eé]ntame|h[aá]blame)\s+sobre", e, re.I):
        return True
    # expresión genérica repetida que no nombra el topic
    if re.match(r"(?i)^cu[eé]ntame\s+sobre\s+\d", e):
        return True
    return False


def _expression_for_intent(expr: str, topic: str) -> str:
    """Si la expresión Excel es basura, preguntar por el topic (prueba de intención)."""
    if _is_garbage_section_expr(expr) and topic:
        return f"Cuéntame sobre {topic}"
    return expr


def _is_personal_ops(intent: str, topic: str, exprs: list[str]) -> bool:
    blob = _norm(" ".join([intent or "", topic or "", " ".join(exprs)]))
    keys = (
        "saldo", "balance", "disponible", "mi cuenta", "mis productos", "mi prestamo",
        "mi tarjeta", "cuota", "limite", "movimientos", "transfer",
    )
    return any(k in blob for k in keys)


def overlap_score(expected: str, actual: str) -> float:
    et = _tokens(expected)
    at = _tokens(actual)
    if not et or not at:
        return 0.0
    return len(et & at) / max(len(et), 1)


def key_phrases_hit(expected: str, actual: str, min_len: int = 12) -> tuple[float, list[str]]:
    """Fracciones de frases/cláusulas del esperado presentes en la respuesta."""
    parts = re.split(r"[.\n;:]+", expected or "")
    phrases = [p.strip() for p in parts if len(p.strip()) >= min_len][:8]
    if not phrases:
        return overlap_score(expected, actual), []
    an = _norm(actual)
    hits = []
    for p in phrases:
        pn = _norm(p)
        # exigir al menos 60% de tokens de la frase
        pt = _tokens(p)
        if not pt:
            continue
        if len(pt & _tokens(actual)) / len(pt) >= 0.55 or pn[:40] in an:
            hits.append(p[:60])
    return (len(hits) / max(len(phrases), 1), hits)


def load_cases(excel: Path, from_row: int) -> list[dict]:
    wb = openpyxl.load_workbook(excel, data_only=True)
    ws = wb["Matriz_Cuentas"] if "Matriz_Cuentas" in wb.sheetnames else wb[wb.sheetnames[0]]
    best: dict[str, dict] = {}
    for r in range(from_row, ws.max_row + 1):
        func = ws.cell(r, 1).value
        producto = ws.cell(r, 5).value or ""
        intencion = ws.cell(r, 7).value or ""
        dato = ws.cell(r, 8).value or ""
        expresiones = ws.cell(r, 9).value or ""
        ambig = str(ws.cell(r, 12).value or "").strip()
        resp_patron = str(ws.cell(r, 23).value or "").strip()
        resp_esperada = str(ws.cell(r, 24).value or "").strip()
        if not any([func, expresiones, resp_esperada, resp_patron, dato]):
            continue
        topic = str(dato or func or f"fila-{r}").strip()
        candidates = [resp_esperada, resp_patron]
        answer = ""
        for cand in candidates:
            if not _is_weak(cand, topic):
                answer = cand
                break
        if not answer:
            continue
        exprs = [e for e in _split_expressions(str(expresiones)) if not _is_placeholder_expr(e)]
        if not exprs:
            continue
        key = _norm(topic) or f"row-{r}"
        entry = {
            "row": r,
            "topic": topic,
            "product": str(producto).strip(),
            "intent": str(intencion).strip(),
            "expressions": exprs,
            "answer": answer,
            "ambiguity": ambig,
            "personal": _is_personal_ops(str(intencion), topic, exprs),
        }
        prev = best.get(key)
        if prev is None or len(answer) > len(prev["answer"]):
            if prev:
                entry["expressions"] = list(dict.fromkeys(prev["expressions"] + exprs))
            best[key] = entry
    return sorted(best.values(), key=lambda x: x["row"])


def post(path: str, payload: dict, timeout: int = 90) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def login() -> str:
    data = post("/lab/login", {"customer_id": CUSTOMER})
    cid = data.get("conversation_id")
    if not cid:
        raise RuntimeError(f"login falló: {data}")
    return cid


def ask(cid: str, question: str) -> tuple[str, str, str]:
    data = post(
        "/turn",
        {
            "question": question,
            "customer_id": CUSTOMER,
            "conversation_id": cid,
            "allow_lab_fallback": True,
        },
    )
    app = data.get("app_channel") or {}
    status = str(data.get("status") or app.get("status") or "")
    intent = str(app.get("intent_id") or "")
    text = (
        app.get("client_response")
        or data.get("client_response")
        or data.get("reply")
        or ""
    ).strip()
    return status, intent, text


def evaluate(case: dict, question: str, status: str, text: str) -> tuple[bool, str, float]:
    low = text.lower()
    # Fallos duros (alucinación / escalación / vacío)
    if not text:
        return False, "respuesta vacía", 0.0
    if "asesor se pondra" in low or "numero de caso" in low:
        return False, "escaló a asesor humano", 0.0
    if "contrato válido" in low or "contrato valido" in low:
        return False, "plantilla interna Contrato válido", 0.0
    if "no se pudo generar" in low:
        return False, "fallback orquestador vacío", 0.0

    expected = case["answer"]
    score, hits = key_phrases_hit(expected, text)
    ov = overlap_score(expected, text)

    # Clarificación esperada
    amb = (case.get("ambiguity") or "").lower()
    if amb in ("sí", "si", "posible") and case.get("personal"):
        if status in ("CLARIFICATION_REQUIRED", "requires_selection") or "?" in text:
            return True, f"aclaración OK (score={score:.2f})", max(score, 0.7)

    # Operativo personal: no exigir texto literal del Excel (montos de ejemplo)
    if case.get("personal"):
        if status in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED", "requires_selection", "NON_OPERATIONAL", "UNSUPPORTED"):
            # Debe sonar bancario / útil
            if any(k in low for k in ("saldo", "cuenta", "prestamo", "préstamo", "tarjeta", "producto", "no tienes", "deseas")):
                return True, f"operativo coherente status={status}", max(ov, 0.6)
            return False, f"operativo poco alineado status={status}", ov

    # FAQ / institucional: exigir overlap razonable
    combined = max(score, ov)
    # umbral: frases cortas más permisivas
    threshold = 0.28 if len(_tokens(expected)) > 25 else 0.35
    if combined >= threshold:
        return True, f"contenido OK score={combined:.2f} hits={len(hits)}", combined
    # si la respuesta contiene el topic o definición parcial
    topic_toks = _tokens(case["topic"])
    if topic_toks and len(topic_toks & _tokens(text)) / len(topic_toks) >= 0.5 and len(text) > 60:
        return True, f"topic cubierto score={combined:.2f}", combined
    return False, f"bajo overlap score={combined:.2f} esperado!=respuesta", combined


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", default=DEFAULT_EXCEL)
    ap.add_argument("--from-row", type=int, default=FROM_ROW)
    ap.add_argument("--limit", type=int, default=0, help="Máx casos (0=todos)")
    ap.add_argument("--all-exprs", action="store_true", help="Probar todas las expresiones (más lento)")
    ap.add_argument("--faq-only", action="store_true", help="Solo filas no personales")
    args = ap.parse_args()

    excel = Path(args.excel)
    if not excel.is_file():
        print(f"ERROR: no existe {excel}")
        return 1

    cases = load_cases(excel, args.from_row)
    if args.faq_only:
        cases = [c for c in cases if not c["personal"]]
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]

    print("=" * 78)
    print(f"VALIDACION EXCEL filas>={args.from_row} | user={CUSTOMER} | {BASE}")
    print(f"Casos únicos por topic: {len(cases)} | all_exprs={args.all_exprs}")
    print("=" * 78)

    # smoke login
    try:
        cid0 = login()
        print(f"login OK cid={cid0[:8]}...")
    except Exception as exc:
        print(f"ERROR login: {exc}")
        return 1

    rows: list[dict] = []
    passes = fails = 0

    for i, case in enumerate(cases, 1):
        exprs = case["expressions"] if args.all_exprs else case["expressions"][:1]
        for expr in exprs:
            question = _expression_for_intent(expr, case["topic"])
            try:
                cid = login()
                status, intent, text = ask(cid, question)
            except Exception as exc:
                status, intent, text = "ERROR", "", str(exc)
            ok, reason, score = evaluate(case, question, status, text)
            if ok:
                passes += 1
                mark = "PASS"
            else:
                fails += 1
                mark = "FAIL"
            row = {
                "row": case["row"],
                "topic": case["topic"],
                "product": case["product"],
                "question": question,
                "ok": ok,
                "reason": reason,
                "score": round(score, 3),
                "status": status,
                "intent": intent,
                "expected": case["answer"][:300],
                "actual": text[:400],
            }
            rows.append(row)
            print(
                f"[{mark}] r{case['row']} {case['topic'][:40]!r} | {question[:55]!r}".encode("ascii", "replace").decode("ascii")
            )
            print(f"       {reason} | status={status}".encode("ascii", "replace").decode("ascii"))
            if not ok:
                esp = case["answer"][:140].replace("\n", " ")
                act = text[:140].replace("\n", " ")
                print(f"       ESP: {esp}".encode("ascii", "replace").decode("ascii"))
                print(f"       ACT: {act}".encode("ascii", "replace").decode("ascii"))
            if i % 25 == 0:
                print(f"--- progreso {i}/{len(cases)} (PASS {passes} FAIL {fails}) ---")

            # escribir progreso incremental
            if (passes + fails) % 10 == 0:
                RESULTS.mkdir(exist_ok=True)
                tmp = RESULTS / f"excel_row{args.from_row}_{CUSTOMER}_8447.partial.json"
                tmp.write_text(
                    json.dumps({"pass": passes, "fail": fails, "rows": rows}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"excel_row{args.from_row}_{CUSTOMER}_8447.json"
    summary = {
        "base": BASE,
        "customer_id": CUSTOMER,
        "from_row": args.from_row,
        "pass": passes,
        "fail": fails,
        "total": passes + fails,
        "pass_rate": round(passes / max(passes + fails, 1), 3),
        "rows": rows,
    }
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # resumen por producto
    by_prod: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_prod[r["product"] or "General"].append(r["ok"])
    print()
    print("=" * 78)
    print(f"TOTAL {passes}/{passes+fails} PASS ({summary['pass_rate']*100:.1f}%)")
    print("Por producto:")
    for prod, oks in sorted(by_prod.items(), key=lambda x: x[0]):
        p = sum(1 for x in oks if x)
        print(f"  {prod[:50]}: {p}/{len(oks)}")
    print(f"Detalle: {out}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
