"""Unit tests for Industry Analyst methodology math."""

import pytest

from app.agents.industry.methodology import (
    WEIGHTS,
    annualized_volatility,
    combine_factor_scores,
    linear_score,
    median,
)


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_median_odd_and_even():
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 3.0, 2.0]) == 2.5
    assert median([]) is None


def test_annualized_volatility():
    assert annualized_volatility([]) is None
    assert annualized_volatility([0.01]) is None
    # Constant returns → zero volatility
    assert annualized_volatility([0.01] * 10) == 0.0
    # Varied returns → positive volatility
    vol = annualized_volatility([0.01, -0.01, 0.02, -0.02, 0.01])
    assert vol is not None and vol > 0


def test_linear_score_relative_strength():
    # -10pp → 0, +10pp → 100
    assert linear_score(-0.10, -0.10, 0.10) == 0.0
    assert linear_score(0.0, -0.10, 0.10) == 50.0
    assert linear_score(0.10, -0.10, 0.10) == 100.0


def test_combine_industry_factors():
    from app.agents.industry.methodology import FactorComputation

    comps = [
        FactorComputation("peer_momentum", 0.05, 62.5, True, "d"),
        FactorComputation("relative_strength", 0.02, 60.0, True, "d"),
        FactorComputation("peer_fundamentals", 0.01, 55.0, True, "d"),
        FactorComputation("sector_volatility", 0.8, 40.0, True, "d"),
    ]
    score, confidence = combine_factor_scores(comps)
    assert score is not None and 0 <= score <= 100
    assert confidence == 0.9  # all 4 available

    # Deterministic
    s2, c2 = combine_factor_scores(comps)
    assert (s2, c2) == (score, confidence)