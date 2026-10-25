"""Gathers and caches every input the research agents need, recording why any input is missing."""

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, date, datetime, timedelta
from typing import TypeVar

from app.agents.base import Peer, PriceSeries, ResearchContext
from app.db import Database
from app.errors import AppError, NotFound
from app.providers import fred, rss
from app.providers.yahoo import Fundamentals, YahooProvider
from app.schemas.market import Instrument, NewsItem
from app.schemas.research import MacroIndicator
from app.services.candles import CandleService
from app.services.instruments import INDUSTRY_UNIVERSE, InstrumentService
from app.services.quotes import QuoteService
from app.tools.headlines import is_relevant, name_terms

log = logging.getLogger(__name__)
T = TypeVar("T")

MAX_PEERS = 12
MAX_HEADLINES = 40
FUNDAMENTALS_TTL = timedelta(hours=24)
MACRO_TTL = timedelta(hours=12)
NEWS_TTL = timedelta(hours=1)
PRICE_SOURCE = "Upstox daily candles"

# NSE industry (NIFTY 500 classification) -> sector index trading symbol.
SECTOR_INDEX = {
    "Financial Services": ("NIFTY Financial Services", "FINNIFTY"),
    "Capital Goods": ("NIFTY India Manufacturing", "NIFTY INDIA MFG"),
    "Healthcare": ("NIFTY Healthcare", "NIFTY HEALTHCARE"),
    "Automobile and Auto Components": ("NIFTY Auto", "NIFTY AUTO"),
    "Fast Moving Consumer Goods": ("NIFTY FMCG", "NIFTY FMCG"),
    "Chemicals": ("NIFTY Chemicals", "NIFTY CHEMICALS"),
    "Information Technology": ("NIFTY IT", "NIFTY IT"),
    "Consumer Services": ("NIFTY Consumption", "NIFTY CONSUMPTION"),
    "Metals & Mining": ("NIFTY Metal", "NIFTY METAL"),
    "Power": ("NIFTY Energy", "NIFTY ENERGY"),
    "Oil Gas & Consumable Fuels": ("NIFTY Oil & Gas", "NIFTY OIL AND GAS"),
    "Consumer Durables": ("NIFTY Consumer Durables", "NIFTY CONSR DURBL"),
    "Services": ("NIFTY Services Sector", "NIFTY SERV SECTOR"),
    "Realty": ("NIFTY Realty", "NIFTY REALTY"),
    "Construction": ("NIFTY Infrastructure", "NIFTY INFRA"),
    "Construction Materials": ("NIFTY Cement", "NIFTY CEMENT"),
    "Media Entertainment & Publication": ("NIFTY Media", "NIFTY MEDIA"),
}
# Yahoo sector -> nearest NSE industry, for companies outside the NIFTY 500.
YAHOO_SECTOR = {
    "Technology": "Information Technology",
    "Financial Services": "Financial Services",
    "Healthcare": "Healthcare",
    "Consumer Defensive": "Fast Moving Consumer Goods",
    "Real Estate": "Realty",
    "Energy": "Oil Gas & Consumable Fuels",
    "Utilities": "Power",
    "Industrials": "Capital Goods",
    "Basic Materials": "Metals & Mining",
    "Consumer Cyclical": "Consumer Services",
    "Communication Services": "Telecommunication",
}

# key, FRED series, label, unit, change unit, change window (days), max age (days), transform
MACRO_SERIES = [
    ("in10y", "INDIRLTLT01STM", "India 10Y bond yield", "%", "pp", 92, 75, "level"),
    ("usdinr", "DEXINUS", "USD/INR", "INR", "%", 91, 10, "level"),
    ("brent", "DCOILBRENTEU", "Brent crude", "USD", "%", 91, 14, "level"),
    ("us10y", "DGS10", "US 10Y Treasury yield", "%", "pp", 91, 10, "level"),
    ("incpi", "INDCPIALLMINMEI", "India CPI inflation (YoY)", "%", "pp", 92, 120, "yoy"),
]


def _value_on_or_before(rows: list[tuple[date, float]], day: date) -> float | None:
    prior = [v for d, v in rows if d <= day]
    return prior[-1] if prior else None


