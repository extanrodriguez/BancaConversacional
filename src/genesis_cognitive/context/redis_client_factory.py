"""Fábrica común de clientes Redis (sesiones + candados).

Soporta:
- GENESIS_REDIS_AUTH_MODE=entra_managed_identity → redis-entraid + identidad administrada
- GENESIS_REDIS_AUTH_MODE=url (o vacío) → redis.from_url (p. ej. Docker local sin Entra)

No incluye contraseñas ni tokens en logs. TLS con verificación de certificado/hostname.
"""

from __future__ import annotations

import logging
import os
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

_log = logging.getLogger("genesis.redis_client")

REDIS_ENTRA_RESOURCE = "https://redis.azure.com/"


class RedisClientConfigError(RuntimeError):
    """Configuración Redis inválida o incompleta."""


class RedisClientConnectionError(RuntimeError):
    """Redis configurado pero inaccesible."""


@dataclass(frozen=True)
class RedisEndpoint:
    """Endpoint sin secretos (para diagnóstico)."""

    scheme: str
    host: str
    port: int
    db: int
    url_for_client: str  # sin password
    tls: bool


def redis_auth_mode() -> str:
    raw = (os.getenv("GENESIS_REDIS_AUTH_MODE") or "").strip().lower()
    if raw in ("entra_managed_identity", "entra", "managed_identity", "mi"):
        return "entra_managed_identity"
    if raw in ("url", "access_key", "password", "key"):
        return "url"
    return raw or "url"


def session_backend_preference() -> str:
    """memory | redis | auto."""
    raw = (os.getenv("GENESIS_SESSION_BACKEND") or "").strip().lower()
    if raw in ("memory", "mem", "in_memory", "local"):
        return "memory"
    if raw in ("redis",):
        return "redis"
    return "auto"


