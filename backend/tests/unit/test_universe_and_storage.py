"""Unit tests for universe configuration and DuckDB storage/repositories."""

from datetime import date, datetime

import pytest

from app.core.exceptions import NotFoundError
from app.data.storage.duckdb_storage import DuckDBStorage
from app.data.universe.universe_config import (
    UNIVERSE_VERSION,
    get_industry_peers,
    get_sector_peers,
    get_universe,
    get_universe_entry,
)
from app.domain.models.agent_output import AgentId, AgentOutput, Signal
from app.domain.models.financial import FilingDocument, FinancialObservation
from app.domain.models.market import MarketPrice
from app.domain.models.news import NewsArticle, SentimentLabel, SentimentResult
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.repositories.universe_repository import UniverseRepository


# --- Universe -----------------------------------------------------------------


def test_universe_has_ten_entries_with_metadata():
    universe = get_universe()
    assert len(universe) == 10
    for entry in universe:
        assert entry.ticker.endswith(".NS")
        assert entry.sector and entry.industry and entry.name


def test_universe_lookup_and_peers():
    entry = get_universe_entry("reliance")  # case-insensitive
    assert entry.symbol == "RELIANCE"
    peers = get_sector_peers("TCS")
    symbols = {p.symbol for p in peers}
    assert {"TCS", "INFY"} <= symbols
    assert get_industry_peers("HDFCBANK")[0].industry == "Private Sector Bank"


def test_universe_unknown_symbol_raises_not_found():
    with pytest.raises(NotFoundError):
        get_universe_entry("NOPE")


def test_universe_aliases_support_relevance_matching():
    """Curated aliases exist for ticker-style references; ambiguous bare
    forms stay out of `aliases` (LT) or live in `strict_aliases` (Reliance)."""
    assert "TCS" in get_universe_entry("TCS").aliases
    assert "INFY" in get_universe_entry("INFY").aliases
    assert "L&T" in get_universe_entry("LT").aliases
    assert "LT" not in get_universe_entry("LT").aliases
    assert "SBI" in get_universe_entry("SBIN").aliases
    assert "HUL" in get_universe_entry("HINDUNILVR").aliases
    assert "RIL" in get_universe_entry("RELIANCE").aliases
    assert "Reliance" in get_universe_entry("RELIANCE").strict_aliases
    assert "Reliance" not in get_universe_entry("RELIANCE").aliases


# --- Storage fixtures ------------------------------------------------------------


@pytest.fixture()
def storage(tmp_path):
    s = DuckDBStorage(tmp_path / "test.duckdb")
    s.connect()
    yield s
    s.close()


# --- Market repository --------------------------------------------------------------


def test_market_repository_roundtrip_and_upsert(storage):
    repo = MarketRepository(storage)
    bar = MarketPrice(
        symbol="RELIANCE",
        provider_ticker="RELIANCE.NS",
        trade_date=date(2024, 1, 2),
        open=100,
        high=110,
        low=95,
        close=105,
        volume=1000,
    )
    assert repo.upsert_bars([bar]) == 1
    # Upsert same date with new close — replace, not duplicate.
    bar2 = bar.model_copy(update={"close": 106})
    repo.upsert_bars([bar2])
    prices = repo.get_prices("RELIANCE")
    assert len(prices) == 1
    assert prices[0].close == 106
    assert repo.count("RELIANCE") == 1
    assert repo.latest_trade_date("RELIANCE") == date(2024, 1, 2)


# --- Financial repository ---------------------------------------------------------------


def test_financial_repository_point_in_time(storage):
    repo = FinancialRepository(storage)
    old = FinancialObservation(
        entity_id="RELIANCE",
        metric="total_revenue",
        value=100.0,
        source_name="FY2023 filing",
        period_end=date(2023, 3, 31),
        available_at=datetime(2023, 5, 10),
    )
    new = FinancialObservation(
        entity_id="RELIANCE",
        metric="total_revenue",
        value=120.0,
        source_name="FY2024 filing",
        period_end=date(2024, 3, 31),
        available_at=datetime(2024, 6, 20),
    )
    repo.save_observations([old, new])

    # As-of before the new filing was public → only the old value visible.
    obs = repo.get_observations("RELIANCE", as_of=datetime(2024, 1, 1))
    assert len(obs) == 1 and obs[0].value == 100.0

    latest = repo.latest_metric_value("RELIANCE", "total_revenue")
    assert latest is not None and latest.value == 120.0


def test_filing_document_dedup_by_hash(storage):
    repo = FinancialRepository(storage)
    doc = FilingDocument(
        document_id="doc-1",
        entity_id="RELIANCE",
        document_type="csv",
        file_name="r.csv",
        file_path="/tmp/r.csv",
        content_hash="abc123",
        source_name="Annual Report",
    )
    repo.save_document(doc)
    assert repo.document_exists_by_hash("abc123")
    assert not repo.document_exists_by_hash("zzz")


# --- News repository -------------------------------------------------------------------


def test_news_repository_dedup(storage):
    repo = NewsRepository(storage)
    a = NewsArticle(article_id="a1", title="T1", entity_id="RELIANCE", content_hash="h1")
    assert repo.save_articles([a]) == 1
    assert repo.save_articles([a]) == 0  # duplicate skipped
    assert repo.count("RELIANCE") == 1