def macro_indicator(spec: tuple, rows: list[tuple[date, float]], today: date) -> MacroIndicator:
    key, series_id, label, unit, change_unit, window, max_age, transform = spec
    source = f"{fred.SOURCE} ({series_id})"
    if transform == "yoy":
        rows = [
            (d, (v / base - 1) * 100)
            for d, v in rows
            if (base := _value_on_or_before(rows, d - timedelta(days=365))) and base > 0
        ]
    base = MacroIndicator(
        key=key,
        label=label,
        value=None,
        unit=unit,
        change=None,
        change_unit=change_unit,
        change_window="3M",
        as_of=None,
        source=source,
        stale=True,
    )
    if not rows:
        base.problem = "no recent observations published"
        return base
    last_day, last = rows[-1]
    then = _value_on_or_before(rows, last_day - timedelta(days=window))
    change = None
    if then is not None:
        change = last - then if change_unit == "pp" else (last / then - 1) * 100 if then else None
    stale = (today - last_day).days > max_age
    return base.model_copy(
        update={
            "value": round(last, 4),
            "change": round(change, 4) if change is not None else None,
            "as_of": datetime(last_day.year, last_day.month, last_day.day, tzinfo=UTC),
            "stale": stale,
            "problem": f"latest observation is from {last_day:%b %Y}" if stale else None,
        }
    )


