"""Port: CapabilityContextProvider."""

from typing import Protocol, runtime_checkable

from genesis_cognitive.decision.capability_types import CapabilityManifest, CapabilityQueryContext


@runtime_checkable
class CapabilityContextProvider(Protocol):
    async def get_effective_capabilities(
        self, context: CapabilityQueryContext
    ) -> tuple[CapabilityManifest, ...]: ...
