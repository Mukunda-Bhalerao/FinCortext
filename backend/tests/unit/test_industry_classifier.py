"""Unit tests: IndustryClassifier resolution order (no network, no Gemini).

Covers: static-universe priority, Nifty 500 CSV hit (symbol + ISIN),
unknown symbols return None honestly (the Gemini research path remains the
enrichment source outside the CSV), peer selection (excludes self, EQ-only,
cap), and missing CSV file degradation.
"""

import pytest

from app.data.universe.industry_classifier import (
    CSV_CONFIDENCE,
    IndustryClassifier,
)

CSV_TEXT = """Company Name,Industry,Symbol,Series,ISIN Code
Adani Power Ltd.,Power,ADANIPOWER,EQ,INE814H01029
Tata Power Co. Ltd.,Power,TATAPOWER,EQ,INE245A01021
NTPC Ltd.,Power,NTPC,EQ,INE733E01010
Power Grid Corporation of India Ltd.,Power,POWERGRID,EQ,INE752E01010
Bharat Bijlee Ltd.,Capital Goods,BBL,BE,INE464A01028
Zomato Ltd.,Consumer Services,ZOMATO,EQ,INE758T01015
"""


@pytest.fixture()
def csv_path(tmp_path):
    path = tmp_path / "nifty500_industry.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return path


@pytest.fixture()
def classifier(csv_path):
    return IndustryClassifier(csv_path=csv_path)


# -- resolution order ------------------------------------------------------------


def test_static_universe_wins(classifier):
    result = classifier.classify("TCS")
    assert result is not None
    assert result.sector == "Information Technology"
    assert result.source == "universe"
    assert result.confidence == 1.0


def test_csv_hit_by_symbol(classifier):
    result = classifier.classify("ADANIPOWER", company_name="ADANI POWER LTD")
    assert result is not None
    assert result.sector == "Power"
    assert result.industry == "Power"
    assert result.source == "nse_nifty500_csv"
    assert result.confidence == CSV_CONFIDENCE
    assert result.isin == "INE814H01029"
    assert result.company_name == "Adani Power Ltd."


def test_csv_hit_by_isin(classifier):
    # Symbol not in CSV under this spelling, but ISIN matches.
    result = classifier.classify("NOPE", isin="INE733E01010")
    assert result is not None
    assert result.symbol == "NOPE"
    assert result.industry == "Power"


def test_csv_hit_case_insensitive(classifier):
    assert classifier.classify("adanipower").industry == "Power"


def test_unknown_symbol_returns_none_honestly(classifier):
    """No structured source knows the symbol: None (callers try the next
    enrichment source — Gemini research — then honest UNAVAILABLE)."""
    assert classifier.classify("ZZZNOTREAL") is None
    assert classifier.classify("") is None
    # BBL IS in the CSV (classified by symbol; only peer selection filters
    # the BE series) — a CSV hit classifies regardless of series.
    assert classifier.classify("BBL").industry == "Capital Goods"


def test_missing_csv_returns_none_honestly(tmp_path):
    classifier = IndustryClassifier(csv_path=tmp_path / "missing.csv")
    assert classifier.row_count() == 0
    assert classifier.classify("ANYTHING") is None


# -- peers -------------------------------------------------------------------------


def test_peers_for_industry_excludes_self_and_caps(classifier):
    peers = classifier.peers_for_industry("Power", exclude={"ADANIPOWER"}, limit=2)
    assert len(peers) == 2
    assert all(s != "ADANIPOWER" for s, _ in peers)
    assert all(s in {"TATAPOWER", "NTPC", "POWERGRID"} for s, _ in peers)


def test_peers_empty_for_unknown_industry(classifier):
    assert classifier.peers_for_industry("No Such Industry") == []
    assert classifier.peers_for_industry("") == []


def test_peers_be_series_excluded(classifier):
    # Fixture BBL row is Series BE: never offered as a peer.
    peers = classifier.peers_for_industry("Capital Goods", limit=10)
    assert all(s != "BBL" for s, _ in peers)


def test_committed_csv_loads():
    """The committed NSE file parses with the expected shape."""
    clf = IndustryClassifier()
    assert clf.row_count() >= 400
    adani = clf.classify("ADANIPOWER")
    assert adani is not None and adani.industry == "Power"
    peers = clf.peers_for_industry("Power", exclude={"ADANIPOWER"})
    assert len(peers) >= 2