def test_sentiment_results_roundtrip(storage):
    repo = NewsRepository(storage)
    s = SentimentResult(
        article_id="a1",
        entity_id="RELIANCE",
        label=SentimentLabel.POSITIVE,
        positive_probability=0.8,
        neutral_probability=0.1,
        negative_probability=0.1,
        model_id="test-model",
        model_confidence=0.8,
    )
    repo.save_sentiment_results([s])
    got = repo.get_sentiment_results("RELIANCE")
    assert len(got) == 1 and got[0].label == SentimentLabel.POSITIVE


# --- Agent output repository --------------------------------------------------------------


def test_agent_output_persistence(storage):
    repo = AgentOutputRepository(storage)
    out = AgentOutput(
        agent_id=AgentId.FIRM_ANALYST,
        entity_id="RELIANCE",
        score=58.0,
        signal=Signal.BUY,
        confidence=0.6,
        rationale="r",
    )
    output_id = repo.save(out)
    assert output_id
    rows = repo.list_outputs(agent_id="firm_analyst", entity_id="RELIANCE")
    assert len(rows) == 1
    assert rows[0]["score"] == 58.0
    assert repo.latest_output("firm_analyst", "RELIANCE") is not None


# --- Concurrent writes (startup + requests race) ---------------------------------------
# Regression: repository writes used to call storage.connect().execute()
# directly, bypassing the storage lock. Concurrent requests sharing one
# connection then failed with "TransactionContext ... Conflict on update!"
# (universe sync) and ConstraintException (quote upserts). All writes must
# go through the locked helpers.


def test_concurrent_writes_do_not_conflict(tmp_path):
    import threading

    from app.repositories.universe_repository import UniverseRepository

    storage = DuckDBStorage(tmp_path / "concurrent.duckdb")
    storage.connect()
    market_repo = MarketRepository(storage)
    universe_repo = UniverseRepository(storage)
    errors: list = []

    def bars(n: int):
        return [
            MarketPrice(
                symbol="TCS",
                provider_ticker="TCS.NS",
                trade_date=date(2024, 1, 2),
                open=100,
                high=110,
                low=95,
                close=100 + n,
                volume=1000,
            )
        ]

    def quote(n: int):
        return {
            "symbol": "TCS",
            "instrument_key": "NSE_EQ|INE467B01029",
            "source": "upstox",
            "timestamp": f"2026-09-28T10:{n:02d}:00+05:30",
            "last_price": 3000.0 + n,
        }

    def worker(n: int):
        try:
            for _ in range(5):
                universe_repo.sync_from_config()
                market_repo.upsert_bars(bars(n))
                market_repo.upsert_quote(quote(n))
        except Exception as exc:  # noqa: BLE001 — collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not [t for t in threads if t.is_alive()]
    assert errors == []
    assert market_repo.count("TCS") == 1  # upsert, never duplicates
    assert market_repo.get_stored_quote("TCS") is not None
    storage.close()


# --- Startup sync guard (skip-when-in-sync + conflict retry) ----------------------
# Regression: concurrent startup workers sharing one DuckDB file failed with
# "Universe sync failed: TransactionContext Error: Conflict on update!".


def test_sync_skips_write_when_already_in_sync(storage):
    urepo = UniverseRepository(storage)
    assert urepo.sync_from_config() == 10  # first sync writes
    assert urepo.sync_from_config() == 0  # repeat startup: zero writes
    assert len(urepo.list_entries()) == 10


def test_sync_retries_transient_conflicts(storage, monkeypatch):
    from app.core.exceptions import StorageError

    urepo = UniverseRepository(storage)
    calls = {"n": 0}
    real = DuckDBStorage.executemany

    def flaky(self, sql, rows=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise StorageError("SQL failed: TransactionContext Error: Conflict on update!")
        return real(self, sql, rows)

    monkeypatch.setattr(DuckDBStorage, "executemany", flaky)
    assert urepo.sync_from_config() == 10
    assert calls["n"] == 3
    assert len(urepo.list_entries()) == 10


def test_sync_reraises_non_transient_errors(storage, monkeypatch):
    from app.core.exceptions import StorageError

    urepo = UniverseRepository(storage)
    monkeypatch.setattr(
        DuckDBStorage,
        "executemany",
        lambda self, sql, rows=None: (_ for _ in ()).throw(
            StorageError("SQL failed: some real corruption")
        ),
    )
    with pytest.raises(StorageError):
        urepo.sync_from_config()


# --- Universe mirror + provenance ------------------------------------------------------------


def test_universe_mirror_and_provenance(storage):
    urepo = UniverseRepository(storage)
    assert urepo.sync_from_config() == 10
    entries = urepo.list_entries()
    assert len(entries) == 10

    prepo = ProvenanceRepository(storage)
    event_id = prepo.record(
        "market_refresh",
        entity_id="RELIANCE",
        source_type="legacy_import",
        source_name="legacy_import",
        rows_ingested=250,
    )
    assert event_id
    events = prepo.list_events(entity_id="RELIANCE")
    assert events[0]["rows_ingested"] == 250