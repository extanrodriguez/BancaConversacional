"""RouteTable — deterministic mapping from selected_route to family and action."""

from genesis_cognitive.enums import InteractionFamily, NextAction, SelectedRoute
from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError

_TABLE: dict[SelectedRoute, tuple[InteractionFamily, NextAction]] = {
    SelectedRoute.BUSINESS_RAG: (InteractionFamily.KNOWLEDGE, NextAction.QUERY_RAG),
    SelectedRoute.PORTFOLIO_QUERY: (InteractionFamily.PORTFOLIO, NextAction.QUERY_PORTFOLIO),
    SelectedRoute.PERSONAL_READ: (InteractionFamily.PERSONAL_READ, NextAction.BUILD_READ_REQUEST),
    SelectedRoute.TRANSFER_CONTRACT_BUILDER: (
        InteractionFamily.TRANSACTION,
        NextAction.BUILD_TYPED_CONTRACT,
    ),
    SelectedRoute.CLARIFICATION: (InteractionFamily.CLARIFICATION, NextAction.ASK_CLARIFICATION),
    SelectedRoute.UNSUPPORTED: (InteractionFamily.UNSUPPORTED, NextAction.RETURN_UNSUPPORTED),
}


class RouteTable:
    """Deterministic route → (interaction_family, next_action) lookup."""

    def complete(self, selected_route: SelectedRoute) -> tuple[InteractionFamily, NextAction]:
        """Return (interaction_family, next_action) for a valid route."""
        result = _TABLE.get(selected_route)
        if result is None:
            raise InvalidModelOutputError()
        return result
