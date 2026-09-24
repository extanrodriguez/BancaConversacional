"""Follow-ups cortos de conocimiento: conservar tema KB y ampliar la pregunta.

Ejemplos:
  last_knowledge_topic = "Cuenta de ahorro"
  "como se usa" → "como se usa Cuenta de ahorro"

  last_knowledge_topic = "… mi responsabilidad"
  "y la del banco" → "responsabilidad del banco"
"""

from __future__ import annotations

import os
import re
from typing import Any


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def confidence_gate_enabled() -> bool:
    """GENESIS_KB_CONFIDENCE_GATE — OFF por defecto (local); ON en QA 8447."""
    return _env_flag("GENESIS_KB_CONFIDENCE_GATE")


def _fold_accents(text: str) -> str:
    t = (text or "").lower()
    for src, dst in (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n"),
    ):
        t = t.replace(src, dst)
    return t


def is_kb_product_compare_question(text: str) -> bool:
    """Comparación institucional (crédito vs débito, Multicrédito vs Cuotas, etc.)."""
    q = _fold_accents(text)
    if not q:
        return False
    has_compare = any(
        s in q
        for s in ("compar", "diferenc", "disting", "versus", " vs ", " frente a ", " entre ")
    )
    if not has_compare:
        return False
    multicredit_cuotas = ("multicredit" in q) and ("cuotas" in q)
    credito_debito = (
        ("credito" in q)
        and ("debito" in q)
        and any(s in q for s in ("tarjeta", "plastico", "plástico", "compar", "diferenc", "entre"))
    )
    return multicredit_cuotas or credito_debito


# Intenciones de detalle: si el FAQ es flojo, preferir Foundry
_DETAIL_QUESTION_KEYS = (
    "requisito",
    "document",
    "cedula",
    "pasaporte",
    "papeles",
    "cargo",
    "comision",
    "comisión",
    "tarifa",
    "costo",
    "cobran",
    "cancel",
    "baja",
    "solicito",
    "solicitar",
    "proceso",
    "pido",
    "contratar",
    "efectivo",
    "avance",
    "consumo",
    "minimo de consumo",
    "mínimo de consumo",
    "beneficio",
    "derecho",
    "entregar",
    "documentacion",
    "documentación",
    "conversion",
    "conversión",
    "internacional",
    "roban",
    "pierdo",
    "robo",
    "plastico",
    "plástico",
    "pagan",
    "pagos",
    "como se pagan",
    "cómo se pagan",
    "diferenc",
    "disting",
    "compar",
)


def question_wants_detail(question: str) -> bool:
    q = _norm_q(question)
    return any(k in q for k in _DETAIL_QUESTION_KEYS)

