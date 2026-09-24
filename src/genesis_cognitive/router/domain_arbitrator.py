"""DomainArbitrator — deterministic code-based domain decision from classifier scores."""

from __future__ import annotations

from dataclasses import dataclass

from genesis_cognitive.router.domain_classifier import DomainScore


@dataclass(frozen=True)
class ArbitrationResult:
    """Result of domain arbitration."""

    domain: str  # "own_product" | "business" | "ood" | "ambiguous" | "non_operational"
    own_score: float
    business_score: float
    ood_score: float


class DomainArbitrator:
    """Deterministic arbitrator over three domain classifier scores.

    Rules (in priority order):
    1. ood >= OOD_THRESHOLD → "ood"
    2. All scores < NON_OP_THRESHOLD → "non_operational"
    3. business > own + MARGIN → "business"
    4. own > business + MARGIN → "own_product"
    5. Otherwise → "ambiguous"
    """

    def __init__(
        self,
        *,
        ood_threshold: float = 0.7,
        margin: float = 0.2,
        non_op_threshold: float = 0.3,
    ) -> None:
        self.ood_threshold = ood_threshold
        self.margin = margin
        self.non_op_threshold = non_op_threshold

    def arbitrate(
        self,
        own: DomainScore,
        business: DomainScore,
        ood: DomainScore,
    ) -> ArbitrationResult:
        """Determine domain from three scores. Deterministic, no model calls."""
        # 1. OOD wins if above threshold
        if ood.score >= self.ood_threshold:
            return ArbitrationResult("ood", own.score, business.score, ood.score)

        # 2. All low → non_operational (greeting/courtesy)
        if max(own.score, business.score, ood.score) < self.non_op_threshold:
            return ArbitrationResult("non_operational", own.score, business.score, ood.score)

        # 3. Business wins with margin
        if business.score > own.score + self.margin:
            return ArbitrationResult("business", own.score, business.score, ood.score)

        # 4. Own wins with margin
        if own.score > business.score + self.margin:
            return ArbitrationResult("own_product", own.score, business.score, ood.score)

        # 5. Tie → ambiguous
        return ArbitrationResult("ambiguous", own.score, business.score, ood.score)