class ResearchData:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        candles: CandleService,
        quotes: QuoteService,
        yahoo: YahooProvider,
    ):
        self._db = db
        self._instruments = instruments
        self._candles = candles
        self._quotes = quotes
        self._yahoo = yahoo

    # --- individual inputs -------------------------------------------------------

    async def daily(self, instrument: Instrument, label: str | None = None) -> PriceSeries:
        series = await self._candles.series(instrument.instrument_key, "1D")
        if not series.candles:
            raise NotFound(f"No daily candles for {instrument.symbol}.")
        return PriceSeries(
            label=label or instrument.symbol,
            times=[c.time for c in series.candles],
            closes=[c.close for c in series.candles],
            source=PRICE_SOURCE,
            as_of=series.fetched_at,
        )

    async def fundamentals(self, symbol: str) -> Fundamentals:
        key = f"yahoo:summary:{symbol}"
        hit = self._db.cache_get(key)
        if hit is not None:
            return Fundamentals.from_json(hit[0])
        f = await self._yahoo.fundamentals(symbol)
        self._db.cache_put(key, "yahoo", f.to_json(), FUNDAMENTALS_TTL)
        return f

    async def _fred(self, series_id: str) -> list[tuple[date, float]]:
        key = f"fred:{series_id}"
        hit = self._db.cache_get(key)
        if hit is not None:
            return [(date.fromisoformat(d), v) for d, v in hit[0]]
        rows = await fred.fetch_series(series_id, date.today() - timedelta(days=6 * 365))
        self._db.cache_put(key, "fred", [(d.isoformat(), v) for d, v in rows], MACRO_TTL)
        return rows

    async def macro(self) -> list[MacroIndicator]:
        today = datetime.now(UTC).date()

        async def one(spec: tuple) -> MacroIndicator:
            try:
                rows = await self._fred(spec[1])
            except AppError as exc:
                rows = []
                ind = macro_indicator(spec, rows, today)
                ind.problem = exc.message
                return ind
            return macro_indicator(spec, rows, today)

        return list(await asyncio.gather(*(one(s) for s in MACRO_SERIES)))

    async def headlines(self, instrument: Instrument) -> tuple[list[NewsItem], list[str]]:
        terms = name_terms(instrument.name, instrument.symbol)
        key = f"news:search:{instrument.symbol}"
        hit = self._db.cache_get(key)
        if hit is not None:
            return [NewsItem.model_validate(i) for i in hit[0]], terms
        query = max(terms, key=len)
        items = await rss.search_news(f'"{query}"')
        seen: set[str] = set()
        relevant: list[NewsItem] = []
        for item in items:
            marker = item.title.casefold()
            if marker not in seen and is_relevant(item.title, terms):
                seen.add(marker)
                relevant.append(item)
        floor = datetime.min.replace(tzinfo=UTC)
        relevant.sort(key=lambda i: i.published_at or floor, reverse=True)
        relevant = relevant[:MAX_HEADLINES]
        self._db.cache_put(
            key, "google-news", [i.model_dump(mode="json") for i in relevant], NEWS_TTL
        )
        return relevant, terms

    def classify(
        self, instrument: Instrument, f: Fundamentals | None
    ) -> tuple[str | None, str | None]:
        industry = self._instruments.industry_of(instrument.isin)
        if industry:
            return industry, f"NSE industry ({INDUSTRY_UNIVERSE} classification)"
        if f and f.sector in YAHOO_SECTOR:
            return YAHOO_SECTOR[f.sector], f"Yahoo Finance sector '{f.sector}', mapped"
        return None, None

    async def peers(self, instrument: Instrument, industry: str) -> tuple[list[Instrument], str]:
        members = [
            m
            for m in self._instruments.industry_members(industry)
            if m.instrument_key != instrument.instrument_key
        ]
        if len(members) <= MAX_PEERS:
            return members, f"All {len(members)} {INDUSTRY_UNIVERSE} members in {industry}"
        quotes = await self._quotes.get([m.instrument_key for m in members])

        def traded_value(m: Instrument) -> float:
            q = quotes.get(m.instrument_key)
            return (q.volume or 0) * (q.avg_price or q.ltp or 0) if q else 0.0

        ranked = sorted(members, key=traded_value, reverse=True)[:MAX_PEERS]
        return ranked, (
            f"Top {MAX_PEERS} of {len(members)} {INDUSTRY_UNIVERSE} members in {industry} "
            "by traded value in the latest session"
        )

    # --- full context ------------------------------------------------------------

    async def context(self, instrument: Instrument) -> ResearchContext:
        ctx = ResearchContext(instrument=instrument, now=datetime.now(UTC))

        async def attempt(name: str, coro: Awaitable[T]) -> T | None:
            try:
                return await coro
            except AppError as exc:
                ctx.problems.setdefault(name, exc.message)
            except Exception as exc:  # unexpected provider format; keep the run going
                log.warning("research input %s failed for %s: %r", name, instrument.symbol, exc)
                ctx.problems.setdefault(name, "the source returned an unexpected response")
            return None

        bench = self._index("NIFTY")
        vix = self._index("INDIA VIX")
        stock, fundamentals, news, macro, bench_s, vix_s = await asyncio.gather(
            attempt("prices", self.daily(instrument)),
            attempt("fundamentals", self.fundamentals(instrument.symbol)),
            attempt("news", self.headlines(instrument)),
            self.macro(),
            attempt("benchmark", self.daily(bench, "NIFTY 50")) if bench else _none(),
            attempt("vix", self.daily(vix, "India VIX")) if vix else _none(),
        )
        ctx.stock, ctx.fundamentals, ctx.macro = stock, fundamentals, macro
        ctx.benchmark, ctx.vix = bench_s, vix_s
        if news is not None:
            ctx.headlines, ctx.headline_terms = news
        ctx.industry, ctx.industry_source = self.classify(instrument, fundamentals)
        if not ctx.industry:
            return ctx

        sector = SECTOR_INDEX.get(ctx.industry)
        sector_inst = self._index(sector[1]) if sector else None
        if sector and sector_inst:
            ctx.sector_label = sector[0]
            ctx.sector = await attempt("sector", self.daily(sector_inst, sector[0]))
        elif sector:
            ctx.problems["sector"] = f"{sector[1]} is not in the instrument master"

        found = await attempt("peers", self.peers(instrument, ctx.industry))
        if found:
            members, ctx.peer_basis = found

            async def peer(m: Instrument) -> Peer:
                s = await attempt(f"peer:{m.symbol}", self.daily(m))
                f = await attempt(f"peer-fundamentals:{m.symbol}", self.fundamentals(m.symbol))
                return Peer(instrument=m, series=s, fundamentals=f)

            ctx.peers = list(await asyncio.gather(*(peer(m) for m in members)))
        elif "peers" not in ctx.problems:
            ctx.problems["peers"] = f"{instrument.symbol} is outside the {INDUSTRY_UNIVERSE}"
        return ctx

    async def aclose(self) -> None:
        await self._yahoo.aclose()

    def _index(self, symbol: str) -> Instrument | None:
        try:
            return self._instruments.by_symbol(symbol, "NSE_INDEX")
        except NotFound:
            return None


async def _none() -> None:
    return None
