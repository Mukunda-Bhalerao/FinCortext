"""Unit tests: macro bundle validation (finite, dated, de-duplicated)."""

from datetime import date

from app.data.validation.macro_validation import validate_bundle


def _bundle(points, unit="%"):
    return {"unit": unit, "source_name": "test", "points": points}


def test_valid_points_pass_sorted():
    out = validate_bundle(
        "cpi_yoy",
        _bundle(
            [
                {"period_end": "2026-07-31", "value": 4.45},
                {"period_end": "2026-06-30", "value": 4.38},
            ]
        ),
    )
    assert len(out.points) == 2
    assert out.points[0]["period_end"] == date(2026, 6, 30)
    assert out.points[1]["value"] == 4.45
    assert out.rejected == []


def test_missing_unit_rejects_whole_bundle():
    out = validate_bundle("cpi_yoy", {"unit": "", "points": [{"period_end": "2026-07-31", "value": 1.0}]})
    assert out.points == []
    assert any("unit" in r["reason"] for r in out.rejected)


def test_bad_values_rejected_with_reasons():
    out = validate_bundle(
        "gdp_real_yoy",
        _bundle(
            [
                {"period_end": "2026-06-30", "value": 7.8},
                {"period_end": "2026-03-31", "value": None},
                {"period_end": "2025-12-31", "value": float("nan")},
                {"period_end": "2025-09-30", "value": "high"},
            ]
        ),
    )
    assert len(out.points) == 1
    assert len(out.rejected) == 3
    assert all(r["reason"] for r in out.rejected)


def test_future_periods_rejected_not_shifted():
    out = validate_bundle(
        "repo_rate",
        _bundle([{"period_end": "2999-01-01", "value": 5.0}]),
        today=date(2026, 9, 10),
    )
    assert out.points == []
    assert any("future" in r["reason"] for r in out.rejected)


def test_duplicate_periods_keep_first_and_report_rest():
    out = validate_bundle(
        "cpi_yoy",
        _bundle(
            [
                {"period_end": "2026-07-31", "value": 4.45},
                {"period_end": "2026-07-31", "value": 4.50},
            ]
        ),
    )
    assert len(out.points) == 1
    assert out.points[0]["value"] == 4.45
    assert any("duplicate" in r["reason"] for r in out.rejected)


def test_unparseable_period_rejected():
    out = validate_bundle(
        "cpi_yoy", _bundle([{"period_end": "not-a-date", "value": 1.0}])
    )
    assert out.points == []
    assert out.rejected
