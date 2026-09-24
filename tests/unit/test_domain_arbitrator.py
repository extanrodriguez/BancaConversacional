"""Unit tests for DomainArbitrator — no model, no network."""

from genesis_cognitive.router.domain_arbitrator import ArbitrationResult, DomainArbitrator
from genesis_cognitive.router.domain_classifier import DomainScore


def _arb() -> DomainArbitrator:
    return DomainArbitrator(ood_threshold=0.7, margin=0.2, non_op_threshold=0.3)


def test_ood_wins():
    result = _arb().arbitrate(
        own=DomainScore(score=0.1),
        business=DomainScore(score=0.1),
        ood=DomainScore(score=0.9),
    )
    assert result.domain == "ood"
    assert result.ood_score == 0.9


def test_own_product_wins():
    result = _arb().arbitrate(
        own=DomainScore(score=0.8),
        business=DomainScore(score=0.2),
        ood=DomainScore(score=0.0),
    )
    assert result.domain == "own_product"
    assert result.own_score == 0.8


def test_business_wins():
    result = _arb().arbitrate(
        own=DomainScore(score=0.2),
        business=DomainScore(score=0.8),
        ood=DomainScore(score=0.0),
    )
    assert result.domain == "business"
    assert result.business_score == 0.8


def test_ambiguous_tie():
    result = _arb().arbitrate(
        own=DomainScore(score=0.5),
        business=DomainScore(score=0.5),
        ood=DomainScore(score=0.1),
    )
    assert result.domain == "ambiguous"


def test_non_operational_all_low():
    result = _arb().arbitrate(
        own=DomainScore(score=0.1),
        business=DomainScore(score=0.1),
        ood=DomainScore(score=0.1),
    )
    assert result.domain == "non_operational"


def test_ood_threshold_exact():
    result = _arb().arbitrate(
        own=DomainScore(score=0.5),
        business=DomainScore(score=0.5),
        ood=DomainScore(score=0.7),
    )
    assert result.domain == "ood"


def test_margin_boundary_own():
    # own=0.5, biz=0.3 → diff=0.2 == margin → NOT own (needs strictly greater)
    result = _arb().arbitrate(
        own=DomainScore(score=0.5),
        business=DomainScore(score=0.3),
        ood=DomainScore(score=0.0),
    )
    assert result.domain == "ambiguous"


def test_margin_boundary_own_wins():
    # own=0.51, biz=0.3 → diff=0.21 > margin → own wins
    result = _arb().arbitrate(
        own=DomainScore(score=0.51),
        business=DomainScore(score=0.3),
        ood=DomainScore(score=0.0),
    )
    assert result.domain == "own_product"


def test_custom_thresholds():
    arb = DomainArbitrator(ood_threshold=0.5, margin=0.1, non_op_threshold=0.2)
    result = arb.arbitrate(
        own=DomainScore(score=0.4),
        business=DomainScore(score=0.25),
        ood=DomainScore(score=0.1),
    )
    assert result.domain == "own_product"  # 0.4 > 0.25 + 0.1
