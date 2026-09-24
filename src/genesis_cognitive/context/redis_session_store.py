"""RedisSessionStore — shared session/snapshot store for multi-replica ACA."""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)
from genesis_cognitive.context.reactive_store import (
    LastResolved,
    PendingAction,
    SessionConflictError,
    SessionState,
)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def product_to_dict(p: ProductSnapshot) -> dict[str, Any]:
    return {
        "product_id": p.product_id,
        "product_type": p.product_type,
        "alias": p.alias,
        "currency": p.currency,
        "status": p.status,
        "available_balance": None if p.available_balance is None else str(p.available_balance),
        "ledger_balance": None if p.ledger_balance is None else str(p.ledger_balance),
        "card_mask": p.card_mask,
        "last_four": p.last_four,
        "credit_limit": None if p.credit_limit is None else str(p.credit_limit),
        "min_payment_rd": None if p.min_payment_rd is None else str(p.min_payment_rd),
        "min_payment_us": None if p.min_payment_us is None else str(p.min_payment_us),
        "statement_balance_rd": None if p.statement_balance_rd is None else str(p.statement_balance_rd),
        "statement_balance_us": None if p.statement_balance_us is None else str(p.statement_balance_us),
        "cutoff_day": p.cutoff_day,
        "available_purchases_domestic": None if p.available_purchases_domestic is None else str(p.available_purchases_domestic),
        "available_purchases_foreign": None if p.available_purchases_foreign is None else str(p.available_purchases_foreign),
        "interest_rate": None if p.interest_rate is None else str(p.interest_rate),
        "interest_amount": None if p.interest_amount is None else str(p.interest_amount),
        "maturity_date": p.maturity_date,
        "multi_currency": p.multi_currency,
        "foreign_currency_balance": None if p.foreign_currency_balance is None else str(p.foreign_currency_balance),
        "domestic_currency_balance": None if p.domestic_currency_balance is None else str(p.domestic_currency_balance),
        "card_expiry": p.card_expiry,
        "party_type": p.party_type,
        "payment_due_date": p.payment_due_date,
    }


def product_from_dict(d: dict[str, Any]) -> ProductSnapshot:
    return ProductSnapshot(
        product_id=str(d["product_id"]),
        product_type=str(d["product_type"]),
        alias=d.get("alias"),
        currency=str(d.get("currency") or "DOP"),
        status=str(d.get("status") or "active"),
        available_balance=_dec(d.get("available_balance")),
        ledger_balance=_dec(d.get("ledger_balance")),
        card_mask=d.get("card_mask"),
        last_four=d.get("last_four"),
        credit_limit=_dec(d.get("credit_limit")),
        min_payment_rd=_dec(d.get("min_payment_rd")),
        min_payment_us=_dec(d.get("min_payment_us")),
        statement_balance_rd=_dec(d.get("statement_balance_rd")),
        statement_balance_us=_dec(d.get("statement_balance_us")),
        cutoff_day=d.get("cutoff_day"),
        available_purchases_domestic=_dec(d.get("available_purchases_domestic")),
        available_purchases_foreign=_dec(d.get("available_purchases_foreign")),
        interest_rate=_dec(d.get("interest_rate")),
        interest_amount=_dec(d.get("interest_amount")),
        maturity_date=d.get("maturity_date"),
        multi_currency=d.get("multi_currency"),
        foreign_currency_balance=_dec(d.get("foreign_currency_balance")),
        domestic_currency_balance=_dec(d.get("domestic_currency_balance")),
        card_expiry=d.get("card_expiry"),
        party_type=d.get("party_type"),
        payment_due_date=d.get("payment_due_date"),
    )


def loan_to_dict(ln: LoanSnapshot) -> dict[str, Any]:
    return {
        "product_id": ln.product_id,
        "loan_type": ln.loan_type,
        "installment_amount": str(ln.installment_amount),
        "annual_interest_rate": str(ln.annual_interest_rate),
        "outstanding_principal": str(ln.outstanding_principal),
        "delinquency_days": ln.delinquency_days,
        "next_due_date": ln.next_due_date,
        "disbursed_amount": None if ln.disbursed_amount is None else str(ln.disbursed_amount),
        "payoff_amount": None if ln.payoff_amount is None else str(ln.payoff_amount),
        "maturity_date": ln.maturity_date,
        "last_four": ln.last_four,
        "overdue_amount": None if ln.overdue_amount is None else str(ln.overdue_amount),
    }


