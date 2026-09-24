"""Evaluador estricto Potenciación Lunes (Fase 5/6).

Una respuesta no vacía no implica aprobación. Evalúa por caso y por turno:
producto, campos/tareas, continuidad, aclaración y origen.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes"
P0_PATH = PKG / "evaluacion" / "aceptacion_p0.json"
CASOS_PATH = PKG / "evaluacion" / "casos_236.json"

ORACLE_VERSION = "strict_v2.2"


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[¿?¡!.,;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_p0_meta() -> dict[str, dict[str, Any]]:
    raw = _load_json(P0_PATH)
    out: dict[str, dict[str, Any]] = {}
    for item in raw:
        aid = str(item.get("acceptance_id") or "")
        if aid:
            out[aid] = item
        for gid in item.get("guide_case_ids") or []:
            out[str(gid)] = item
    return out


def load_case_meta() -> dict[str, dict[str, Any]]:
    raw = _load_json(CASOS_PATH)
    cases = raw.get("cases") if isinstance(raw, dict) else raw
    return {str(c.get("case_id")): c for c in (cases or []) if c.get("case_id")}


_P0_META: dict[str, dict[str, Any]] | None = None
_CASE_META: dict[str, dict[str, Any]] | None = None


def p0_meta() -> dict[str, dict[str, Any]]:
    global _P0_META
    if _P0_META is None:
        _P0_META = load_p0_meta()
    return _P0_META


def case_meta() -> dict[str, dict[str, Any]]:
    global _CASE_META
    if _CASE_META is None:
        _CASE_META = load_case_meta()
    return _CASE_META


def _has_money(text: str) -> bool:
    return bool(re.search(r"(rd\$|us\$|\$)\s*[\d,.]+|\[\s*amt\s*\]", text or "", re.I))


def _has_rate(text: str) -> bool:
    return bool(re.search(r"\d[\d,.]*\s*%|\[\s*rate\s*\]", text or "", re.I)) or "tasa" in (text or "").lower()


def _provider_error(text: str) -> bool:
    t = _norm(text)
    return any(
        s in t
        for s in (
            "no pude completar la interpretacion",
            "no pude completar la consulta",
            "intenta de nuevo o reformula",
        )
    )


def _movements_absent_ok(text: str) -> bool:
    t = _norm(text)
    return any(
        s in t
        for s in (
            "historial de movimientos no",
            "movimientos no estan disponibles",
            "movimientos no esta disponible",
            "no invente transacciones",
            "no inventé transacciones",
            "ausencia de evidencia",
            "no dispongo de movimientos",
            "no tengo movimientos",
        )
    ) or (
        "movimientos" in t
        and any(s in t for s in ("no disponible", "no estan", "no está", "no esta", "no puedo consultar"))
    )


def _facet_hit(facet: str, text: str) -> str:
    """Y = presente con dato; A = ausencia explícita; C = aclaración; N = omitido/incorrecto."""
    t = _norm(text)
    raw = text or ""
    if _provider_error(raw) and facet not in ("transactions",):
        return "N"
    if facet in ("current_debt", "outstanding_balance", "debt"):
        if any(s in t for s in ("adeud", "debo", "saldo actual", "saldo adeud", "capital", "te queda", "debes")) and (
            _has_money(raw) or "rd$" in t or "[amt]" in t
        ):
            return "Y"
        if "saldo" in t and _has_money(raw) and "disponible" not in t.split("saldo")[0][-20:]:
            # «saldo … RD$» sin «disponible» adyacente
            if "disponible" not in t or t.find("saldo") < t.find("disponible"):
                return "Y"
        return "N"
    if facet in ("available_credit", "available", "available_balance"):
        if "disponible" in t and (_has_money(raw) or "rd$" in t or "[amt]" in t):
            return "Y"
        if any(s in t for s in ("limite disponible", "límite disponible", "cupo")) and _has_money(raw):
            return "Y"
        return "N"
    if facet in ("minimum_payment", "min_payment"):
        if any(s in t for s in ("pago minimo", "pago mínimo", "minimo", "mínimo")) and (
            _has_money(raw) or "rd$" in t or "[amt]" in t
        ):
            return "Y"
        if any(s in t for s in ("pago minimo", "pago mínimo")) and any(
            s in t for s in ("no dispon", "no regist", "no tengo", "ausente", "no disponible")
        ):
            return "A"
        return "N"
    if facet in ("due_date", "next_payment_date", "payment_due_date", "payment_date"):
        if any(
            s in t
            for s in (
                "fecha",
                "vence",
                "vencimiento",
                "limite de pago",
                "límite de pago",
                "te toca",
                "proxima fecha de pago",
                "próxima fecha de pago",
            )
        ):
            return "Y"
        return "N"
    if facet in ("interest_rate", "rate"):
        return "Y" if _has_rate(raw) else "N"
    if facet in ("installment_amount", "installment"):
        if "cuota" in t and (_has_money(raw) or "rd$" in t or "[amt]" in t):
            return "Y"
        return "N"
    if facet in ("payoff_amount", "payoff"):
        if any(s in t for s in ("cancel", "saldar", "payoff", "liquidar")) and (
            _has_money(raw) or "rd$" in t or "[amt]" in t
        ):
            return "Y"
        if any(s in t for s in ("cancel", "saldar")) and any(
            s in t for s in ("no dispon", "no regist", "ausente", "no disponible", "no tengo el monto")
        ):
            return "A"
        return "N"
    if facet in ("transactions", "movements", "transactions_last_3"):
        if _movements_absent_ok(raw):
            return "A"
        if any(s in t for s in ("movimiento", "transaccion", "transacción", "consumo reciente")) and _has_money(raw):
            return "Y"
        return "N"
    if facet in ("ledger_balance", "current_balance"):
        if any(s in t for s in ("saldo actual", "balance actual", "saldo en", "tu saldo")) and (
            _has_money(raw) or "rd$" in t or "[amt]" in t
        ):
            return "Y"
        if "saldo" in t and _has_money(raw) and "disponible" not in t:
            return "Y"
        return "N"
    if facet == "opening_amount":
        if any(s in t for s in ("inverti", "invertí", "monto inicial", "capital inicial", "apertura")) and (
            _has_money(raw) or "rd$" in t or "[amt]" in t
        ):
            return "Y"
        if any(s in t for s in ("inverti", "invertí", "monto inicial")) and any(
            s in t for s in ("no dispon", "no regist", "ausente", "no disponible")
        ):
            return "A"
        return "N"
    if facet == "interest_earned":
        if any(s in t for s in ("generado", "intereses ganados", "interes ganado", "rendimiento")) and (
            _has_money(raw) or "rd$" in t or "[amt]" in t
        ):
            return "Y"
        if any(s in t for s in ("generado", "intereses")) and any(
            s in t for s in ("no dispon", "no regist", "ausente", "no disponible")
        ):
            return "A"
        return "N"
    if facet in ("maturity_date", "earliest_maturity"):
        if any(s in t for s in ("vence", "vencimiento", "fecha de vencimiento", "vence primero", "vence el")):
            return "Y"
        return "N"
    if facet == "balance_semantics_resolved":
        # «cuánto tengo» resuelto como saldo actual o disponible con monto
        if (_has_money(raw) or "rd$" in t or "[amt]" in t) and any(
            s in t for s in ("saldo", "disponible", "balance", "tienes")
        ):
            return "Y"
        return "N"
    if facet == "compare_available_credit_same_currency":
        if any(
            s in t
            for s in (
                "mas credito disponible",
                "más crédito disponible",
                "mayor disponible",
                "tiene mas credito",
                "tiene más crédito",
            )
        ):
            return "Y"
        if "disponible" in t and any(s in t for s in ("mas", "más", "mayor", "compar")) and _has_money(raw):
            return "Y"
        return "N"
    if facet == "payment_window_resolved":
        # Exige cálculo explícito de ventana (referencia + TZ + intervalo).
        # Tener «fecha de pago» o «próxima fecha» sin ventana NO basta.
        has_window = (
            ("ventana temporal" in t or "ventana de evaluacion" in t or "ventana de evaluación" in t)
            and ("america/santo_domingo" in t or "zona horaria" in t)
            and (
                "intervalo" in t
                or "proximos" in t
                or "próximos" in t
                or re.search(r"\b\d+\s*dias\b", t)
                or re.search(r"\b\d+\s*días\b", t)
            )
            and bool(re.search(r"20\d{2}-\d{2}-\d{2}", raw or text or ""))
        )
        distinguishes = any(
            s in t
            for s in (
                "no es pago proximo",
                "no es pago próximo",
                "fuera del intervalo",
                "fuera de la ventana",
                "no equivale a pago proximo",
                "no implica que el pago sea proximo",
                "dentro de la ventana",
                "pago proximo dentro",
                "pago próximo dentro",
            )
        ) or ("pago proximo" in t or "pago próximo" in t)
        if has_window and distinguishes:
            return "Y"
        if has_window:
            return "A"
        return "N"
    if facet == "payment_amount_semantics_resolved":
        if any(s in t for s in ("cuota", "pago minimo", "pago mínimo", "debo pagar")) and (
            _has_money(raw) or "rd$" in t or "[amt]" in t
        ):
            return "Y"
        return "N"
    if facet == "clarification":
        return "Y" if any(s in t for s in ("cual", "cuál", "selecciona", "sobre cual", "opcion", "opción")) else "N"
    return "N"


def _wrong_product_loan_as_multicredit(text: str, question: str) -> bool:
    q = _norm(question)
    t = _norm(text)
    if "prestamo" in q and "cancel" in q:
        if "multicredit" in t or "credito diferido" in t or "cuotas bsc" in t:
            if "prestamo personal" not in t and "prestamos personales" not in t:
                return True
    return False


def _compare_complete(turns: list[dict[str, Any]]) -> dict[str, str]:
    """Evalúa continuidad de comparación ordenada (CC02/L10)."""
    out = {
        "initial_set": "N",
        "differences": "N",
        "expand_gold": "N",
        "ordinal_second": "N",
        "provider_errors": "N",
        "product_evidence_match": "N",
        "attribute_contrast": "N",
    }
    if not turns:
        return out
    joined = "\n".join(str(t.get("reply") or t.get("text") or "") for t in turns)
    jn = _norm(joined)
    if "visa platinum" in jn and "visa infinite" in jn and "compar" in jn:
        out["initial_set"] = "Y"
    # Evidencia cruzada: bloque Platinum no puede ser solo Visa Joven
    wrong_xprod = False
    # Heurística: tras encabezado Platinum, si aparece JOVEN antes del siguiente producto
    low = joined.lower()
    idx_plat = low.find("visa platinum")
    idx_inf = low.find("visa infinite")
    if idx_plat >= 0:
        window_end = idx_inf if idx_inf > idx_plat else min(len(low), idx_plat + 800)
        window = low[idx_plat:window_end]
        if "visa joven" in window or "tarjetas de credito visa joven" in window or "subsegmento joven" in window:
            if "platinum" not in window.replace("visa platinum", ""):
                wrong_xprod = True
            # Si el cuerpo es claramente Joven sin Platinum en el extracto
            if "joven" in window and "platino" not in window and window.count("platinum") <= 1:
                # solo el encabezado menciona platinum
                body = window.split("\n", 1)[-1] if "\n" in window else window
                if "joven" in body and "platinum" not in body and "platino" not in body:
                    wrong_xprod = True
    out["product_evidence_match"] = "N" if wrong_xprod else ("Y" if out["initial_set"] == "Y" else "N")
    # Diferencias: contraste de atributos equivalentes (no «textos distintos»)
    diff_turns = [
        t for t in turns
        if any(
            s in _norm(str(t.get("question") or ""))
            for s in ("diferente", "diferencia", "caracteristic")
        )
    ]
    if diff_turns:
        ok_diff = False
        ok_attr = False
        for t in diff_turns:
            r = _norm(str(t.get("reply") or ""))
            raw = str(t.get("reply") or "")
            if _provider_error(raw):
                continue
            if wrong_xprod:
                continue
            if any(
                s in r
                for s in (
                    "no aparece este atributo", "atributo", "segmento", "requisito",
                    "beneficio", "tarifa", "limite", "límite", "mientras que",
                    "en cambio", "a diferencia", "descripcion / condiciones",
                    "descripción / condiciones",
                )
            ) and ("platinum" in r and "infinite" in r):
                ok_attr = True
            # Rechazar justificación débil «textos no idénticos» / «productos distintos» sola
            weak_only = (
                ("no es identico" in r or "no es idéntico" in r or "textos" in r)
                and "atributo" not in r
                and "segmento" not in r
                and "requisito" not in r
                and "«" not in raw and '"' not in raw
            )
            # Contraste con valores concretos entre comillas / extractos
            has_concrete = (
                ("«" in raw and "»" in raw)
                or raw.count("→") >= 2
                or ("→ «" in raw)
            )
            if has_concrete and "platinum" in r and "infinite" in r:
                ok_attr = True
            if ("platinum" in r and "infinite" in r) and not weak_only and (
                ok_attr
                or any(s in r for s in ("diferencia", "atributo", "segmento", "requisito", "beneficio"))
                or has_concrete
            ):
                ok_diff = True
        out["differences"] = "Y" if ok_diff else "N"
        out["attribute_contrast"] = "Y" if ok_attr else "N"
    else:
        out["differences"] = "A"
        out["attribute_contrast"] = "A"
    expand = [t for t in turns if "gold" in _norm(str(t.get("question") or "")) or "agrega" in _norm(str(t.get("question") or ""))]
    if expand:
        r = _norm(str(expand[-1].get("reply") or ""))
        out["expand_gold"] = "Y" if ("gold" in r or "oro" in r) and "platinum" in r and "infinite" in r else "N"
    ordinal = [
        t for t in turns
        if any(s in _norm(str(t.get("question") or "")) for s in ("segunda", "segundo", "de las tres"))
    ]
    if ordinal:
        r = _norm(str(ordinal[-1].get("reply") or ""))
        raw_o = str(ordinal[-1].get("reply") or "")
        # No acreditar ordinal si la evidencia es de otro producto (empresarial/joven)
        bad_ord = any(s in r for s in ("visa joven", "empresarial", "subsegmento joven"))
        out["ordinal_second"] = "Y" if "infinite" in r and "seleccionaste" in r and not bad_ord else "N"
        if bad_ord:
            out["product_evidence_match"] = "N"
    if any(_provider_error(str(t.get("reply") or "")) for t in turns):
        out["provider_errors"] = "Y"
    return out


def _is_personal_portfolio_case(case_id: str) -> bool:
    """Casos de portafolio personal (no catálogo/IG/PR institucional)."""
    cid = (case_id or "").upper()
    if re.match(r"^P\d", cid):
        return True
    if re.match(r"^C\d", cid):  # C01 continuity, no CA/CC/CD/CE/CMP
        return True
    if re.match(r"^D\d", cid) or re.match(r"^R\d", cid) or re.match(r"^X\d", cid):
        return True
    if cid.startswith(("MIX", "CTX")):
        return True
    return False


def _topic_overlap(question: str, reply: str, *, min_hits: int = 1) -> bool:
    qn = _norm(question)
    tn = _norm(reply)
    stop = {
        "que", "qué", "cual", "cuál", "como", "cómo", "donde", "dónde", "cuando",
        "cuándo", "tiene", "tengo", "puedo", "puede", "para", "por", "con", "una",
        "unos", "unas", "del", "los", "las", "mis", "mi", "tu", "sus", "el", "la",
        "de", "en", "y", "o", "a", "al", "un", "es", "son", "me", "te", "se",
        "si", "sí", "no", "hay", "mas", "más", "ahora", "tambien", "también",
    }
    tokens = [w for w in re.findall(r"[a-z0-9]{4,}", qn) if w not in stop]
    if not tokens:
        return len(tn) > 60
    hits = sum(1 for w in tokens if w in tn)
    return hits >= min_hits


def _evaluate_guide_typed_oracle(
    case_id: str,
    question: str,
    combined: str,
    turns: list[dict[str, Any]],
    expected: str,
) -> tuple[str, dict[str, Any]] | None:
    """Oráculos tipados derivados de la guía (expected + familia)."""
    cid = (case_id or "").upper()
    # Solo IDs presentes en la guía 236 (evita aprobar/fallar IDs sintéticos de unit tests)
    if cid not in case_meta():
        return None
    qn = _norm(question)
    tn = _norm(combined)
    exp = _norm(expected or "")
    facets: dict[str, str] = {"guide_oracle": "Y"}

    if _provider_error(combined):
        return "FAIL_INTERPRETATION", {"facets": {**facets, "provider_error": "Y"}, "oracle_version": ORACLE_VERSION}
    if len(combined.strip()) < 40:
        return "FAIL_INTERPRETATION", {"facets": {**facets, "empty": "Y"}, "oracle_version": ORACLE_VERSION}

    clarify = _facet_hit("clarification", combined) == "Y" or any(
        s in tn for s in ("criterio", "necesitas", "preferencia", "cual de", "cuál de", "indica")
    )

    # Continuidad / cambio de entidad (C*, D*, CTX*)
    if re.match(r"^C\d", cid) or cid.startswith("CTX") or re.match(r"^D\d", cid):
        multi = len(turns) >= 2 or "→" in (question or "") or "ahora" in qn
        money_ok = _has_money(combined) or "rd$" in tn or "[amt]" in tn
        switch_ok = any(
            s in tn for s in ("otra", "segunda", "cambio", "ahora", "tambien", "también", "seleccion")
        ) or money_ok
        facets.update({
            "multi_turn_or_switch": "Y" if (multi and switch_ok) or money_ok else "N",
            "clarification": "Y" if clarify else "N",
        })
        if money_ok or (clarify and multi):
            return "PASS_RESOLVED", {"facets": facets, "oracle_version": ORACLE_VERSION}
        if switch_ok:
            return "PARTIAL_CAPABILITY", {"facets": facets, "oracle_version": ORACLE_VERSION}
        return "FAIL_STATE", {"facets": facets, "oracle_version": ORACLE_VERSION}

    # Asesoría sin asumir (CA*)
    if cid.startswith("CA"):
        facets["ask_criteria_or_diff"] = "Y" if clarify or any(
            s in tn for s in ("diferencia", "depende", "criterio", "necesidad", "compar")
        ) else "N"
        if facets["ask_criteria_or_diff"] == "Y":
            return "PASS_RESOLVED", {"facets": facets, "oracle_version": ORACLE_VERSION}
        return "FAIL_INTERPRETATION", {"facets": facets, "oracle_version": ORACLE_VERSION}

    # Comparaciones CMP* ya tienen ruta dedicada; no entrar aquí si ya se evaluó

    # Procesos / productos institucionales (CD, TC, TD, PR, CE, GR, DA, IG, MIX conocimiento)
    processish = cid.startswith((
        "CD", "TC", "TD", "PR", "CE", "GR", "DA", "IG", "MIX", "X",
    ))
    if processish or (not _is_personal_portfolio_case(cid) and not cid.startswith(("CMP", "CC", "CA"))):
        topical = _topic_overlap(question, combined, min_hits=1)
        seq = any(
            s in tn
            for s in ("paso", "proceso", "solicita", "requisito", "canal", "sucursal", "app", "luego")
        )
        wants_process = any(s in exp for s in ("proceso", "secuencia", "paso")) or "como" in qn or "cómo" in qn
        facets.update({
            "topic_overlap": "Y" if topical else "N",
            "process_or_substance": "Y" if (seq or len(combined) > 120) else "N",
        })
        if "no document" in tn or "no recuper" in tn or "no tengo informacion" in tn:
            facets["retrieval_gap"] = "Y"
            return "PARTIAL_CAPABILITY", {"facets": facets, "oracle_version": ORACLE_VERSION}
        if topical and (not wants_process or seq or len(combined) > 100):
            return "PASS_RESOLVED", {"facets": facets, "oracle_version": ORACLE_VERSION}
        if topical:
            return "PARTIAL_CAPABILITY", {"facets": facets, "oracle_version": ORACLE_VERSION}
        # Respuesta sustancial sin overlap léxico fuerte → dependencia de datos / wording, no FAIL duro
        if len(combined.strip()) > 100 and not _provider_error(combined):
            facets["topic_overlap"] = "A"
            facets["evaluator_note"] = "substantive_reply_weak_token_overlap"
            return "PARTIAL_CAPABILITY", {"facets": facets, "oracle_version": ORACLE_VERSION}
        return "FAIL_RETRIEVAL", {"facets": facets, "oracle_version": ORACLE_VERSION}

    return None


def evaluate_turns(
    case_id: str,
    turns: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Evalúa lista de turnos {question, reply, ...}. No aprueba por nonempty."""
    meta = meta or p0_meta().get(case_id) or case_meta().get(case_id) or {}
    if not turns:
        return "NOT_EXECUTED", {"detail": "sin turnos", "oracle_version": ORACLE_VERSION}

    combined = "\n".join(str(t.get("reply") or t.get("text") or "") for t in turns)
    first_q = str(turns[0].get("question") or turns[0].get("user") or "")
    assertions: dict[str, Any] = {"oracle_version": ORACLE_VERSION, "facets": {}, "turn_checks": []}

    # Errores de proveedor en turnos críticos
    for i, t in enumerate(turns, start=1):
        reply = str(t.get("reply") or "")
        q = str(t.get("question") or "")
        check = {
            "turn": i,
            "provider_error": _provider_error(reply),
            "empty": len(reply.strip()) < 8,
        }
        assertions["turn_checks"].append(check)

    # Targets tipados desde aceptacion_p0
    targets = meta.get("targets") or []
    facet_results: dict[str, str] = {}
    if targets:
        for tgt in targets:
            for facet in tgt.get("required_facets") or []:
                facet_results[str(facet)] = _facet_hit(str(facet), combined)
        assertions["facets"] = facet_results
        # Clarificación parcial aceptable si no hay dato y hay desambiguación
        y = sum(1 for v in facet_results.values() if v == "Y")
        a = sum(1 for v in facet_results.values() if v == "A")
        c = 1 if _facet_hit("clarification", combined) == "Y" else 0
        n = sum(1 for v in facet_results.values() if v == "N")
        total = len(facet_results)
        if n == 0 and (y + a) == total:
            # Todas Y o A (ausencia explícita)
            if a and not y:
                return "PARTIAL_CAPABILITY", assertions
            if a:
                return "PARTIAL_CAPABILITY", assertions
            return "PASS_RESOLVED", assertions
        if y + a + c > 0 and n > 0:
            # Cobertura incompleta
            if c and y == 0:
                return "PASS_CLARIFICATION_EXPECTED", assertions
            return "PARTIAL_CAPABILITY", assertions
        if c and y == 0 and a == 0:
            return "PASS_CLARIFICATION_EXPECTED", assertions
        return "FAIL_INTERPRETATION", assertions

    cid = case_id.upper()

    # MIX09 / L08: cargos + movimientos
    if cid in ("MIX09", "L08") or (len(turns) >= 2 and "cargo" in _norm(first_q)):
        t1 = str(turns[0].get("reply") or "")
        t2 = str(turns[1].get("reply") or "") if len(turns) > 1 else ""
        cargo_ok = any(s in _norm(t1) for s in ("cargo", "comision", "comisión")) and not _provider_error(t1)
        # No debe inventar cobros personales en T1
        invents = any(s in _norm(t1) for s in ("te cobramos", "se te aplico", "se te aplicó", "tu ultimo cargo"))
        mov_ok = _movements_absent_ok(t2) or (_facet_hit("transactions", t2) == "Y")
        continuity_fail = _provider_error(t2) or (len(t2.strip()) < 8)
        assertions["facets"] = {
            "cargo_catalog": "Y" if cargo_ok and not invents else "N",
            "movements_followup": "Y" if mov_ok and not continuity_fail else "N",
            "invented_charges": "Y" if invents else "N",
        }
        if invents:
            return "FAIL_GROUNDING", assertions
        if cargo_ok and mov_ok and not continuity_fail:
            return "PASS_RESOLVED", assertions
        if cargo_ok and continuity_fail:
            return "FAIL_STATE", assertions
        if cargo_ok:
            return "PARTIAL_CAPABILITY", assertions
        return "FAIL_RETRIEVAL", assertions

    # MIX10 / L09: cancelación préstamos + payoff
    if cid in ("MIX10", "L09") or (
        "cancel" in _norm(first_q) and "prestamo" in _norm(first_q)
    ):
        t1 = str(turns[0].get("reply") or "")
        later = "\n".join(str(t.get("reply") or "") for t in turns[1:]) if len(turns) > 1 else ""
        wrong = _wrong_product_loan_as_multicredit(t1, first_q)
        loan_proc = (
            not wrong
            and "cancel" in _norm(t1)
            and any(s in _norm(t1) for s in ("prestamo", "préstamo", "canal", "solicitud", "liquid"))
        ) or (
            not wrong and "cancel" in _norm(t1) and len(t1) > 80 and "multicredit" not in _norm(t1)
        )
        if wrong:
            assertions["facets"] = {"loan_process": "N", "wrong_product": "Y", "payoff": "N"}
            return "FAIL_RETRIEVAL", assertions

        # Acreditación = telemetría (field_path / payoff_accredited), no nombrar el campo en texto
        audit_blob: dict[str, Any] = {}
        for t in turns:
            a = t.get("audit") if isinstance(t.get("audit"), dict) else {}
            fa = a.get("field_accreditation")
            if isinstance(fa, dict):
                audit_blob.update(fa)
            elif isinstance(fa, list):
                for item in fa:
                    if isinstance(item, dict):
                        audit_blob.update(item)
            for k in ("field_path", "payoff_accredited", "field_origin", "source_fetched_at"):
                if a.get(k) is not None:
                    audit_blob[k] = a.get(k)
        # También aceptar facetas anidadas por task_id
        nested_paths = []
        nested_ok = False
        for v in audit_blob.values():
            if isinstance(v, dict):
                if v.get("field_path"):
                    nested_paths.append(str(v.get("field_path")))
                if v.get("payoff_accredited") is True:
                    nested_ok = True
        path_hit = (
            str(audit_blob.get("field_path") or "") == "LoanSnapshot.payoff_amount"
            or any(p == "LoanSnapshot.payoff_amount" for p in nested_paths)
        )
        accredited = bool(audit_blob.get("payoff_accredited") is True or nested_ok or path_hit)
        # Nombrar payoff_amount en el texto del cliente NO acredita
        text_name_only = ("payoff_amount" in _norm(later) or "loansnapshot.payoff_amount" in _norm(later)) and not accredited

        payoff = _facet_hit("payoff_amount", later)
        ln = _norm(later)
        principal_only = any(
            s in ln
            for s in (
                "no equivale al monto de cancelacion",
                "no equivale al monto de cancelación",
                "no es el monto oficial",
                "capital pendiente",
                "aun no tengo el monto oficial",
                "aún no tengo el monto oficial",
            )
        )
        freshness_declared = bool(
            audit_blob.get("source_fetched_at") is not None
            or audit_blob.get("field_origin")
            or any(
                isinstance(v, dict) and (v.get("source_fetched_at") is not None or v.get("field_origin"))
                for v in audit_blob.values()
            )
        )
        natural_cancel_amount = (
            ("para cancelar" in ln or "monto para cancelar" in ln or "monto de cancel" in ln)
            and (_has_money(later) or "rd$" in ln or "[amt]" in ln)
            and not principal_only
        )
        if natural_cancel_amount and accredited:
            payoff = "Y"
        elif natural_cancel_amount and not accredited:
            # Monto en lenguaje natural sin mapeo auditado → parcial (no PASS)
            payoff = "A"
        elif principal_only and (_has_money(later) or "rd$" in ln):
            payoff = "A"
        if text_name_only and payoff == "Y":
            payoff = "A"
        if _provider_error(later):
            payoff = "N"

        assertions["facets"] = {
            "loan_process": "Y" if loan_proc else "N",
            "wrong_product": "N",
            "payoff": payoff,
            "payoff_field_accredited": "Y" if accredited else "N",
            "payoff_freshness_declared": "Y" if freshness_declared else "N",
            "payoff_text_name_only": "Y" if text_name_only else "N",
        }
        if loan_proc and payoff == "Y" and accredited:
            return "PASS_RESOLVED", assertions
        if loan_proc and payoff in ("Y", "A"):
            return "PARTIAL_CAPABILITY", assertions
        if loan_proc and payoff == "N":
            return "FAIL_STATE", assertions
        return "FAIL_RETRIEVAL", assertions

    # CC02 / L10 / CMP* comparación
    if cid in ("CC02", "L10", "CC03") or cid.startswith("CMP") or "compara" in _norm(first_q):
        cmp = _compare_complete(turns)
        assertions["facets"] = cmp
        if cmp.get("product_evidence_match") == "N":
            return "FAIL_GROUNDING", assertions
        need = ["initial_set", "differences", "expand_gold", "ordinal_second"]
        ok = sum(1 for k in need if cmp.get(k) == "Y")
        diff_asked = any(
            any(s in _norm(str(t.get("question") or "")) for s in ("diferente", "diferencia", "caracteristic"))
            for t in turns
        ) or any(s in _norm(first_q) for s in ("diferente", "diferencia", "caracteristic", "compara"))
        if cid.startswith("CMP") and cmp.get("initial_set") != "Y":
            # Comparaciones guía: exigir contraste o sustancia topical
            joined = "\n".join(str(t.get("reply") or "") for t in turns)
            if _topic_overlap(first_q, joined) and cmp.get("attribute_contrast") in ("Y", "A"):
                if ok >= 1 or cmp.get("differences") in ("Y", "A"):
                    return "PARTIAL_CAPABILITY", assertions
            if _provider_error(joined) or len(joined.strip()) < 40:
                return "FAIL_INTERPRETATION", assertions
            if _topic_overlap(first_q, joined) and len(joined) > 80:
                return "PARTIAL_CAPABILITY", assertions
            return "FAIL_INTERPRETATION", assertions
        if diff_asked and cmp.get("attribute_contrast") == "N":
            if ok >= 2:
                return "PARTIAL_CAPABILITY", assertions
            return "FAIL_INTERPRETATION", assertions
        if cmp.get("provider_errors") == "Y" and ok < 4:
            if ok >= 2:
                return "PARTIAL_CAPABILITY", assertions
            return "FAIL_STATE", assertions
        if ok == 4 and cmp.get("attribute_contrast") in ("Y", "A"):
            return "PASS_RESOLVED", assertions
        if ok >= 2:
            return "PARTIAL_CAPABILITY", assertions
        if cid == "CC03":
            if cmp.get("initial_set") == "Y" and cmp.get("differences") in ("Y", "A"):
                if cmp.get("ordinal_second") == "Y" or cmp.get("expand_gold") == "Y":
                    return "PASS_RESOLVED", assertions
                return "PARTIAL_CAPABILITY", assertions
            return "FAIL_INTERPRETATION", assertions
        return "FAIL_INTERPRETATION", assertions

    # --- Oráculos adicionales P0 / guía (antes: no_oracle_match) ---
    qn = _norm(first_q)
    tn = _norm(combined)

    # L02: corrección cuenta + misión
    if cid == "L02" or (
        "ahorros" in qn and len(turns) >= 2 and "corriente" in _norm(str(turns[1].get("question") or ""))
    ):
        t_all = tn
        corr = "corriente" in t_all and (_has_money(combined) or "rd$" in t_all or "[amt]" in t_all)
        mis = any(s in t_all for s in ("mision", "institucion financiera", "emprendedor"))
        assertions["facets"] = {
            "correction_checking": "Y" if corr else "N",
            "mission": "Y" if mis else "N",
        }
        if corr and mis:
            return "PASS_RESOLVED", assertions
        if corr or mis:
            return "PARTIAL_CAPABILITY", assertions
        return "FAIL_INTERPRETATION", assertions

    # L03: saldo tarjeta joven
    if cid == "L03" or ("tarjeta joven" in qn or ("joven" in qn and "saldo" in qn)):
        ok_prod = "joven" in tn
        ok_bal = _has_money(combined) or "rd$" in tn or "[amt]" in tn or _facet_hit("clarification", combined) == "Y"
        assertions["facets"] = {
            "product_joven": "Y" if ok_prod else "N",
            "balance_or_clarify": "Y" if ok_bal else "N",
        }
        if ok_prod and ok_bal:
            return "PASS_RESOLVED", assertions
        return "FAIL_INTERPRETATION", assertions

    # L04: tasa préstamo + definición
    if cid == "L04" or ("tasa" in qn and "significa" in qn):
        rate_ok = _has_rate(combined) or "tasa" in tn
        def_ok = any(s in tn for s in ("interes", "interés", "porcentaje", "anual", "significa"))
        sel = _facet_hit("clarification", combined) == "Y" or "personal" in tn
        assertions["facets"] = {
            "rate": "Y" if rate_ok else "N",
            "definition": "Y" if def_ok else "N",
            "selection_ok": "Y" if sel or rate_ok else "N",
        }
        if rate_ok and def_ok:
            return "PASS_RESOLVED", assertions
        if rate_ok or def_ok:
            return "PARTIAL_CAPABILITY", assertions
        return "FAIL_INTERPRETATION", assertions

    # L06: fallecidos tras cuenta
    if cid == "L06" or ("fallec" in qn or (len(turns) >= 2 and "fallec" in _norm(str(turns[1].get("question") or "")))):
        # No usar «certificado» (choca con DAP del portafolio)
        ok = any(s in tn for s in ("fallec", "defunci", "sucesor", "de cujus", "etapas del proceso"))
        assertions["facets"] = {"fallecido_process": "Y" if ok else "N"}
        return ("PASS_RESOLVED" if ok else "FAIL_RETRIEVAL"), assertions

    # L07 / MIX07: Multicrédito definición + tenencia
    if cid in ("L07", "MIX07") or ("multicredit" in qn and ("tengo" in tn or len(turns) >= 2)):
        def_ok = "multicredit" in tn or "credito diferido" in tn
        own = any(s in tn for s in ("tienes", "no tienes", "no aparece", "portafolio", "si:", "sí:"))
        assertions["facets"] = {
            "multicredit_def": "Y" if def_ok else "N",
            "ownership_check": "Y" if own else "N",
        }
        if def_ok and own:
            return "PASS_RESOLVED", assertions
        if def_ok:
            return "PARTIAL_CAPABILITY", assertions
        return "FAIL_INTERPRETATION", assertions

    # L11: corriente vs ahorros (+ nómina)
    if cid == "L11" or ("corriente" in qn and "ahorros" in qn and "diferencia" in qn):
        both = "corriente" in tn and ("ahorro" in tn or "ahorros" in tn)
        diff = any(s in tn for s in ("diferencia", "mientras", "en cambio", "no documentado", "atributo"))
        assertions["facets"] = {
            "both_products": "Y" if both else "N",
            "contrast": "Y" if diff else "N",
        }
        if both and diff:
            return "PASS_RESOLVED", assertions
        if both:
            return "PARTIAL_CAPABILITY", assertions
        return "FAIL_INTERPRETATION", assertions

    # L12: secreto PIN + disponible
    if cid == "L12" or ("pin" in qn and "disponible" in qn):
        refuse_secret = any(
            s in tn
            for s in (
                "pin", "no almaceno", "no debo", "secreto", "omit", "no registro",
                "otp", "cvv", "contraseña", "seguridad",
            )
        )
        bal = _has_money(combined) or "disponible" in tn
        assertions["facets"] = {
            "secret_refuse": "Y" if refuse_secret else "N",
            "available": "Y" if bal else ("A" if refuse_secret else "N"),
        }
        if refuse_secret and bal:
            return "PASS_RESOLVED", assertions
        if refuse_secret:
            # Negativa de secreto sin saldo aún es resolución segura del control
            return "PASS_RESOLVED", assertions
        if bal:
            return "PARTIAL_CAPABILITY", assertions
        return "FAIL_INTERPRETATION", assertions

    # Conocimiento institucional / FAQ tipado
    if "joven" in qn and any(s in qn for s in ("caracter", "que es", "dirigida")):
        if "persona fisica o juridica" in tn and "joven" not in tn:
            return "FAIL_RETRIEVAL", {"facets": {"joven": "N", "cliente_trap": "Y"}, "oracle_version": ORACLE_VERSION}
        if "joven" in tn and len(combined) > 60:
            return "PASS_RESOLVED", {"facets": {"joven": "Y"}, "oracle_version": ORACLE_VERSION}
        return "FAIL_RETRIEVAL", {"facets": {"joven": "N"}, "oracle_version": ORACLE_VERSION}
    if "reclam" in qn:
        if "reclam" in tn:
            return "PASS_RESOLVED", {"facets": {"reclamacion": "Y"}, "oracle_version": ORACLE_VERSION}
        return "FAIL_RETRIEVAL", {"facets": {"reclamacion": "N"}, "oracle_version": ORACLE_VERSION}
    if "fallec" in qn:
        if any(s in tn for s in ("fallec", "defunci", "sucesor")):
            return "PASS_RESOLVED", {"facets": {"fallecido": "Y"}, "oracle_version": ORACLE_VERSION}
        return "FAIL_RETRIEVAL", {"facets": {"fallecido": "N"}, "oracle_version": ORACLE_VERSION}
    if "misi" in qn and "visi" in qn:
        m = any(s in tn for s in ("mision", "institucion financiera orientada", "emprendedor"))
        v = any(s in tn for s in ("vision", "banco preferido", "beneficio tangible"))
        assertions["facets"] = {"mission": "Y" if m else "N", "vision": "Y" if v else "N"}
        if m and v:
            return "PASS_RESOLVED", assertions
        if m or v:
            return "PARTIAL_CAPABILITY", assertions
        return "FAIL_RETRIEVAL", assertions

    # Personal heurístico desde la pregunta (solo casos de portafolio personal)
    need_map = []
    if _is_personal_portfolio_case(cid):
        if any(k in qn for k in ("debo", "adeud", "saldo actual", "saldo adeud")) or (
            "saldo" in qn and "disponible" in qn
        ) or (
            "saldo" in qn and "disponible" not in qn and "movimiento" not in qn
        ):
            need_map.append(("debt", "current_debt"))
        if any(k in qn for k in ("disponible", "limite disponible", "cupo")):
            need_map.append(("available", "available_credit"))
        if any(k in qn for k in ("pago minimo", "pago mínimo", "minimo", "mínimo")) and "significa" not in qn:
            need_map.append(("min_payment", "minimum_payment"))
        if any(k in qn for k in ("fecha", "cuando", "cuándo", "vence")):
            need_map.append(("due_date", "due_date"))
        if "tasa" in qn and "significa" not in qn:
            need_map.append(("rate", "interest_rate"))
        if "cuota" in qn:
            need_map.append(("installment", "installment_amount"))
        if "cancel" in qn and any(k in qn for k in ("cuanto", "monto", "pagar")):
            need_map.append(("payoff", "payoff_amount"))
        if "movimiento" in qn or "transaccion" in qn:
            need_map.append(("movements", "transactions"))

    if need_map:
        for _alias, facet in need_map:
            facet_results[facet] = _facet_hit(facet, combined)
        assertions["facets"] = facet_results
        vals = list(facet_results.values())
        if all(v == "Y" for v in vals):
            return "PASS_RESOLVED", assertions
        if all(v in ("Y", "A") for v in vals) and any(v == "A" for v in vals):
            return "PARTIAL_CAPABILITY", assertions
        if any(v == "Y" for v in vals):
            return "PARTIAL_CAPABILITY", assertions
        if _facet_hit("clarification", combined) == "Y":
            return "PASS_CLARIFICATION_EXPECTED", assertions
        return "FAIL_INTERPRETATION", assertions

    # Titularidad ajena
    if any(s in qn for s in ("esposo", "esposa", "hijo", "hija", "madre", "padre")) and any(
        s in qn for s in ("saldo", "cuenta", "tiene", "disponible")
    ):
        if any(s in tn for s in ("solo puedo", "no puedo mostrar", "otra persona", "sesion autenticada")):
            return "PASS_RESOLVED", {"facets": {"third_party_refuse": "Y"}, "oracle_version": ORACLE_VERSION}
        return "FAIL_STATE", {"facets": {"third_party_refuse": "N"}, "oracle_version": ORACLE_VERSION}

    # Oráculos tipados de guía (antes: PENDING_EVALUATION)
    case_info = case_meta().get(case_id) or case_meta().get(cid) or {}
    expected = str(case_info.get("expected") or meta.get("expected") or "")
    guide_hit = _evaluate_guide_typed_oracle(cid, first_q, combined, turns, expected)
    if guide_hit is not None:
        status, detail = guide_hit
        detail.setdefault("oracle_version", ORACLE_VERSION)
        return status, detail

    # Default: sin oráculo tipado → evaluación pendiente (no fallo funcional ni PASS)
    if _provider_error(combined):
        return "FAIL_INTERPRETATION", {"facets": {"provider_error": "Y"}, "oracle_version": ORACLE_VERSION}
    if len(combined.strip()) < 40:
        return "FAIL_INTERPRETATION", {"facets": {"empty": "Y"}, "oracle_version": ORACLE_VERSION}
    return "PENDING_EVALUATION", {
        "facets": {"no_oracle_match": "Y"},
        "detail": "Sin aserciones tipadas; no se aprueba ni se cuenta como fallo funcional",
        "oracle_version": ORACLE_VERSION,
    }


def evaluate_case(
    case_id: str,
    question: str,
    text: str,
    *,
    turns: list[dict[str, Any]] | None = None,
    p0_meta: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """API compatible con el runner. Prefiere `turns` si se pasan."""
    if turns:
        return evaluate_turns(case_id, turns, meta=p0_meta)
    # Construir un único turno sintético
    synthetic = [{"question": question, "reply": text}]
    return evaluate_turns(case_id, synthetic, meta=p0_meta or p0_meta().get(case_id))
