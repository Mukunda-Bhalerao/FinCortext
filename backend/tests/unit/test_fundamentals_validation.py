"""Unit tests: fundamentals validation rules (finite, sane, reported)."""

import math

from app.data.validation.fundamentals_validation import (
    validate_fundamental_value,
    validate_metrics,
)


def test_valid_values_pass():
    assert validate_fundamental_value("total_revenue", 1_000_000.0) is None
    assert validate_fundamental_value("total_debt", 0.0) is None
    # Losses and negative ROE are real — never rejected.
    assert validate_fundamental_value("net_income", -500.0) is None
    assert validate_fundamental_value("roe", -0.05) is None
    assert validate_fundamental_value("pe_ratio", 22.5) is None


def test_missing_and_nonfinite_rejected():
    assert validate_fundamental_value("total_revenue", None) is not None
    assert validate_fundamental_value("net_income", float("nan")) is not None
    assert validate_fundamental_value("total_revenue", float("inf")) is not None
    assert validate_fundamental_value("net_income", "lots") is not None
    assert validate_fundamental_value("net_income", True) is not None


def test_impossible_values_rejected_with_reasons():
    # Negative revenue/assets/debt are data errors, not losses.
    assert "negative" in validate_fundamental_value("total_revenue", -1.0)
    assert "negative" in validate_fundamental_value("total_assets", -1.0)
    assert "negative" in validate_fundamental_value("total_debt", -1.0)
    # Zero/negative P/E is meaningless for scoring.
    assert validate_fundamental_value("pe_ratio", 0.0) is not None
    assert validate_fundamental_value("pe_ratio", -5.0) is not None


def test_validate_metrics_splits_valid_and_rejected():
    result = validate_metrics(
        {
            "total_revenue": 1000.0,
            "net_income": -50.0,
            "total_debt": float("nan"),
            "pe_ratio": 0.0,
            "roe": 0.19,
        }
    )
    assert result.valid == {"total_revenue": 1000.0, "net_income": -50.0, "roe": 0.19}
    rejected = {r["metric"]: r["reason"] for r in result.rejected}
    assert set(rejected) == {"total_debt", "pe_ratio"}
    assert all(isinstance(reason, str) and reason for reason in rejected.values())
    assert math.isfinite(result.valid["net_income"])  # losses stay usable