def loan_from_dict(d: dict[str, Any]) -> LoanSnapshot:
    return LoanSnapshot(
        product_id=str(d["product_id"]),
        loan_type=str(d.get("loan_type") or "GENERAL"),
        installment_amount=_dec(d.get("installment_amount")) or Decimal("0"),
        annual_interest_rate=_dec(d.get("annual_interest_rate")) or Decimal("0"),
        outstanding_principal=_dec(d.get("outstanding_principal")) or Decimal("0"),
        delinquency_days=int(d.get("delinquency_days") or 0),
        next_due_date=d.get("next_due_date"),
        disbursed_amount=_dec(d.get("disbursed_amount")),
        payoff_amount=_dec(d.get("payoff_amount")),
        maturity_date=d.get("maturity_date"),
        last_four=d.get("last_four"),
        overdue_amount=_dec(d.get("overdue_amount")),
    )


def snapshot_to_dict(snap: CustomerContextSnapshot) -> dict[str, Any]:
    return {
        "customer_id": snap.customer_id,
        "display_name": snap.display_name,
        "default_currency": snap.default_currency,
        "products": [product_to_dict(p) for p in snap.products],
        "loans": [loan_to_dict(ln) for ln in snap.loans],
    }


def snapshot_from_dict(d: dict[str, Any]) -> CustomerContextSnapshot:
    return CustomerContextSnapshot(
        customer_id=str(d.get("customer_id") or ""),
        display_name=str(d.get("display_name") or "Cliente"),
        default_currency=str(d.get("default_currency") or "DOP"),
        products=tuple(product_from_dict(p) for p in (d.get("products") or [])),
        loans=tuple(loan_from_dict(ln) for ln in (d.get("loans") or [])),
    )


def session_to_dict(session: SessionState) -> dict[str, Any]:
    pending = None
    if session.pending_action is not None:
        pa = session.pending_action
        pending = {
            "intent_id": pa.intent_id,
            "capability_candidate": pa.capability_candidate,
            "selected_route": pa.selected_route,
            "detected_entities": pa.detected_entities,
            "missing_requirements": pa.missing_requirements,
            "suggested_question": pa.suggested_question,
            "original_question": getattr(pa, "original_question", "") or "",
            "query_spec": dict(getattr(pa, "query_spec", {}) or {}),
        }
    last = None
    if session.last_resolved is not None:
        lr = session.last_resolved
        last = {
            "intent_id": lr.intent_id,
            "account_ref": lr.account_ref,
            "original_question": lr.original_question,
        }
    focus = None
    if session.product_focus is not None:
        pf = session.product_focus
        focus = {
            "kind": pf.kind,
            "product_id": pf.product_id,
            "intent_id": pf.intent_id,
            "original_question": pf.original_question,
            "updated_at": pf.updated_at,
        }
    snap = None
    if session.snapshot is not None:
        snap = snapshot_to_dict(session.snapshot)
    return {
        "customer_id": session.customer_id,
        "history": session.history,
        "pending_action": pending,
        "last_resolved": last,
        "product_focus": focus,
        "last_knowledge_topic": session.last_knowledge_topic,
        "snapshot": snap,
        "updated_at": session.updated_at,
        "schema_version": int(getattr(session, "schema_version", 1) or 1),
        "revision": int(getattr(session, "revision", 0) or 0),
        "snapshot_source_fetched_at": getattr(session, "snapshot_source_fetched_at", None),
        "pending_tasks": list(getattr(session, "pending_tasks", None) or []),
        "compare_set": list(getattr(session, "compare_set", None) or []),
        "process_focus": getattr(session, "process_focus", None),
        "catalog_personal_map": dict(getattr(session, "catalog_personal_map", None) or {}),
    }


