"""Pruebas de fábrica Redis Entra + fail-closed (sin Redis remoto obligatorio)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from genesis_cognitive.context.redis_client_factory import (
    RedisClientConfigError,
    create_redis_client,
    diagnose_redis_backends,
    parse_redis_endpoint,
    redis_auth_mode,
    redis_required,
    session_backend_preference,
)
from genesis_cognitive.context.redis_session_store import (
    build_session_store,
    session_from_dict,
    session_to_dict,
)
from genesis_cognitive.context.reactive_store import SessionState


def test_parse_endpoint_strips_password() -> None:
    ep = parse_redis_endpoint(
        "rediss://:supersecret@bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0"
    )
    assert ep.host == "bsc-cognitive-redis-qa.eastus.redis.azure.net"
    assert ep.port == 10000
    assert ep.tls is True
    assert "supersecret" not in ep.url_for_client
    assert ep.url_for_client.startswith("rediss://")


def test_entra_mode_requires_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_REDIS_AUTH_MODE", "entra_managed_identity")
    with pytest.raises(RedisClientConfigError, match="requires_rediss"):
        create_redis_client("redis://127.0.0.1:6379/0", purpose="session")


def test_entra_builds_client_with_credential_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_REDIS_AUTH_MODE", "entra_managed_identity")
    fake_provider = object()
    fake_client = MagicMock(name="redis_client")

    with patch(
        "genesis_cognitive.context.redis_client_factory._build_entra_credential_provider",
        return_value=fake_provider,
    ), patch("redis.Redis", return_value=fake_client) as redis_cls:
        client = create_redis_client(
            "rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0",
            purpose="session",
        )
    assert client is fake_client
    kwargs = redis_cls.call_args.kwargs
    assert kwargs["credential_provider"] is fake_provider
    assert kwargs["ssl"] is True
    assert kwargs["ssl_check_hostname"] is True
    assert kwargs["host"] == "bsc-cognitive-redis-qa.eastus.redis.azure.net"
    assert kwargs["port"] == 10000


def test_lock_and_session_share_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ambos propósitos pasan por create_redis_client (misma auth)."""
    monkeypatch.setenv("GENESIS_REDIS_AUTH_MODE", "url")
    calls: list[str] = []

    def _fake_from_url(url, **kwargs):
        calls.append(url)
        m = MagicMock()
        m.ping.return_value = True
        return m

    with patch("redis.from_url", side_effect=_fake_from_url):
        create_redis_client("redis://127.0.0.1:6379/0", purpose="session")
        create_redis_client("redis://127.0.0.1:6379/0", purpose="lock")
    assert calls == ["redis://127.0.0.1:6379/0", "redis://127.0.0.1:6379/0"]


def test_qa_requires_redis_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_ENV", "qa")
    monkeypatch.delenv("GENESIS_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("GENESIS_SESSION_BACKEND", raising=False)
    assert redis_required() is True
    with pytest.raises(RuntimeError, match="GENESIS_REDIS_URL is empty"):
        build_session_store()


def test_explicit_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_ENV", "qa")
    monkeypatch.setenv("GENESIS_SESSION_BACKEND", "memory")
    monkeypatch.delenv("GENESIS_REDIS_URL", raising=False)
    store = build_session_store()
    assert type(store).__name__ == "ReactiveSessionStore"
    assert session_backend_preference() == "memory"


def test_url_configured_unreachable_never_silently_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GENESIS_ENV", "dev")
    monkeypatch.setenv("GENESIS_SESSION_BACKEND", "auto")
    monkeypatch.setenv("GENESIS_REDIS_AUTH_MODE", "url")
    monkeypatch.setenv("GENESIS_REDIS_URL", "redis://127.0.0.1:1/0")
    with pytest.raises(RuntimeError, match="unavailable"):
        build_session_store()


def test_catalog_personal_map_roundtrip() -> None:
    s = SessionState(
        customer_id="X",
        catalog_personal_map={"multicredito": "M1"},
        pending_tasks=[{"task_id": "t1", "fields": ["balance", "due_date"]}],
        compare_set=["visa_platinum", "visa_infinite"],
    )
    restored = session_from_dict(session_to_dict(s))
    assert restored.catalog_personal_map == {"multicredito": "M1"}
    assert restored.pending_tasks[0]["fields"] == ["balance", "due_date"]
    assert restored.compare_set == ["visa_platinum", "visa_infinite"]


def test_diagnose_reports_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_SESSION_BACKEND", "memory")
    monkeypatch.delenv("GENESIS_REDIS_URL", raising=False)
    monkeypatch.delenv("GENESIS_CONV_LOCK_REDIS_URL", raising=False)
    d = diagnose_redis_backends()
    assert d["session_backend"] == "memory"
    assert d["lock_backend"] == "local"
    assert "auth_mode" in d


def test_auth_mode_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_REDIS_AUTH_MODE", "entra_managed_identity")
    assert redis_auth_mode() == "entra_managed_identity"