def redis_required() -> bool:
    """True en QA/PROD o cuando se exige Redis explícitamente."""
    if session_backend_preference() == "memory":
        return False
    if session_backend_preference() == "redis":
        return True
    flag = (os.getenv("GENESIS_REDIS_REQUIRED") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    env = (os.getenv("GENESIS_ENV") or "dev").strip().lower()
    return env in ("qa", "prod", "production")


def session_redis_url() -> str:
    return (os.getenv("GENESIS_REDIS_URL") or os.getenv("REDIS_URL") or "").strip()


def lock_redis_url() -> str:
    return (
        (os.getenv("GENESIS_CONV_LOCK_REDIS_URL") or "").strip()
        or session_redis_url()
    )


def _strip_userinfo(url: str) -> str:
    """Quita user/password de la URL (Entra no debe llevar token en la URL)."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise RedisClientConfigError("redis_url_missing_host")
    netloc = parsed.hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((
        parsed.scheme or "rediss",
        netloc,
        parsed.path or "/0",
        "",
        "",
        "",
    ))


def parse_redis_endpoint(url: str) -> RedisEndpoint:
    if not url:
        raise RedisClientConfigError("redis_url_empty")
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise RedisClientConfigError("redis_url_missing_host")
    scheme = (parsed.scheme or "redis").lower()
    tls = scheme in ("rediss", "redis+ssl")
    port = int(parsed.port or (10000 if tls else 6379))
    path = (parsed.path or "/0").lstrip("/")
    try:
        db = int(path.split("/")[0] or "0")
    except ValueError:
        db = 0
    clean = _strip_userinfo(url)
    return RedisEndpoint(
        scheme=scheme,
        host=host,
        port=port,
        db=db,
        url_for_client=clean,
        tls=tls,
    )


def _build_entra_credential_provider() -> Any:
    try:
        from redis_entraid.cred_provider import create_from_managed_identity
        from redis_entraid.identity_provider import (
            ManagedIdentityIdType,
            ManagedIdentityType,
        )
    except ImportError as exc:  # pragma: no cover
        raise RedisClientConfigError(
            "redis_entraid_not_installed: declare redis-entraid in dependencies"
        ) from exc

    identity = (
        os.getenv("GENESIS_REDIS_MANAGED_IDENTITY_TYPE") or "system_assigned"
    ).strip().lower()
    resource = (
        os.getenv("GENESIS_REDIS_ENTRA_RESOURCE") or REDIS_ENTRA_RESOURCE
    ).strip()

    if identity in ("user_assigned", "user", "uai"):
        client_id = (
            os.getenv("GENESIS_REDIS_MANAGED_IDENTITY_CLIENT_ID")
            or os.getenv("AZURE_CLIENT_ID")
            or ""
        ).strip()
        if not client_id:
            raise RedisClientConfigError(
                "entra_user_assigned_requires_GENESIS_REDIS_MANAGED_IDENTITY_CLIENT_ID"
            )
        return create_from_managed_identity(
            identity_type=ManagedIdentityType.USER_ASSIGNED,
            resource=resource,
            id_type=ManagedIdentityIdType.CLIENT_ID,
            id_value=client_id,
        )

    return create_from_managed_identity(
        identity_type=ManagedIdentityType.SYSTEM_ASSIGNED,
        resource=resource,
    )


def create_redis_client(
    url: str | None = None,
    *,
    purpose: str = "session",
    decode_responses: bool = True,
    socket_connect_timeout: float = 2.0,
    socket_timeout: float = 2.0,
) -> Any:
    """Crea un cliente redis-py para sesiones o candados.

    purpose solo etiqueta logs/diagnóstico; no cambia el protocolo.
    """
    import redis

    raw_url = (url or "").strip()
    if not raw_url:
        raise RedisClientConfigError(f"redis_url_required_for_{purpose}")

    endpoint = parse_redis_endpoint(raw_url)
    mode = redis_auth_mode()
    common: dict[str, Any] = {
        "decode_responses": decode_responses,
        "socket_connect_timeout": socket_connect_timeout,
        "socket_timeout": socket_timeout,
        "retry_on_timeout": True,
        "health_check_interval": 30,
    }

    if mode == "entra_managed_identity":
        if not endpoint.tls:
            raise RedisClientConfigError(
                "entra_managed_identity_requires_rediss_tls"
            )
        # Hostname TLS = host del recurso (no IP ni alias privatelink)
        provider = _build_entra_credential_provider()
        client = redis.Redis(
            host=endpoint.host,
            port=endpoint.port,
            db=endpoint.db,
            ssl=True,
            ssl_cert_reqs=ssl.CERT_REQUIRED,
            ssl_check_hostname=True,
            credential_provider=provider,
            **common,
        )
        _log.info(
            "redis_client_created purpose=%s auth=entra_managed_identity host=%s port=%s db=%s",
            purpose,
            endpoint.host,
            endpoint.port,
            endpoint.db,
        )
        return client

    # Modo URL (Docker local / access key legacy). Nunca ssl_cert_reqs=None.
    kwargs = dict(common)
    if endpoint.tls:
        kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
        kwargs["ssl_check_hostname"] = True
    client = redis.from_url(raw_url, **kwargs)
    _log.info(
        "redis_client_created purpose=%s auth=url host=%s port=%s db=%s tls=%s",
        purpose,
        endpoint.host,
        endpoint.port,
        endpoint.db,
        endpoint.tls,
    )
    return client


def ping_client(client: Any) -> bool:
    try:
        return bool(client.ping())
    except Exception as exc:  # noqa: BLE001
        _log.warning("redis_ping_failed: %s", type(exc).__name__)
        return False


def create_and_ping(
    url: str | None,
    *,
    purpose: str,
) -> Any:
    client = create_redis_client(url, purpose=purpose)
    if not ping_client(client):
        raise RedisClientConnectionError(f"redis_ping_failed:{purpose}")
    return client


def diagnose_redis_backends(
    *,
    session_store: Any | None = None,
    lock_client: Any | None = None,
) -> dict[str, Any]:
    """Señal diagnóstica interna sin secretos."""
    sess_url = session_redis_url()
    lock_url = lock_redis_url()
    pref = session_backend_preference()
    required = redis_required()
    mode = redis_auth_mode()

    session_backend = "memory"
    lock_backend = "local"
    session_ping: bool | None = None
    lock_ping: bool | None = None
    session_host: str | None = None
    lock_host: str | None = None
    errors: list[str] = []

    if session_store is not None:
        name = type(session_store).__name__
        if "Redis" in name:
            session_backend = "redis"
            client = getattr(session_store, "_client", None)
            if client is not None:
                session_ping = ping_client(client)
            try:
                session_host = parse_redis_endpoint(sess_url).host if sess_url else None
            except Exception:
                session_host = None
        else:
            session_backend = "memory"
    elif sess_url:
        session_backend = "redis"
        try:
            ep = parse_redis_endpoint(sess_url)
            session_host = ep.host
            c = create_redis_client(sess_url, purpose="diagnose_session")
            session_ping = ping_client(c)
            try:
                c.close()
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            session_ping = False
            errors.append(f"session:{type(exc).__name__}")

    if lock_client is not None:
        lock_backend = "redis"
        lock_ping = ping_client(lock_client)
        try:
            lock_host = parse_redis_endpoint(lock_url).host if lock_url else None
        except Exception:
            lock_host = None
    elif lock_url:
        lock_backend = "redis"
        try:
            ep = parse_redis_endpoint(lock_url)
            lock_host = ep.host
            c = create_redis_client(lock_url, purpose="diagnose_lock")
            lock_ping = ping_client(c)
            try:
                c.close()
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            lock_ping = False
            errors.append(f"lock:{type(exc).__name__}")

    ok = True
    if required and session_backend != "redis":
        ok = False
        errors.append("session_backend_not_redis_while_required")
    if required and lock_backend != "redis":
        ok = False
        errors.append("lock_backend_not_redis_while_required")
    if session_backend == "redis" and session_ping is False:
        ok = False
    if lock_backend == "redis" and lock_ping is False:
        ok = False

    return {
        "ok": ok,
        "session_backend": session_backend,
        "lock_backend": lock_backend,
        "auth_mode": mode,
        "redis_required": required,
        "session_backend_preference": pref,
        "session_ping": session_ping,
        "lock_ping": lock_ping,
        "session_host": session_host,
        "lock_host": lock_host,
        "errors": errors,
    }
