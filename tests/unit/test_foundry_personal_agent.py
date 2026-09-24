"""Unit tests for foundry_personal_agent helpers (no live Azure)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from genesis_cognitive.agents.foundry_personal_agent import (
    looks_like_personal_portfolio_query,
)
from genesis_cognitive.agents.product_context_tools import is_foundry_product_tools_enabled


def test_looks_like_personal_portfolio_query() -> None:
    assert looks_like_personal_portfolio_query("lista mis productos")
    assert looks_like_personal_portfolio_query("Cuáles son mis préstamos")
    assert not looks_like_personal_portfolio_query("cuál es la misión del banco")
    assert not looks_like_personal_portfolio_query("")


def test_flag_default_off(monkeypatch) -> None:
    monkeypatch.delenv("GENESIS_FOUNDRY_PRODUCT_TOOLS", raising=False)
    assert is_foundry_product_tools_enabled() is False
    monkeypatch.setenv("GENESIS_FOUNDRY_PRODUCT_TOOLS", "1")
    assert is_foundry_product_tools_enabled() is True