# Preguntas ambiguas que dependen del tema KB previo (no del portafolio personal)
_KB_FOLLOWUP_PATTERNS = (
    r"^como se usa\??$",
    r"^cómo se usa\??$",
    r"^como funciona\??$",
    r"^cómo funciona\??$",
    r"^y eso\??$",
    r"^y eso como\b",
    r"^para que sirve\??$",
    r"^para qué sirve\??$",
    r"^mas info\??$",
    r"^más info\??$",
    r"^mas informacion\??$",
    r"^más información\??$",
    r"^dame mas\??$",
    r"^dame más\??$",
    r"^y el proceso\??$",
    r"^el proceso\??$",
    r"^y los requisitos\??$",
    r"^los requisitos\??$",
    r"^que requisitos\b",
    r"^qué requisitos\b",
    r"^y las condiciones\??$",
    r"^y la del banco\??$",
    r"^y las del banco\??$",
    r"^cual es la del banco\??$",
    r"^cuál es la del banco\??$",
    r"^la del banco\??$",
    r"^las del banco\??$",
    r"^y la mia\??$",
    r"^y la mía\??$",
    r"^y las mias\??$",
    r"^y las mías\??$",
    # Guía CTX / CC — follow-ups de conocimiento
    r"^y que requisitos\b",
    r"^y qué requisitos\b",
    r"^como lo solicito\??$",
    r"^cómo lo solicito\??$",
    r"^tiene cargos\??$",
    r"^y como lo cancelo\??$",
    r"^y cómo lo cancelo\??$",
    r"^cual es el consumo minimo\??$",
    r"^cuál es el consumo mínimo\??$",
    r"^puedo sacar efectivo\??$",
    r"^tiene algun cargo\b",
    r"^tiene algún cargo\b",
    r"^y si pierdo\b",
    r"^y la fecha limite\??$",
    r"^y la fecha límite\??$",
    r"^cual ocurre primero\??$",
    r"^cuál ocurre primero\??$",
    r"^que pasa si pago\b",
    r"^qué pasa si pago\b",
    r"^que informacion debo\b",
    r"^qué información debo\b",
    r"^cuales son mis derechos\b",
    r"^cuáles son mis derechos\b",
    r"^cual es la principal diferencia\??$",
    r"^cuál es la principal diferencia\??$",
    r"^y en cuanto a los pagos\??$",
    r"^cual de los dos\b",
    r"^cuál de los dos\b",
    r"^como cancelo el primero\??$",
    r"^cómo cancelo el primero\??$",
    r"^y el segundo\??$",
    r"^y el primero\??$",
    r"^y la otra\??$",
    r"^y como funciona la otra\??$",
    r"^y cómo funciona la otra\??$",
    r"^que cargos puede tener\b",
    r"^qué cargos puede tener\b",
    r"^que cargos puede tener esa\??$",
    r"^qué cargos puede tener esa\??$",
    r"^no,? me referia\b",
    r"^no,? me refería\b",
    r"^no,? me referia a la primera\??$",
    r"^no,? me refería a la primera\??$",
    r"^que beneficios tiene\??$",
    r"^qué beneficios tiene\??$",
    r"^y que la diferencia\b",
    r"^y qué la diferencia\b",
    # Coloquial guía
    r"^que papeles piden\??$",
    r"^qué papeles piden\??$",
    r"^como lo pido\??$",
    r"^cómo lo pido\??$",
    r"^y cuanto me cobran\??$",
    r"^y cuánto me cobran\??$",
    r"^cuanto me cobran\??$",
    r"^cuánto me cobran\??$",
    r"^como lo doy de baja\??$",
    r"^cómo lo doy de baja\??$",
    r"^dime el minimo de consumo\??$",
    r"^dime el mínimo de consumo\??$",
    r"^que los distingue\??$",
    r"^qué los distingue\??$",
    r"^quien tiene consumo\b",
    r"^quién tiene consumo\b",
    r"^cual viene antes\??$",
    r"^cuál viene antes\??$",
    r"^si me atraso\b",
    r"^que hago si me roban\b",
    r"^qué hago si me roban\b",
    r"^y cancelar\b",
    r"^cancelacion del\b",
    r"^cancelación del\b",
    r"^procedimiento de cancelacion\b",
    r"^procedimiento de cancelación\b",
    r"^cual es el procedimiento de cancelacion\b",
    r"^cuál es el procedimiento de cancelación\b",
    r"^se puede hacer avance\b",
    r"^puedo hacer avance\b",
    r"^avance de efectivo\b",
    r"^que comisiones tiene el avance\b",
    r"^qué comisiones tiene el avance\b",
    r"^como se pagan\b",
    r"^cómo se pagan\b",
)

_KB_TOPIC_ESCAPE = (
    "mi saldo",
    "mis productos",
    "mi prestamo",
    "mi préstamo",
    "mi tarjeta",
    "mis tarjetas",
    "mi cuenta",
    "terminad",
    "el mio",
    "el mío",
    "la mia cuanto",
    "y el mio",
    "y el mío",
    "y el mío,",
)


