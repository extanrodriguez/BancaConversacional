"""T06 — RouteTable tests."""

import pytest

from genesis_cognitive.decision.route_table import RouteTable
from genesis_cognitive.enums import InteractionFamily, NextAction, SelectedRoute


@pytest.fixture()
def table() -> RouteTable:
    return RouteTable()


class TestRouteTable:
    def test_business_rag(self, table: RouteTable) -> None:
        f, a = table.complete(SelectedRoute.BUSINESS_RAG)
        assert f == InteractionFamily.KNOWLEDGE
        assert a == NextAction.QUERY_RAG

    def test_portfolio_query(self, table: RouteTable) -> None:
        f, a = table.complete(SelectedRoute.PORTFOLIO_QUERY)
        assert f == InteractionFamily.PORTFOLIO
        assert a == NextAction.QUERY_PORTFOLIO

    def test_personal_read(self, table: RouteTable) -> None:
        f, a = table.complete(SelectedRoute.PERSONAL_READ)
        assert f == InteractionFamily.PERSONAL_READ
        assert a == NextAction.BUILD_READ_REQUEST

    def test_transfer(self, table: RouteTable) -> None:
        f, a = table.complete(SelectedRoute.TRANSFER_CONTRACT_BUILDER)
        assert f == InteractionFamily.TRANSACTION
        assert a == NextAction.BUILD_TYPED_CONTRACT

    def test_clarification(self, table: RouteTable) -> None:
        f, a = table.complete(SelectedRoute.CLARIFICATION)
        assert f == InteractionFamily.CLARIFICATION
        assert a == NextAction.ASK_CLARIFICATION

    def test_unsupported(self, table: RouteTable) -> None:
        f, a = table.complete(SelectedRoute.UNSUPPORTED)
        assert f == InteractionFamily.UNSUPPORTED
        assert a == NextAction.RETURN_UNSUPPORTED

    def test_exactly_six_routes(self, table: RouteTable) -> None:
        for route in SelectedRoute:
            table.complete(route)  # All 6 must work
