"""Market overview, sector board, movers, watchlist and stock summaries."""

from datetime import UTC, datetime

from app.db import Database
from app.errors import AppError
from app.schemas.market import Instrument, LabeledQuote, Movers, Quote, StockSummary
from app.services.candles import CandleService
from app.services.instruments import MOVERS_UNIVERSE, InstrumentService
from app.services.quotes import QuoteService
from app.tools.candles import trailing_range

MOVERS_COUNT = 8


def rank_movers(
    items: list[tuple[Instrument, Quote]], count: int = MOVERS_COUNT
) -> tuple[list, list, list, tuple[int, int, int]]:
    """Gainers/losers by % change, most active by traded value (volume x average price)."""
    priced = [(i, q) for i, q in items if q.change_pct is not None]
    gainers = sorted(
        (x for x in priced if x[1].change_pct > 0), key=lambda x: x[1].change_pct, reverse=True
    )[:count]
    losers = sorted((x for x in priced if x[1].change_pct < 0), key=lambda x: x[1].change_pct)[
        :count
    ]

    def traded_value(q: Quote) -> float:
        return (q.volume or 0) * (q.avg_price or q.ltp or 0)

    active = sorted(
        (x for x in items if x[1].volume), key=lambda x: traded_value(x[1]), reverse=True
    )[:count]
    adv = sum(1 for _, q in priced if q.change_pct > 0)
    dec = sum(1 for _, q in priced if q.change_pct < 0)
    return gainers, losers, active, (adv, dec, len(priced) - adv - dec)


class MarketService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        quotes: QuoteService,
        candles: CandleService,
    ):
        self._db = db
        self._instruments = instruments
        self._quotes = quotes
        self._candles = candles

    async def _labeled(self, pairs: list[tuple[str, Instrument]]) -> list[LabeledQuote]:
        quotes = await self._quotes.get([i.instrument_key for _, i in pairs])
        return [
            LabeledQuote(label=label, instrument=i, quote=quotes.get(i.instrument_key))
            for label, i in pairs
        ]

    async def indices(self) -> list[LabeledQuote]:
        pairs = [(label, i) for label, i in self._instruments.headline_indices() if i]
        return await self._labeled(pairs)

    async def sectors(self) -> list[LabeledQuote]:
        return await self._labeled(self._instruments.sector_indices())

    async def movers(self) -> Movers:
        members = self._instruments.constituents(MOVERS_UNIVERSE)
        quotes = await self._quotes.get([m.instrument_key for m in members]) if members else {}
        items = [(m, quotes[m.instrument_key]) for m in members if m.instrument_key in quotes]
        gainers, losers, active, (adv, dec, unch) = rank_movers(items)

        def wrap(rows: list[tuple[Instrument, Quote]]) -> list[LabeledQuote]:
            return [LabeledQuote(label=i.symbol, instrument=i, quote=q) for i, q in rows]

        stamps = [q.fetched_at for _, q in items]
        return Movers(
            universe=MOVERS_UNIVERSE,
            gainers=wrap(gainers),
            losers=wrap(losers),
            most_active=wrap(active),
            advances=adv,
            declines=dec,
            unchanged=unch,
            constituents_total=self._instruments.constituents_expected(MOVERS_UNIVERSE),
            quotes_received=len(items),
            source="upstox.rest.market-quote; constituents: nseindia.com",
            as_of=max(stamps) if stamps else None,
        )

    # --- watchlist ---------------------------------------------------------------

    def watchlist_keys(self) -> list[str]:
        rows = self._db.fetchall("SELECT instrument_key FROM watchlist ORDER BY added_at")
        return [r[0] for r in rows]

    async def watchlist(self) -> list[LabeledQuote]:
        keys = self.watchlist_keys()
        found = self._instruments.get_many(keys)
        pairs = [(found[k].symbol, found[k]) for k in keys if k in found]
        return await self._labeled(pairs) if pairs else []

    def watch(self, instrument_key: str) -> None:
        self._instruments.get(instrument_key)  # validates the key
        self._db.execute(
            "INSERT OR IGNORE INTO watchlist VALUES (?, ?)", [instrument_key, datetime.now(UTC)]
        )

    def unwatch(self, instrument_key: str) -> None:
        self._db.execute("DELETE FROM watchlist WHERE instrument_key = ?", [instrument_key])

    # --- stock page --------------------------------------------------------------

    async def summary(self, instrument: Instrument) -> StockSummary:
        """Instrument identity always; quote and 52-week range only when the provider answers."""
        problems: list[str] = []
        quote = None
        try:
            quote = (await self._quotes.get([instrument.instrument_key])).get(
                instrument.instrument_key
            )
        except AppError as exc:
            problems.append(exc.message)
        high = low = basis = None
        try:
            daily = await self._candles.series(instrument.instrument_key, "1D")
            rng = trailing_range(daily.candles, datetime.now(UTC))
            if rng:
                high, low = rng
                basis = "Daily candles, trailing 365 days"
        except AppError as exc:
            if exc.message not in problems:
                problems.append(exc.message)
        return StockSummary(
            instrument=instrument,
            quote=quote,
            week52_high=high,
            week52_low=low,
            week52_basis=basis,
            in_watchlist=instrument.instrument_key in self.watchlist_keys(),
            problems=problems,
        )
