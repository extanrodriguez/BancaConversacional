"""Serialización por conversation_id — asyncio + Redis (fail-closed si Redis requerido).

- In-process: asyncio.Lock (no threading.RLock: deadlock con corutinas en el mismo hilo).
- Multi-réplica: SET NX EX atómico; liberación solo por token propietario; renovación TTL.
- Si GENESIS_REDIS_URL (o CONV_LOCK) está configurado y Redis falla → no degradar a local.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

_log = logging.getLogger("genesis.conversation_gate")


class ConversationGateError(RuntimeError):
    """Redis requerido no disponible o candado perdido."""


class ConversationGate:
    """Candado por conversación seguro para asyncio y multi-réplica."""

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        redis_required: bool = False,
        lock_ttl_s: float = 30.0,
        renew_interval_s: float | None = None,
    ) -> None:
        self._async_locks: dict[str, asyncio.Lock] = {}
        self._async_meta = asyncio.Lock()
        self._redis = redis_client
        self._redis_required = bool(redis_required)
        self._lock_ttl_s = float(max(2.0, lock_ttl_s))
        self._renew_interval_s = float(
            renew_interval_s
            if renew_interval_s is not None
            else max(1.0, self._lock_ttl_s / 3.0)
        )
        self._token_prefix = f"cg-{uuid.uuid4().hex[:8]}"
        # Instrumentación de pruebas (solo tests): retardo dentro de la sección crítica
        self.test_hold_delay_s: float = 0.0
        self.test_signal_path: str | None = None

    async def _async_lock_for(self, conversation_id: str) -> asyncio.Lock:
        async with self._async_meta:
            lk = self._async_locks.get(conversation_id)
            if lk is None:
                lk = asyncio.Lock()
                self._async_locks[conversation_id] = lk
            return lk

    def _redis_key(self, conversation_id: str) -> str:
        return f"genesis:conv_lock:{conversation_id}"

    def _acquire_redis_sync(self, conversation_id: str, token: str, timeout_s: float) -> bool:
        if self._redis is None:
            if self._redis_required:
                raise ConversationGateError("redis_required_but_unavailable")
            return True
        key = self._redis_key(conversation_id)
        deadline = time.time() + max(0.05, timeout_s)
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                ok = self._redis.set(key, token, nx=True, ex=int(self._lock_ttl_s))
                if ok:
                    return True
                last_err = None
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if self._redis_required:
                    # Fail-closed: no degradar a solo local
                    raise ConversationGateError(f"redis_acquire_failed:{exc}") from exc
                raise ConversationGateError(f"redis_acquire_failed:{exc}") from exc
            time.sleep(0.02)
        if last_err is not None and self._redis_required:
            raise ConversationGateError(f"redis_acquire_failed:{last_err}") from last_err
        return False

    def _renew_redis_sync(self, conversation_id: str, token: str) -> bool:
        """Extiende TTL solo si seguimos siendo propietarios. False = candado perdido."""
        if self._redis is None:
            return not self._redis_required
        key = self._redis_key(conversation_id)
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
        )
        try:
            return bool(self._redis.eval(script, 1, key, token, int(self._lock_ttl_s)))
        except Exception as exc:  # noqa: BLE001
            if self._redis_required:
                raise ConversationGateError(f"redis_renew_failed:{exc}") from exc
            return False

    def _still_owner_sync(self, conversation_id: str, token: str) -> bool:
        if self._redis is None:
            return not self._redis_required
        try:
            return self._redis.get(self._redis_key(conversation_id)) == token
        except Exception as exc:  # noqa: BLE001
            if self._redis_required:
                raise ConversationGateError(f"redis_owner_check_failed:{exc}") from exc
            return False

    def _release_redis_sync(self, conversation_id: str, token: str) -> None:
        if self._redis is None:
            return
        key = self._redis_key(conversation_id)
        script = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            self._redis.eval(script, 1, key, token)
        except Exception as exc:  # noqa: BLE001
            _log.warning("redis_release_failed: %s", exc)

    @asynccontextmanager
    async def hold(self, conversation_id: str, *, timeout_s: float = 25.0) -> AsyncIterator[dict[str, Any]]:
        """Yields dict {acquired, token, still_owner callable}.

        acquired=False → ocupado (timeout). No abrir sección crítica.
        """
        cid = (conversation_id or "").strip() or "_anon"
        local = await self._async_lock_for(cid)
        try:
            await asyncio.wait_for(local.acquire(), timeout=max(0.05, timeout_s))
        except TimeoutError:
            yield {"acquired": False, "token": None, "still_owner": lambda: False}
            return

        token = f"{self._token_prefix}:{uuid.uuid4().hex}"
        renew_task: asyncio.Task | None = None
        acquired_remote = False
        try:
            acquired_remote = await asyncio.to_thread(
                self._acquire_redis_sync, cid, token, max(0.5, timeout_s / 2),
            )
            if not acquired_remote:
                yield {"acquired": False, "token": None, "still_owner": lambda: False}
                return

            async def _renew_loop() -> None:
                while True:
                    await asyncio.sleep(self._renew_interval_s)
                    ok = await asyncio.to_thread(self._renew_redis_sync, cid, token)
                    if not ok:
                        _log.warning("conversation_lock_lost cid=%s", cid)
                        return

            renew_task = asyncio.create_task(_renew_loop())

            def still_owner() -> bool:
                return self._still_owner_sync(cid, token)

            # Instrumentación de prueba: señal + retardo para forzar contención
            if self.test_signal_path:
                try:
                    PathWrite = open  # noqa: N806 — local alias
                    with PathWrite(self.test_signal_path, "w", encoding="utf-8") as fh:
                        fh.write(f"held:{cid}:{token}\n")
                except Exception:
                    pass
            if self.test_hold_delay_s > 0:
                await asyncio.sleep(float(self.test_hold_delay_s))

            yield {
                "acquired": True,
                "token": token,
                "still_owner": still_owner,
            }
        finally:
            if renew_task is not None:
                renew_task.cancel()
                try:
                    await renew_task
                except asyncio.CancelledError:
                    pass
            if acquired_remote:
                await asyncio.to_thread(self._release_redis_sync, cid, token)
            local.release()


_GATE: ConversationGate | None = None
_GATE_LOCK = threading.Lock()


def _redis_url() -> str:
    from genesis_cognitive.context.redis_client_factory import lock_redis_url

    return lock_redis_url()


def get_conversation_gate() -> ConversationGate:
    global _GATE
    with _GATE_LOCK:
        if _GATE is not None:
            return _GATE
        from genesis_cognitive.context.redis_client_factory import (
            create_and_ping,
            redis_required,
        )

        url = _redis_url()
        redis_client = None
        # Candado Redis si hay URL o si el perfil exige Redis (mismo store)
        required = bool(url) or redis_required()
        if required and not url:
            raise ConversationGateError(
                "redis_required_but_GENESIS_CONV_LOCK_REDIS_URL_and_GENESIS_REDIS_URL_empty"
            )
        if url:
            try:
                redis_client = create_and_ping(url, purpose="lock")
            except Exception as exc:  # noqa: BLE001
                raise ConversationGateError(
                    f"redis_configured_but_unreachable:{exc}"
                ) from exc
        ttl = float(os.getenv("GENESIS_CONV_LOCK_TTL_S", "30") or 30)
        _GATE = ConversationGate(
            redis_client=redis_client,
            redis_required=bool(redis_client is not None) or required,
            lock_ttl_s=ttl,
        )
        return _GATE


def reset_conversation_gate_for_tests(gate: ConversationGate | None = None) -> None:
    global _GATE
    with _GATE_LOCK:
        _GATE = gate


def conversation_gate_backend_name(gate: ConversationGate | None = None) -> str:
    g = gate if gate is not None else _GATE
    if g is None:
        return "uninitialized"
    return "redis" if g._redis is not None else "local"
