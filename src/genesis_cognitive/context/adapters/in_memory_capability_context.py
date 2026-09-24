"""In-memory CapabilityContextProvider — wraps CapabilityCatalog."""

from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
from genesis_cognitive.decision.capability_types import CapabilityManifest, CapabilityQueryContext


class InMemoryCapabilityContextProvider:
    def __init__(self, catalog: CapabilityCatalog | None = None) -> None:
        self._catalog = catalog or CapabilityCatalog()

    async def get_effective_capabilities(
        self, context: CapabilityQueryContext
    ) -> tuple[CapabilityManifest, ...]:
        return self._catalog.get_effective_capabilities(context)
