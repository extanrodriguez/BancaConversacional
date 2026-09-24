"""ProductIntentArbitrator — deterministic read vs mutation decision."""

from __future__ import annotations

from dataclasses import dataclass

from genesis_cognitive.router.domain_classifier import DomainScore


@dataclass(frozen=True)
class ProductArbitrationResult:
    """Result of product intent arbitration."""

    intent: str  # "read" | "mutation" | "ambiguous"
    read_score: float
    mutation_score: float


class ProductIntentArbitrator:
    """Deterministic arbitrator: read vs mutation with margin.

    - mutation > read + margin → "mutation"
    - read > mutation + margin → "read"
    - otherwise → "ambiguous"
    """

    def __init__(self, *, margin: float = 0.25) -> None:
        self.margin = margin

    def arbitrate(
        self, read: DomainScore, mutation: DomainScore
    ) -> ProductArbitrationResult:
        if mutation.score > read.score + self.margin:
            return ProductArbitrationResult("mutation", read.score, mutation.score)
        if read.score > mutation.score + self.margin:
            return ProductArbitrationResult("read", read.score, mutation.score)
        # Tie-break: if read >= mutation and mutation is low, treat as read
        if read.score >= mutation.score and mutation.score < 0.5:
            return ProductArbitrationResult("read", read.score, mutation.score)
        return ProductArbitrationResult("ambiguous", read.score, mutation.score)