def _norm_q(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[¿?¡!]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def has_knowledge_session(session: Any | None) -> bool:
    topic = getattr(session, "last_knowledge_topic", None) if session is not None else None
    if not topic:
        return False
    t = str(topic).strip().upper()
    return t not in ("KB_AMBIGUITY", "RECLAMACION_CHANNEL")


def is_knowledge_followup(text: str) -> bool:
    """True si el mensaje parece un follow-up corto al tema KB previo."""
    q = _norm_q(text)
    if not q or len(q) > 90:
        return False
    if any(s in q for s in _KB_TOPIC_ESCAPE):
        return False
    # Fecha de pago personal ≠ follow-up de glosario KB
    try:
        from genesis_cognitive.router.field_guardrails import is_personal_payment_date_question

        if is_personal_payment_date_question(text):
            return False
    except Exception:
        pass
    if any(re.search(p, q) for p in _KB_FOLLOWUP_PATTERNS):
        return True
    # Frases cortas genéricas de uso / detalle / comparación
    toks = q.split()
    if len(toks) <= 8 and any(
        s in q
        for s in (
            "como se usa",
            "cómo se usa",
            "como funciona",
            "cómo funciona",
            "del banco",
            "para que sirve",
            "para qué sirve",
            "requisito",
            "consumo minimo",
            "consumo mínimo",
            "minimo de consumo",
            "mínimo de consumo",
            "sacar efectivo",
            "fecha limite",
            "fecha límite",
            "el primero",
            "el segundo",
            "la primera",
            "la segunda",
            "la otra",
            "la anterior",
            "me referia",
            "me refería",
            "dinero de mi cuenta",
            "usa directamente",
            "principal diferencia",
            "en cuanto a",
            "si pierdo",
            "si me roban",
            "si pago despues",
            "si pago después",
            "si me atraso",
            "debo entregar",
            "mis derechos",
            "beneficios tiene",
            "cargos",
            "me cobran",
            "papeles",
            "doy de baja",
            "como lo pido",
            "cómo lo pido",
            "como lo cancelo",
            "cómo lo cancelo",
            "como lo solicito",
            "cómo lo solicito",
            "viene antes",
            "los distingue",
        )
    ):
        return True
    return False


def is_bank_responsibility_question(text: str) -> bool:
    q = _norm_q(text)
    if not q:
        return False
    if any(s in q for s in ("mi responsabilidad", "mis responsabilidad", "como cliente", "como usuario")):
        # "mi" explícito → cliente, salvo contraste "banco y la mía"
        if not any(s in q for s in ("del banco", "el banco", "banco y")):
            return False
    return any(
        s in q
        for s in (
            "responsabilidad del banco",
            "responsabilidades del banco",
            "la del banco",
            "las del banco",
            "obligacion del banco",
            "obligación del banco",
            "obligaciones del banco",
            "deberes del banco",
            "que debe el banco",
            "qué debe el banco",
        )
    )


def is_client_responsibility_question(text: str) -> bool:
    q = _norm_q(text)
    if is_bank_responsibility_question(text) and "mi " not in f" {q} " and "mis " not in f" {q} ":
        return False
    return any(
        s in q
        for s in (
            "mi responsabilidad",
            "mis responsabilidad",
            "mis obligaciones",
            "mi obligacion",
            "mi obligación",
            "como cliente",
            "como usuario",
            "la mia",
            "la mía",
            "las mias",
            "las mías",
        )
    )


def should_prefer_foundry_over_faq(question: str, answer: str) -> bool:
    """True cuando el follow-up pide un detalle y el FAQ solo devolvió la ficha genérica."""
    q = _norm_q(question)
    a = (answer or "").lower()
    if not q or not a:
        return False
    # Respuestas meta de matriz
    if any(s in a for s in ("la ia cambia", "deja de utilizar el anterior", "validación esperada", "validacion esperada")):
        return True
    checks = (
        (("requisito", "document", "cedula", "pasaporte", "papeles"), ("requisito", "document", "cédula", "cedula", "pasaporte", "presentar", "papel")),
        (("cargo", "comision", "comisión", "tarifa", "costo", "cobran"), ("cargo", "comision", "comisión", "tarifa", "costo", "cobro")),
        (("cancel", "baja"), ("cancel", "bloquear", "solicitud de cancel", "baja")),
        (("solicito", "solicitar", "proceso", "pido", "contratar"), ("solicitar", "solicitud", "proceso", "canal", "contratar", "digital", "centro")),
        (("efectivo", "avance"), ("efectivo", "avance")),
        (("consumo", "minimo de consumo", "mínimo de consumo"), ("consumo", "minimo", "mínimo", "rd")),
        (("beneficio",), ("beneficio", "ventaja", "puntos", "cashback")),
        (("derecho",), ("derecho", "obligacion", "obligación")),
        (("entregar", "documentacion", "documentación", "informacion debo", "información debo"), ("document", "factura", "constancia", "soporte", "presentar")),
        (("conversion", "conversión", "internacional"), ("conversion", "conversión", "visa", "moneda", "internacional")),
        (("roban", "pierdo", "robo", "plastico", "plástico"), ("pierd", "robo", "bloque", "report", "seguridad", "extrav")),
        (("pagan", "pagos", "como se pagan", "cómo se pagan"), ("pago", "cuota", "amortiz", "vencim")),
        (("diferenc", "disting", "compar"), ("diferenc", "disting", "frente", "mientras", "mientras que", "en cambio")),
    )
    for q_keys, a_keys in checks:
        if any(k in q for k in q_keys) and not any(k in a for k in a_keys):
            return True
    return False


def prefer_foundry_for_faq_hit(
    question: str,
    answer: str | None,
    *,
    score: float | None = None,
) -> bool:
    """Puerta de confianza FAQ → Foundry.

    Siempre aplica cobertura de intención (should_prefer_foundry_over_faq).
    Con GENESIS_KB_CONFIDENCE_GATE=1 también cede si el score es débil
    o está bajo HIGH_SCORE en preguntas de detalle.
    """
    if not (answer or "").strip():
        return True
    if should_prefer_foundry_over_faq(question, answer or ""):
        return True
    if not confidence_gate_enabled():
        return False
    high = _env_float("GENESIS_FAQ_HIGH_SCORE", 0.90)
    gray_min = _env_float("GENESIS_FAQ_GRAY_MIN", 0.55)
    if score is None:
        return False
    if score < gray_min:
        return True
    if score < high and question_wants_detail(question):
        return True
    return False


def expand_knowledge_question(question: str, session: Any | None) -> str:
    """Amplía la pregunta con last_knowledge_topic cuando hay follow-up corto."""
    q = (question or "").strip()
    if not q or session is None:
        return q
    topic = getattr(session, "last_knowledge_topic", None)
    if not topic or not is_knowledge_followup(q):
        # Responsabilidad del banco aunque no sea follow-up corto
        if is_bank_responsibility_question(q):
            return q
        return q

    topic_s = str(topic).strip()
    if topic_s.upper() in ("KB_AMBIGUITY", "RECLAMACION_CHANNEL"):
        return q
    ql = _norm_q(q)
    topic_l = topic_s.lower()

    # Contraste responsabilidad → reescribir a pregunta explícita
    if any(s in ql for s in ("del banco", "la del banco", "las del banco")):
        if any(s in topic_l for s in ("responsab", "derecho", "obligacion", "obligación", "deber")):
            return "cuál es la responsabilidad del banco como institución"
        return f"{q} {topic_s}"

    if any(s in ql for s in ("la mia", "la mía", "las mias", "las mías", "como cliente")):
        return "cuál es mi responsabilidad como cliente"

    # Comparaciones: primero / segundo / otra / corrección "me refería a…"
    # (antes de "cómo funciona" genérico, para no tragar "cómo funciona la otra")
    _cred_deb = (
        ("credito" in topic_l or "crédito" in topic_l)
        and ("debito" in topic_l or "débito" in topic_l)
    )
    if "me referia" in ql or "me refería" in ql:
        if _cred_deb and any(s in ql for s in ("primera", "primero")):
            return (
                "qué cargos o comisiones tiene la tarjeta de débito "
                "(cargo a la cuenta asociada, no línea de crédito)"
            )
        if _cred_deb and any(s in ql for s in ("segunda", "segundo", "otra")):
            return "qué cargos o comisiones tiene la tarjeta de crédito"
        if "primera" in ql or "primero" in ql:
            return f"detalle del primero de: {topic_s} (cargos/comisiones si aplica)"
        if "segunda" in ql or "segundo" in ql or "otra" in ql:
            return f"detalle del segundo de: {topic_s} (cargos/comisiones si aplica)"

    if "el primero" in ql or "la primera" in ql:
        if _cred_deb:
            return (
                "qué cargos o comisiones tiene la tarjeta de débito "
                "(la primera del contraste crédito/débito según corrección del hilo)"
            )
        if "cancel" in ql:
            return f"cómo cancelo el primero de: {topic_s}"
        return f"{q} (refiriéndome al primero de: {topic_s})"
    if "el segundo" in ql or "la segunda" in ql:
        if _cred_deb:
            return "qué cargos o comisiones tiene la tarjeta de crédito"
        return f"{q} (refiriéndome al segundo de: {topic_s})"
    if "la anterior" in ql or "la otra" in ql:
        if _cred_deb:
            if any(s in ql for s in ("como funciona", "cómo funciona", "funciona")):
                return "cómo funciona la tarjeta de crédito (frente a la de débito)"
            if any(s in ql for s in ("cargo", "comision", "comisión")):
                return "qué cargos o comisiones puede tener la tarjeta de crédito"
            return "información de la tarjeta de crédito (la otra frente al débito)"
        return f"{q} en el contexto de {topic_s}"

    if any(s in ql for s in ("esa", "tiene esa")) and _cred_deb:
        if any(s in ql for s in ("cargo", "comision", "comisión")):
            return "qué cargos o comisiones puede tener la tarjeta de crédito"
        return f"{q} (tarjeta de crédito en {topic_s})"

    if _cred_deb and any(
        s in ql
        for s in (
            "dinero de mi cuenta",
            "usa directamente",
            "fondos de la cuenta",
            "de mi cuenta",
        )
    ):
        return (
            "cuál usa directamente el dinero de la cuenta bancaria: "
            "la tarjeta de débito (no la de crédito)"
        )

    if any(s in ql for s in ("como se usa", "cómo se usa", "como funciona", "cómo funciona", "para que sirve", "para qué sirve")):
        return f"cómo se usa / cómo funciona {topic_s}"

    if any(s in ql for s in ("fecha limite", "fecha límite")) and "corte" in topic_l:
        return f"qué es la fecha límite de pago y cómo se relaciona con {topic_s}"

    if "consumo minimo" in ql or "consumo mínimo" in ql or "minimo de consumo" in ql or "mínimo de consumo" in ql:
        return f"cuál es el consumo mínimo de {topic_s}"

    if "avance" in ql or "efectivo" in ql:
        if "comision" in ql or "comisión" in ql:
            return f"qué comisiones tiene el avance de efectivo en {topic_s}"
        return f"se puede hacer avance de efectivo con {topic_s}"

    if "como se pagan" in ql or "cómo se pagan" in ql or "en cuanto a los pagos" in ql:
        return f"cómo se pagan / modalidades de pago en {topic_s}"

    if "sacar efectivo" in ql or "avance" in ql:
        return f"puedo hacer avance de efectivo con {topic_s}"

    if "pierdo" in ql or "robo" in ql:
        return f"qué hago si pierdo la tarjeta o comprometo seguridad en {topic_s}"

    if "requisito" in ql:
        return f"qué requisitos tiene {topic_s}"

    if "solicito" in ql or "solicitar" in ql or "lo pido" in ql or "pido" in ql:
        return f"cómo solicito {topic_s}"

    if "cancelo" in ql or "cancelar" in ql or "doy de baja" in ql or "de baja" in ql:
        return f"cómo cancelo {topic_s}"

    if "cargo" in ql or "comision" in ql or "comisión" in ql or "cobran" in ql or "cobrar" in ql:
        if "efectivo" in topic_l or "avance" in topic_l or "multicredit" in topic_l:
            return f"qué cargos o comisiones aplican por avance de efectivo en {topic_s}"
        return f"qué cargos tiene {topic_s}"

    if "papeles" in ql or "document" in ql:
        return f"qué requisitos y documentos tiene {topic_s}"

    if "distingue" in ql or "diferencia" in ql:
        return f"cuál es la diferencia principal en {topic_s}"

    if "viene antes" in ql or "ocurre primero" in ql:
        return f"qué ocurre primero entre fecha de corte y fecha límite de pago ({topic_s})"

    if "roban" in ql or "pierdo" in ql or "robo" in ql:
        return f"qué hago si pierdo o me roban la tarjeta en {topic_s}"

    if "atraso" in ql or "pago despues" in ql or "pago después" in ql:
        return f"qué pasa si pago después de la fecha límite ({topic_s})"

    if "minimo de consumo" in ql or "mínimo de consumo" in ql or "consumo minimo" in ql or "consumo mínimo" in ql:
        return f"cuál es el consumo mínimo de {topic_s}"

    if "beneficio" in ql:
        return f"qué beneficios tiene {topic_s}"

    if "derecho" in ql:
        return f"cuáles son mis derechos en el proceso de {topic_s}"

    if "informacion debo" in ql or "información debo" in ql or "debo entregar" in ql:
        return f"qué documentación o información debo entregar para {topic_s}"

    if topic_s.lower() not in ql:
        return f"{q} {topic_s}"
    return q


def should_block_personal_followup(text: str, session: Any | None) -> bool:
    """No reutilizar last_resolved de préstamo/TC si el usuario sigue un hilo KB."""
    if is_bank_responsibility_question(text) or is_client_responsibility_question(text):
        return True
    if has_knowledge_session(session) and is_knowledge_followup(text):
        return True
    return False
