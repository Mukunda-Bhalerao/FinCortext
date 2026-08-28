"""Unit tests for Firm Analyst methodology math and scoring."""

import pytest

from app.agents.firm.methodology import (
    DE_MAX,
    DE_MIN,
    FactorComputation,
    GROWTH_MAX,
    GROWTH_MIN,
    NET_MARGIN_MAX,
    NET_MARGIN_MIN,
    WEIGHTS,
    combine_factor_scores,
    linear_score,
)


# --- linear_score ---------------------------------------------------------------


def test_linear_score_bounds_and_clamping():
    assert linear_score(0.0, 0.0, 0.20) == 0.0
    assert linear_score(0.20, 0.0, 0.20) == 100.0
    assert linear_score(0.10, 0.0, 0.20) == 50.0
    # Clamped beyond bounds
    assert linear_score(0.50, 0.0, 0.20) == 100.0
    assert linear_score(-0.5, 0.0, 0.20) == 0.0


def test_linear_score_reversed_direction():
    # Debt: high is bad (worst=2.0, best=0.0)
    assert linear_score(2.0, DE_MAX, DE_MIN) == 0.0
    assert linear_score(0.0, DE_MAX, DE_MIN) == 100.0
    assert linear_score(1.0, DE_MAX, DE_MIN) == 50.0


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


# --- combine_factor_scores ----------------------------------------------------------


def _comp(name, points, available=True):
    return FactorComputation(name, 1.0 if available else None, points, available, "d")


def test_combine_all_available():
    comps = [_comp(n, 80.0) for n in WEIGHTS]
    score, confidence = combine_factor_scores(comps)
    assert score == 80.0
    assert confidence == 0.9  # 5+ factors → quality 0.9, full coverage


def test_combine_redistributes_missing_weights():
    comps = [_comp(n, 80.0) for n in WEIGHTS]
    comps = [c for c in comps if c.name != "valuation"]  # drop one (weight 0.10)
    score, confidence = combine_factor_scores(comps)
    assert score == 80.0  # redistribution keeps the same average
    assert confidence == pytest.approx(0.9 * 0.9, abs=0.01)  # 0.9 coverage × 0.9 quality


def test_combine_no_factors_available():
    comps = [_comp(n, None, available=False) for n in WEIGHTS]
    score, confidence = combine_factor_scores(comps)
    assert score is None
    assert confidence == 0.0


def test_combine_deterministic():
    comps = [_comp(n, 60.0 + i) for i, n in enumerate(WEIGHTS)]
    s1, c1 = combine_factor_scores(comps)
    s2, c2 = combine_factor_scores(comps)
    assert (s1, c1) == (s2, c2)


def test_combine_confidence_tiers():
    # 2 available factors → quality 0.6
    comps = [_comp(n, 50.0) for n in WEIGHTS]
    two = [c for c in comps if c.name in {"profitability", "financial_health"}]
    _, conf2 = combine_factor_scores(two)
    assert conf2 == pytest.approx(0.45 * 0.6, abs=0.01)
    # 3-4 available → quality 0.75
    three = [c for c in comps if c.name in {"profitability", "financial_health", "valuation"}]
    _, conf3 = combine_factor_scores(three)
    assert conf3 == pytest.approx(0.55 * 0.75, abs=0.01)