def session_from_dict(d: dict[str, Any]) -> SessionState:
    from genesis_cognitive.context.reactive_store import ProductFocus

    pending = None
    if d.get("pending_action"):
        pa = d["pending_action"]
        pending = PendingAction(
            intent_id=pa["intent_id"],
            capability_candidate=pa.get("capability_candidate"),
            selected_route=pa.get("selected_route") or "PERSONAL_READ",
            detected_entities=dict(pa.get("detected_entities") or {}),
            missing_requirements=list(pa.get("missing_requirements") or []),
            suggested_question=str(pa.get("suggested_question") or ""),
            original_question=str(pa.get("original_question") or ""),
            query_spec={
                str(k): str(v)
                for k, v in dict(pa.get("query_spec") or {}).items()
            },
        )
    last = None
    if d.get("last_resolved"):
        lr = d["last_resolved"]
        last = LastResolved(
            intent_id=lr["intent_id"],
            account_ref=lr["account_ref"],
            original_question=str(lr.get("original_question") or ""),
        )
    focus = None
    if d.get("product_focus"):
        pf = d["product_focus"]
        focus = ProductFocus(
            kind=str(pf.get("kind") or ""),
            product_id=str(pf.get("product_id") or ""),
            intent_id=str(pf.get("intent_id") or ""),
            original_question=str(pf.get("original_question") or ""),
            updated_at=float(pf.get("updated_at") or time.time()),
        )
        if not focus.kind or not focus.product_id:
            focus = None
    snap = None
    if d.get("snapshot"):
        snap = snapshot_from_dict(d["snapshot"])
    return SessionState(
        customer_id=str(d.get("customer_id") or ""),
        history=list(d.get("history") or []),
        pending_action=pending,
        last_resolved=last,
        product_focus=focus,
        last_knowledge_topic=(str(d["last_knowledge_topic"]) if d.get("last_knowledge_topic") else None),
        snapshot=snap,
        updated_at=float(d.get("updated_at") or time.time()),
        schema_version=int(d.get("schema_version") or 1),
        revision=int(d.get("revision") or 0),
        snapshot_source_fetched_at=(
            None
            if d.get("snapshot_source_fetched_at") is None
            else float(d["snapshot_source_fetched_at"])
        ),
        pending_tasks=list(d.get("pending_tasks") or []),
        compare_set=[str(x) for x in (d.get("compare_set") or [])],
        process_focus=(str(d["process_focus"]) if d.get("process_focus") else None),
        catalog_personal_map={
            str(k): str(v) for k, v in dict(d.get("catalog_personal_map") or {}).items()
        },
    )


