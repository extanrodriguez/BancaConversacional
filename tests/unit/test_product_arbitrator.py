"""Unit tests for ProductIntentArbitrator — no model, no network."""

from genesis_cognitive.router.domain_classifier import DomainScore
from genesis_cognitive.router.product_arbitrator import ProductIntentArbitrator


def _arb() -> ProductIntentArbitrator:
    return ProductIntentArbitrator(margin=0.25)


def test_read_wins():
    result = _arb().arbitrate(
        read=DomainScore(score=0.9), mutation=DomainScore(score=0.1)
    )
    assert result.intent == "read"


def test_mutation_wins():
    result = _arb().arbitrate(
        read=DomainScore(score=0.1), mutation=DomainScore(score=0.9)
    )
    assert result.intent == "mutation"


def test_ambiguous_equal():
    result = _arb().arbitrate(
        read=DomainScore(score=0.5), mutation=DomainScore(score=0.5)
    )
    assert result.intent == "ambiguous"


def test_ambiguous_within_margin():
    # diff = 0.2 < margin 0.25
    result = _arb().arbitrate(
        read=DomainScore(score=0.6), mutation=DomainScore(score=0.4)
    )
    assert result.intent == "ambiguous"


def test_read_wins_at_boundary():
    # diff = 0.26 > margin 0.25
    result = _arb().arbitrate(
        read=DomainScore(score=0.63), mutation=DomainScore(score=0.37)
    )
    assert result.intent == "read"


def test_mutation_wins_at_boundary():
    result = _arb().arbitrate(
        read=DomainScore(score=0.3), mutation=DomainScore(score=0.56)
    )
    assert result.intent == "mutation"


def test_scores_preserved():
    result = _arb().arbitrate(
        read=DomainScore(score=0.85), mutation=DomainScore(score=0.12)
    )
    assert result.read_score == 0.85
    assert result.mutation_score == 0.12
