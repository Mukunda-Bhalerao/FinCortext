"""Unit tests: portfolio synthesis rules (deterministic, no blending)."""

from app.agents.portfolio import methodology as M


def test_direction_mapping_keeps_vocabularies_separate():
    assert M.direction_of("analyst", "buy", 62.0) == "positive"
    assert M.direction_of("analyst", "strong_buy", 80.0) == "positive"
    assert M.direction_of("analyst", "neutral", 50.0) == "neutral"
    assert M.direction_of("analyst", "sell", 35.0) == "negative"
    assert M.direction_of("analyst", "strong_sell", 10.0) == "negative"
    assert M.direction_of("macro", "positive", 60.0) == "positive"
    assert M.direction_of("macro", "negative", 40.0) == "negative"
    assert M.direction_of("macro", "neutral", 50.0) == "neutral"


def test_missing_inputs_are_excluded_never_neutral():
    # Null score on an analyst output means missing, even with a signal string.
    assert M.direction_of("analyst", "buy", None) is None
    assert M.direction_of("analyst", "unavailable", None) is None
    assert M.direction_of("macro", "unavailable", None) is None
    assert M.direction_of("macro", "neutral", None) == "neutral"


def test_agreement_verdicts():
    verdict, _ = M.agreement_of(["positive", "positive"])
    assert verdict == "unanimous-positive"
    verdict, _ = M.agreement_of(["negative", "negative", "negative"])
    assert verdict == "unanimous-negative"
    verdict, _ = M.agreement_of(["neutral", "neutral"])
    assert verdict == "unanimous-neutral"
    verdict, _ = M.agreement_of(["positive", "positive", "negative"])
    assert verdict == "majority-positive"
    verdict, _ = M.agreement_of(["negative", "negative", "positive"])
    assert verdict == "majority-negative"
    verdict, _ = M.agreement_of(["positive", "negative"])
    assert verdict == "mixed"
    verdict, summary = M.agreement_of(["positive"])
    assert verdict == "insufficient"
    assert "fewer than two" in summary.lower()
    verdict, _ = M.agreement_of([])
    assert verdict == "insufficient"


def test_combine_confidence_scales_by_coverage():
    assert M.combine_confidence([0.8, 0.8, 0.8, 0.8], 4) == 0.8
    # Same mean confidence, thinner coverage → lower confidence.
    assert M.combine_confidence([0.8, 0.8], 2) == 0.4
    assert M.combine_confidence([], 0) == 0.0
