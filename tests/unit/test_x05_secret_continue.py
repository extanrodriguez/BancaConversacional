# Test strip_auth_secret_clauses + refuse-and-continue (X05)

from genesis_cognitive.brain.security_secrets import strip_auth_secret_clauses
from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.brain.plan_executor import execute_turn_plan

from tests.unit.test_cognitive_improvement_v3 import _snap_mixed


def test_strip_pin_keeps_account_intent() -> None:
    rem = strip_auth_secret_clauses("Mi PIN es 1234, ahora dime cuánto tengo en la cuenta.")
    assert "1234" not in rem
    assert "pin" not in rem.lower()
    assert "cuenta" in rem.lower()


def test_pin_plus_account_refuse_and_continue() -> None:
    snap = _snap_mixed()
    q = "Mi PIN es 1234, ahora dime cuánto tengo en la cuenta."
    plan = interpret_turn_plan(q, None, snapshot=snap)
    actions = [(t.action, t.object) for t in plan.tasks]
    assert ("refuse", "secret") in actions
    assert any(a == "read_field" and o == "account" for a, o in actions)
    pex = execute_turn_plan(plan, snap, q, session=None)
    text = (pex.text or "").lower()
    assert "pin" in text or "seguridad" in text
    assert "1234" not in (pex.text or "")
    assert any(k in text for k in ("saldo", "disponible", "cuenta"))
