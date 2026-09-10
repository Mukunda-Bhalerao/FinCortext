"""Unit tests: macro methodology pure functions (deterministic math only)."""

from datetime import date

import pytest

from app.agents.macro import methodology as M


def test_sign_of_respects_floor():
    assert M.sign_of(0.05, 0.01) == 1
    assert M.sign_of(-0.05, 0.01) == -1
    assert M.sign_of(0.005, 0.01) == 0
    assert M.sign_of(0.0) == 0


def test_slope_sign_needs_trend_not_noise():
    assert M.slope_sign([1.0, 2.0, 3.0, 4.0]) == 1
    assert M.slope_sign([4.0, 3.0, 2.0, 1.0]) == -1
    assert M.slope_sign([2.0, 2.0, 2.0]) == 0
    assert M.slope_sign([2.0]) == 0
    assert M.slope_sign([]) == 0


def test_majority_signal_counts_votes_not_weights():
    assert M.majority_signal([1, 1, 0, -1]) == "positive"
    assert M.majority_signal([-1, -1, 1]) == "negative"
    assert M.majority_signal([1, -1]) == "neutral"
    assert M.majority_signal([0, 0]) == "neutral"
    assert M.majority_signal([]) == "neutral"


def test_combine_confidence_weights_documented_components():
    # Full marks on everything → 1.0.
    assert M.combine_confidence(1.0, 1.0, 1.0) == 1.0
    # Empty coverage can never look confident.
    assert M.combine_confidence(0.0, 1.0, 1.0) == 0.5
    assert M.combine_confidence(0.0, 0.0, 0.0) == 0.0
    # Deterministic rounding.
    assert M.combine_confidence(6 / 7, 1.0, 0.5) == round(0.5 * 6 / 7 + 0.3 + 0.1, 2)


def test_factor_confidence_rewards_full_fresh_inputs():
    assert M.factor_confidence(True, True) == 0.9
    assert M.factor_confidence(True, False) == 0.6
    assert M.factor_confidence(False, True) == 0.6
    assert M.factor_confidence(False, False) == 0.5


def test_is_fresh_uses_per_series_windows():
    today = date(2026, 9, 10)
    assert M.is_fresh(date(2026, 9, 9), 14, today) is True
    assert M.is_fresh(date(2026, 8, 1), 14, today) is False
    # Quarterly GDP from June is still fresh under its 120-day window.
    assert M.is_fresh(date(2026, 6, 30), 120, today) is True
    assert M.is_fresh(None, 120, today) is False


def test_population_std_agreement_measure():
    assert M.population_std([1.0, 1.0, 1.0]) == 0.0
    assert M.population_std([1.0]) == 0.0
    assert M.population_std([1.0, -1.0]) == 1.0


def test_macro_score_rescales_available_votes_only():
    # Empty → None (never a fabricated midpoint).
    assert M.macro_score([]) is None
    # All neutral → exactly 50.
    assert M.macro_score([0, 0, 0]) == 50.0
    # Net positive / negative scale linearly.
    assert M.macro_score([1, 1, 0, -1]) == 62.5  # net +1 of 4
    assert M.macro_score([-1, -1, 1]) == pytest.approx(33.3, abs=0.05)
    assert M.macro_score([1]) == 100.0
    assert M.macro_score([-1]) == 0.0
    # Bounds hold for any vote mix.
    assert 0.0 <= M.macro_score([1, 1, 1, -1, 0]) <= 100.0


def test_signal_from_macro_score_matches_majority():
    # Score and majority vote always agree (both reduce to the sign of net).
    cases = [[1, 1, 0, -1], [-1, -1, 1], [1, -1], [0, 0], [1], [-1, -1, -1, 1, 1, 1]]
    for votes in cases:
        assert M.signal_from_macro_score(M.macro_score(votes)) == M.majority_signal(votes)
    assert M.signal_from_macro_score(50.0) == "neutral"
    assert M.signal_from_macro_score(50.1) == "positive"
    assert M.signal_from_macro_score(49.9) == "negative"