class RedisSessionStore:
    """Redis-backed session/snapshot store (multi-replica safe).

    Contexto atado a sesión: el snapshot viaja en session:{id} y el TTL de Redis
    de la sesión renueva con cada put_session. Al expirar la sesión, muere el contexto.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        session_ttl_s: float | None = None,
        snapshot_ttl_s: float | None = None,
        *,
        redis_client: Any | None = None,
    ) -> None:
        from genesis_cognitive.context.redis_client_factory import (
            create_redis_client,
            session_redis_url,
        )

        url = (redis_url or session_redis_url() or "").strip()
        if redis_client is None and not url:
            raise ValueError("GENESIS_REDIS_URL is required for RedisSessionStore")
        self._session_ttl = int(session_ttl_s or float(os.getenv("GENESIS_SESSION_TTL_S", "1800")))
        # Por defecto sin TTL propio: "session" | "0" | vacío
        env_snap = (os.getenv("GENESIS_SNAPSHOT_TTL_S", "session") or "session").strip()
        if snapshot_ttl_s is not None:
            self._snapshot_ttl = int(snapshot_ttl_s) if snapshot_ttl_s else None
        elif env_snap in ("0", "none", "None", "session", ""):
            self._snapshot_ttl = None
        else:
            self._snapshot_ttl = int(float(env_snap))
        self._client = redis_client or create_redis_client(url, purpose="session")
        self.backend_name = "redis"

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    def get_session(self, conversation_id: str) -> SessionState | None:
        raw = self._client.get(f"session:{conversation_id}")
        if not raw:
            return None
        session = session_from_dict(json.loads(raw))
        # Sincronizar frescura desde respaldo global sin inventar fecha
        if session.customer_id:
            try:
                snap_raw = self._client.get(f"customer:{session.customer_id}:snapshot")
                if snap_raw:
                    meta = json.loads(snap_raw)
                    if "source_fetched_at" in meta:
                        fetched = meta.get("source_fetched_at")
                        session.snapshot_source_fetched_at = (
                            None if fetched is None else float(fetched)
                        )
            except Exception:
                pass
        return session

    def put_session(
        self,
        conversation_id: str,
        session: SessionState,
        *,
        expected_revision: int | None = None,
    ) -> int:
        """Persistencia con CAS por revisión (WATCH) seguro entre réplicas Redis.

        expected_revision=None → escritura legacy (contract_inspector) que igual
        incrementa revisión. Con expected_revision, conflicto → SessionConflictError.
        """
        from redis.exceptions import WatchError

        key = f"session:{conversation_id}"
        new_rev = int(getattr(session, "revision", 0) or 0) + 1
        attempts = 0
        while attempts < 8:
            attempts += 1
            pipe = self._client.pipeline()
            try:
                pipe.watch(key)
                raw = pipe.get(key)
                actual_rev = 0
                if raw:
                    try:
                        actual_rev = int(json.loads(raw).get("revision") or 0)
                    except Exception:
                        actual_rev = 0
                if expected_revision is not None and actual_rev != int(expected_revision):
                    pipe.unwatch()
                    raise SessionConflictError(
                        conversation_id, int(expected_revision), actual_rev,
                    )
                new_rev = actual_rev + 1
                session.revision = new_rev
                session.schema_version = max(
                    1, int(getattr(session, "schema_version", 1) or 1),
                )
                session.updated_at = time.time()
                payload = json.dumps(session_to_dict(session), ensure_ascii=False)
                pipe.multi()
                pipe.setex(key, self._session_ttl, payload)
                pipe.execute()
                break
            except WatchError:
                if expected_revision is not None:
                    # Otro writer ganó: releer y reportar conflicto
                    raw2 = self._client.get(key)
                    actual2 = 0
                    if raw2:
                        try:
                            actual2 = int(json.loads(raw2).get("revision") or 0)
                        except Exception:
                            actual2 = 0
                    raise SessionConflictError(
                        conversation_id, int(expected_revision), actual2,
                    )
                continue
            finally:
                try:
                    pipe.reset()
                except Exception:
                    pass
        else:
            raise SessionConflictError(
                conversation_id,
                int(expected_revision) if expected_revision is not None else -1,
                int(getattr(session, "revision", 0) or 0),
            )

        if session.snapshot is not None and session.customer_id:
            self.put_snapshot(
                session.customer_id,
                session.snapshot,
                bound_conversation_id=conversation_id,
                preserve_source_fetched_at=True,
            )
            age_meta = self._client.get(f"customer:{session.customer_id}:snapshot")
            if age_meta:
                try:
                    meta = json.loads(age_meta)
                    if "source_fetched_at" in meta:
                        fetched = meta.get("source_fetched_at")
                        session.snapshot_source_fetched_at = (
                            None if fetched is None else float(fetched)
                        )
                except Exception:
                    pass
        return int(session.revision)

    def create_session(self, conversation_id: str, customer_id: str) -> SessionState:
        session = SessionState(customer_id=customer_id)
        self.put_session(conversation_id, session, expected_revision=0)
        return session

    def delete_session(self, conversation_id: str) -> None:
        raw = self._client.get(f"session:{conversation_id}")
        self._client.delete(f"session:{conversation_id}")
        if raw:
            try:
                data = json.loads(raw)
                cid = data.get("customer_id")
                if cid:
                    # Solo borrar snapshot global si estaba atado a esta conversación
                    snap_raw = self._client.get(f"customer:{cid}:snapshot")
                    if snap_raw:
                        meta = json.loads(snap_raw)
                        if meta.get("bound_conversation_id") == conversation_id:
                            self._client.delete(f"customer:{cid}:snapshot")
            except Exception:
                pass

    def get_snapshot(self, customer_id: str) -> CustomerContextSnapshot | None:
        raw = self._client.get(f"customer:{customer_id}:snapshot")
        if not raw:
            return None
        data = json.loads(raw)
        return snapshot_from_dict(data.get("snapshot") or data)

    def get_snapshot_age(self, customer_id: str) -> float | None:
        """Edad del dato bancario. None si falta, es desconocida o está vencida.

        Limitación: esta capa no refresca el Core; edad alta ≠ permiso para
        afirmar que el saldo sigue vigente.
        """
        raw = self._client.get(f"customer:{customer_id}:snapshot")
        if not raw:
            return None
        data = json.loads(raw)
        # Preferir source_fetched_at. loaded_at legacy sin source → desconocido.
        if "source_fetched_at" in data:
            fetched = data.get("source_fetched_at")
            if fetched is None:
                return None
            age = time.time() - float(fetched)
        else:
            # Estado antiguo sin marca de origen bancario
            return None
        if self._snapshot_ttl is not None and age > self._snapshot_ttl:
            return None
        return age

    def put_snapshot(
        self,
        customer_id: str,
        snapshot: CustomerContextSnapshot,
        *,
        bound_conversation_id: str | None = None,
        source_fetched_at: float | None = None,
        preserve_source_fetched_at: bool = False,
        mark_fetched_now: bool = False,
    ) -> None:
        previous_fetched: float | None = None
        previous_bound = bound_conversation_id
        try:
            raw = self._client.get(f"customer:{customer_id}:snapshot")
            if raw:
                prev = json.loads(raw)
                if "source_fetched_at" in prev:
                    previous_fetched = (
                        None
                        if prev.get("source_fetched_at") is None
                        else float(prev["source_fetched_at"])
                    )
                if bound_conversation_id is None:
                    previous_bound = prev.get("bound_conversation_id")
        except Exception:
            previous_fetched = None

        if mark_fetched_now:
            fetched: float | None = time.time()
        elif source_fetched_at is not None:
            fetched = float(source_fetched_at)
        elif preserve_source_fetched_at:
            fetched = previous_fetched
        else:
            fetched = time.time()

        payload = {
            "snapshot": snapshot_to_dict(snapshot),
            # loaded_at = persistencia local; no implica frescura bancaria
            "loaded_at": time.time(),
            "source_fetched_at": fetched,
            "version": "v1",
            "bound_conversation_id": previous_bound,
        }
        # Mismo TTL que la sesión cuando no hay TTL propio de snapshot
        ttl = self._snapshot_ttl if self._snapshot_ttl is not None else self._session_ttl
        self._client.setex(
            f"customer:{customer_id}:snapshot",
            int(ttl),
            json.dumps(payload, ensure_ascii=False),
        )

    def session_count(self) -> int:
        return len(list(self._client.scan_iter("session:*", count=100)))

    def snapshot_count(self) -> int:
        return len(list(self._client.scan_iter("customer:*:snapshot", count=100)))

    def session_keys(self) -> list[str]:
        keys = list(self._client.scan_iter("session:*", count=100))
        return [k.split("session:", 1)[-1] for k in keys]


def build_session_store():
    """Factory: Redis (Entra o URL) o memoria explícita; fail-closed en QA/PROD."""
    from genesis_cognitive.context.reactive_store import ReactiveSessionStore
    from genesis_cognitive.context.redis_client_factory import (
        RedisClientConfigError,
        RedisClientConnectionError,
        redis_required,
        session_backend_preference,
        session_redis_url,
    )

    pref = session_backend_preference()
    url = session_redis_url()
    required = redis_required()

    if pref == "memory":
        store = ReactiveSessionStore()
        store.backend_name = "memory"  # type: ignore[attr-defined]
        return store

    if not url:
        if required or pref == "redis":
            raise RuntimeError(
                "RedisSessionStore required but GENESIS_REDIS_URL is empty "
                "(set GENESIS_SESSION_BACKEND=memory only for local tests)"
            )
        store = ReactiveSessionStore()
        store.backend_name = "memory"  # type: ignore[attr-defined]
        return store

    try:
        store = RedisSessionStore(redis_url=url)
        if not store.ping():
            raise RedisClientConnectionError("redis ping failed")
        return store
    except (RedisClientConfigError, RedisClientConnectionError, Exception) as exc:
        # URL configurada: nunca degradar en silencio (tampoco en dev)
        raise RuntimeError(f"RedisSessionStore unavailable: {exc}") from exc
