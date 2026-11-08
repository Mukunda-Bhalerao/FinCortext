"""IPO desk: issues open now, announced, closed and awaiting listing, and recent listings, with
real subscription demand from NSE and listing results from exchange prices.

The "odds" attached to an issue are measured, not predicted: how past NSE mainboard issues
with similar demand opened on their listing day. The study is rebuilt in the background from
NSE's past-issue register and Upstox daily candles and stored in ``ipo_history``.
"""

import asyncio
import contextlib
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta

from app.db import Database
from app.errors import AppError, NotFound, ProviderUnavailable
from app.providers import rss
from app.providers.nse_ipo import NseIpoClient
from app.schemas.ipo import (
    IpoDetail,
    IpoIssue,
    IpoOverview,
    Listing,
    ListingOdds,
    MoodStat,
    Subscription,
)
from app.schemas.tracker import Headline
from app.services.candles import CandleService
from app.services.instruments import InstrumentService
from app.services.monitor import SourceMonitor
from app.tools import ipo as I
from app.tools.backtest import session_date
from app.tools.headlines import score_headline
from app.tools.market_hours import to_ist

log = logging.getLogger(__name__)

SOURCE = "nse"
REGISTER_TTL = timedelta(hours=6)
LIVE_TTL = timedelta(minutes=10)  # issues open now: subscription changes through the day
DETAIL_TTL = timedelta(days=1)
NEWS_TTL = timedelta(hours=1)
STUDY_DAYS = 600  # past mainboard issues used for the listing odds
RECENT_DAYS = 90
NEWS_DAYS = 7


def _today() -> date:
    return to_ist(datetime.now(UTC)).date()


def _short(company: str) -> str:
    return re.sub(r"\b(limited|ltd\.?)$", "", company.strip(), flags=re.I).strip(" .,")


def _pct(v: float) -> str:
    return f"{v * 100:+.1f}%"


def _x(v: float | None) -> str:
    return "n/a" if v is None else (f"{v:,.0f}x" if v >= 10 else f"{v:.2f}x")


def _first(row: dict, *keys: str):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "-"):
            return v
    return None


class IpoService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        candles: CandleService,
        monitor: SourceMonitor,
        client: NseIpoClient | None = None,
    ):
        self._db = db
        self._instruments = instruments
        self._candles = candles
        self._monitor = monitor
        self._nse = client or NseIpoClient()
        self._study: asyncio.Task | None = None
        self._study_total = 0

    # --- NSE access with caching and health tracking ------------------------------------

    async def _nse_call(self, key: str, ttl: timedelta, coro_fn):
        hit = self._db.cache_get(key)
        if hit is not None:
            return hit[0]
        try:
            data = await coro_fn()
        except AppError as exc:
            self._monitor.failed(SOURCE, exc.message)
            raise
        self._monitor.ok(SOURCE)
        self._db.cache_put(key, SOURCE, data, ttl)
        return data

    async def _register(self) -> list[dict]:
        """NSE's past-issue register, parsed: one row per issue, newest first."""
        raw = await self._nse_call("ipo:past", REGISTER_TTL, self._nse.past)
        out = []
        for r in raw:
            symbol = str(r.get("symbol") or "").strip()
            if not symbol:
                continue
            kind = str(r.get("securityType") or "").strip().upper()
            if kind not in ("EQUITY", "SME"):
                continue  # debt, InvIT and REIT issues are not equity IPOs
            if symbol.endswith("PP"):
                continue  # partly paid shares of a listed company (rights issues), not an IPO
            low, high = I.parse_band(r.get("priceRange"))
            out.append(
                {
                    "symbol": symbol,
                    "company": str(_first(r, "companyName", "company") or symbol).strip(),
                    "board": "sme" if kind == "SME" else "mainboard",
                    "open": I.parse_date(r.get("ipoStartDate")),
                    "close": I.parse_date(r.get("ipoEndDate")),
                    "listing": I.parse_date(r.get("listingDate")),
                    "issue_price": I.parse_price(r.get("issuePrice")),
                    "low": low,
                    "high": high,
                }
            )
        return out

    async def _detail_raw(self, symbol: str, live: bool) -> dict:
        return await self._nse_call(
            f"ipo:detail:{symbol}",
            LIVE_TTL if live else DETAIL_TTL,
            lambda: self._nse.detail(symbol),
        )

    # --- issue construction --------------------------------------------------------------

    def _issue_from_row(self, r: dict, stage: str) -> IpoIssue:
        return IpoIssue(
            symbol=r["symbol"],
            company=r["company"],
            board=r["board"],
            stage=stage,  # type: ignore[arg-type]
            open_date=r.get("open"),
            close_date=r.get("close"),
            listing_date=r.get("listing"),
            price_low=r.get("low"),
            price_high=r.get("high"),
            issue_price=r.get("issue_price"),
            lot_size=None,
            min_investment=None,
        )

    @staticmethod
    def _live_row(r: dict) -> dict:
        """A row of NSE's current or upcoming issue lists, read defensively."""
        low, high = I.parse_band(_first(r, "issuePrice", "priceBand", "priceRange"))
        series = str(_first(r, "series", "securityType", "issueType") or "").upper()
        return {
            "symbol": str(_first(r, "symbol") or "").strip(),
            "company": str(_first(r, "companyName", "company", "name") or r.get("symbol") or ""),
            "board": "sme" if "SME" in series or series in ("SM", "ST") else "mainboard",
            "open": I.parse_date(_first(r, "issueStartDate", "ipoStartDate", "startDate")),
            "close": I.parse_date(_first(r, "issueEndDate", "ipoEndDate", "endDate")),
            "listing": I.parse_date(_first(r, "listingDate")),
            "issue_price": None,
            "low": low,
            "high": high,
            "times": _first(r, "noOfTime", "noOfTimes"),
        }

    def _enrich(self, issue: IpoIssue, raw: dict, history: list[I.PastIssue], mood30) -> None:
        info = I.parse_issue_info((raw.get("issueInfo") or {}).get("dataList") or [])
        meta = raw.get("metaInfo") or {}
        sub = I.parse_subscription((raw.get("activeCat") or {}).get("dataList") or [])
        if sub and not any(sub.values()):
            sub = {}  # NSE shows zeros where it has no figures for the issue
        if not sub.get("total"):
            with contextlib.suppress(TypeError, ValueError):
                total = float((raw.get("demandGraphALL") or {}).get("noOfTimesIssueSubscribed"))
                if total > 0:
                    sub["total"] = total
        issue.industry = meta.get("industry") or issue.industry
        if issue.price_high is None:
            issue.price_low, issue.price_high = I.parse_band(info.get("Price Range"))
        if issue.open_date is None or issue.close_date is None:
            o, c = I.issue_period(info.get("Issue Period"))
            issue.open_date = issue.open_date or o
            issue.close_date = issue.close_date or c
        issue.lot_size = I.parse_lot(info.get("Bid Lot") or info.get("Minimum Order Quantity"))
        top = issue.issue_price or issue.price_high
        if issue.lot_size and top:
            issue.min_investment = issue.lot_size * top
        if sub:
            issue.subscription = Subscription(**sub)
        others = [h for h in history if h.symbol != issue.symbol]  # never its own result
        issue.odds = self._odds(others, sub.get("qib"), sub.get("total"))
        if issue.stage == "open" and issue.close_date:
            days = (issue.close_date - (issue.open_date or issue.close_date)).days + 1
            day = min(days, max(1, (_today() - (issue.open_date or _today())).days + 1))
            issue.subscription_note = (
                f"Bidding open: day {day} of {days}. Institutions usually bid on the last day, so "
                "demand so far is incomplete."
                if day < days
                else "Last day of bidding: figures update through the day."
            )
        issue.signals = self._signals(issue, mood30)

    @staticmethod
    def _odds(history, qib, total) -> ListingOdds | None:
        o = I.odds_for(history, qib, total)
        if o is None:
            return None
        who = "institutional (QIB) demand" if o.measure == "qib" else "overall demand"
        text = (
            f"Of {o.sample} recent NSE mainboard IPOs with {who} {o.bucket}, "
            f"{o.above_issue * 100:.0f}% opened above the issue price on listing day; "
            f"average {_pct(o.average_gain)}, median {_pct(o.median_gain)}, "
            f"range {_pct(o.worst)} to {_pct(o.best)}."
        )
        return ListingOdds(text=text, **o.__dict__)

    @staticmethod
    def _signals(issue: IpoIssue, mood30) -> list[str]:
        s = issue.subscription
        out: list[str] = []
        if s and s.qib is not None:
            if s.qib >= 10:
                out.append(f"Strong institutional demand: QIB portion {_x(s.qib)} subscribed.")
            elif s.qib < 1 and issue.stage != "open":
                out.append(f"Weak institutional demand: QIB portion only {_x(s.qib)} subscribed.")
            else:
                out.append(f"QIB portion {_x(s.qib)} subscribed.")
        if s and s.retail is not None:
            out.append(f"Retail portion {_x(s.retail)} subscribed.")
            if s.retail >= 10:
                out.append(
                    "Heavy retail oversubscription: allotment is by lottery, so the chance of "
                    "getting a lot is low."
                )
        if issue.board == "sme":
            out.append(
                "SME issue: large minimum lot, thin trading after listing and lighter disclosure "
                "rules. Higher risk than mainboard IPOs."
            )
        if issue.min_investment:
            out.append(f"Minimum investment about Rs {issue.min_investment:,.0f} (one lot).")
        if mood30 and mood30.listed >= 3 and mood30.above_issue_at_open is not None:
            out.append(
                f"IPO market mood: {mood30.above_issue_at_open * 100:.0f}% of the "
                f"{mood30.listed} mainboard IPOs listed in the last 30 days opened above "
                "their issue price."
            )
        return out

    # --- listing results -----------------------------------------------------------------

    async def _listing(self, isin: str | None, issue_price: float | None, listed: date | None):
        if not isin:
            return None
        key = f"NSE_EQ|{isin}"
        if not self._instruments.get_many([key]):
            return Listing(
                instrument_key=None,
                listing_open=None,
                listing_close=None,
                listing_gain=None,
                price=None,
                price_basis=None,
                since_issue=None,
            )
        try:
            series = await self._candles.series(key, "1D")
            self._monitor.ok("upstox")
        except AppError as exc:
            self._monitor.failed("upstox", exc.message)
            return None
        candles = series.candles
        first = candles[0] if candles else None
        first_day = session_date(first.time // 86400) if first else None
        # The first candle is the listing session only when it falls on the listing date.
        on_listing = first is not None and (
            listed is None or (first_day and abs((first_day - listed).days) <= 3)
        )
        last = candles[-1] if candles else None
        price = last.close if last else None
        basis = None
        if last:
            day = session_date(last.time // 86400)
            basis = (
                "today, live"
                if series.includes_current_session and day == _today()
                else f"close on {day:%d %b}"
            )
        lo = first.open if on_listing and first else None
        return Listing(
            instrument_key=key,
            listing_open=lo,
            listing_close=first.close if on_listing and first else None,
            listing_gain=lo / issue_price - 1 if lo and issue_price else None,
            price=price,
            price_basis=basis,
            since_issue=price / issue_price - 1 if price and issue_price else None,
        )

    # --- the listing-odds study ----------------------------------------------------------

    def _history(self) -> list[I.PastIssue]:
        rows = self._db.fetchall(
            "SELECT symbol, listing_date, qib, total, listing_open, issue_price FROM ipo_history "
            "WHERE board = 'mainboard' AND listing_open IS NOT NULL AND issue_price > 0"
        )
        return [
            I.PastIssue(sym, ld, qib, total, lo / ip - 1) for sym, ld, qib, total, lo, ip in rows
        ]

    def _study_targets(self, register: list[dict]) -> list[dict]:
        today = _today()
        done = {r[0] for r in self._db.fetchall("SELECT symbol FROM ipo_history")}
        return [
            r
            for r in register
            if r["board"] == "mainboard"
            and r["listing"]
            and r["issue_price"]
            and 0 <= (today - r["listing"]).days <= STUDY_DAYS
            and r["symbol"] not in done
        ]

    def ensure_study(self, register: list[dict]) -> None:
        if self._study and not self._study.done():
            return
        targets = self._study_targets(register)
        if targets:
            self._study_total = len(targets)
            self._study = asyncio.create_task(self._build_study(targets))

    async def _build_study(self, targets: list[dict]) -> None:
        failures = 0
        for r in targets:
            try:
                raw = await self._detail_raw(r["symbol"], live=False)
            except AppError as exc:
                failures += 1
                log.info("IPO study: %s skipped (%s)", r["symbol"], exc.message)
                if failures >= 5:
                    log.warning("IPO study paused: NSE keeps refusing requests")
                    return
                continue
            sub = I.parse_subscription((raw.get("activeCat") or {}).get("dataList") or [])
            if not any(sub.values()):
                sub = {}
            isin = (raw.get("metaInfo") or {}).get("isin")
            listing = await self._listing(isin, r["issue_price"], r["listing"])
            self._db.execute(
                "INSERT OR REPLACE INTO ipo_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    r["symbol"],
                    r["company"],
                    r["board"],
                    isin,
                    r["issue_price"],
                    r["listing"],
                    sub.get("qib"),
                    sub.get("total"),
                    json.dumps(sub),
                    listing.listing_open if listing else None,
                    listing.listing_close if listing else None,
                    datetime.now(UTC),
                ],
            )
        log.info("IPO study: %d issues processed", len(targets))

    # --- news ----------------------------------------------------------------------------

    async def _news(self, query: str, days: int, must: str | None = None) -> list[Headline]:
        key = f"ipo:news:{query}:{days}"
        hit = self._db.cache_get(key)
        if hit is not None:
            return [Headline.model_validate(h) for h in hit[0]]
        try:
            items = await rss.search_news(query, days)
            self._monitor.ok("news")
        except AppError as exc:
            self._monitor.failed("news", exc.message)
            return []
        seen: set[str] = set()
        out: list[Headline] = []
        for item in sorted(
            items, key=lambda i: i.published_at or datetime.min.replace(tzinfo=UTC), reverse=True
        ):
            title = item.title.strip()
            mark = title.casefold()
            if mark in seen or (must and must.casefold() not in mark):
                continue
            seen.add(mark)
            score = score_headline(title).score
            out.append(
                Headline(
                    title=title,
                    link=item.link,
                    publisher=item.publisher,
                    published_at=item.published_at,
                    tone="positive" if score > 0 else "negative" if score < 0 else "neutral",
                )
            )
        out = out[:20]
        self._db.cache_put(key, "news", [h.model_dump(mode="json") for h in out], NEWS_TTL)
        return out

    # --- public --------------------------------------------------------------------------

    async def overview(self) -> IpoOverview:
        gaps: list[str] = []
        today = _today()
        try:
            register = await self._register()
        except AppError as exc:
            raise ProviderUnavailable(f"NSE IPO data is unavailable: {exc.message}") from exc
        self.ensure_study(register)
        history = self._history()

        # Recent mainboard listings, newest first, with how they listed and trade now.
        recent_rows = [
            r
            for r in register
            if r["board"] == "mainboard"
            and r["listing"]
            and 0 <= (today - r["listing"]).days <= RECENT_DAYS
        ]
        stored = {
            row[0]: row
            for row in self._db.fetchall(
                "SELECT symbol, isin, subscription FROM ipo_history WHERE symbol IN (SELECT "
                "unnest(?))",
                [[r["symbol"] for r in recent_rows] or [""]],
            )
        }

        async def listed(r: dict) -> IpoIssue:
            issue = self._issue_from_row(r, "listed")
            row = stored.get(r["symbol"])
            if row:
                sub = json.loads(row[2]) if row[2] else {}
                if sub:
                    issue.subscription = Subscription(**sub)
                issue.listing = await self._listing(row[1], r["issue_price"], r["listing"])
            return issue

        recent = list(await asyncio.gather(*(listed(r) for r in recent_rows)))
        recent.sort(key=lambda i: i.listing_date or date.min, reverse=True)
        mood_points = [
            (i.listing_date, i.listing.listing_gain, i.listing.since_issue)
            for i in recent
            if i.listing and i.listing.listing_gain is not None and i.listing_date
        ]
        moods = [I.mood(mood_points, today, d) for d in (30, 90)]
        mood30 = moods[0]

        # Open now and announced, from NSE's live lists.
        live_open: list[dict] = []
        live_upcoming: list[dict] = []
        try:
            live_open = [
                self._live_row(r)
                for r in await self._nse_call("ipo:current", LIVE_TTL, self._nse.current)
            ]
            live_upcoming = [
                self._live_row(r)
                for r in await self._nse_call("ipo:upcoming", LIVE_TTL, self._nse.upcoming)
            ]
        except AppError as exc:
            gaps.append(f"NSE current and upcoming issue lists unavailable: {exc.message}")
        known = {r["symbol"] for r in live_open + live_upcoming}
        # The register also carries issues that have closed but not listed yet, and issues
        # whose bidding window covers today.
        for r in register:
            if r["symbol"] in known or (r["listing"] and r["listing"] <= today):
                continue
            if r["open"] and r["close"] and r["open"] <= today <= r["close"]:
                live_open.append(r)
                known.add(r["symbol"])
        awaiting_rows = [
            r
            for r in register
            if r["symbol"] not in known
            and r["close"]
            and r["close"] < today
            and (r["listing"] is None or r["listing"] > today)
            and (today - r["close"]).days <= 14
        ]

        async def enriched(r: dict, stage: str) -> IpoIssue:
            issue = self._issue_from_row(r, stage)
            if stage == "upcoming":
                issue.signals = self._signals(issue, mood30)
                return issue
            try:
                raw = await self._detail_raw(r["symbol"], live=stage == "open")
                self._enrich(issue, raw, history, mood30)
            except AppError as exc:
                gaps.append(f"{r['symbol']}: issue details unavailable ({exc.message}).")
                issue.signals = self._signals(issue, mood30)
            return issue

        open_now = [await enriched(r, "open") for r in live_open if r["symbol"]]
        awaiting = [await enriched(r, "closed") for r in awaiting_rows]
        upcoming = [await enriched(r, "upcoming") for r in live_upcoming if r["symbol"]]
        upcoming.sort(key=lambda i: i.open_date or date.max)

        ranked = sorted(
            (i for i in open_now + awaiting if i.odds is not None),
            key=lambda i: (
                -(i.odds.above_issue if i.odds else 0),
                -(i.odds.average_gain if i.odds else 0),
                -((i.subscription.qib or 0) if i.subscription else 0),
            ),
        )
        odds_table = [ListingOdds(text="", **o.__dict__) for o in I.bucket_table(history, "qib")]
        if not history:
            gaps.append(
                "Listing odds are still being measured from past NSE issues; they appear here "
                "once enough issues are processed."
            )
        building = self._study is not None and not self._study.done()
        news = await self._news("IPO India NSE BSE", NEWS_DAYS, must="IPO")
        return IpoOverview(
            open=open_now,
            upcoming=upcoming,
            awaiting_listing=awaiting,
            recent_listings=recent,
            strongest=[i.symbol for i in ranked[:5]],
            mood=[MoodStat(**m.__dict__) for m in moods],
            odds_table=odds_table,
            history_size=len(history),
            history_complete=not building,
            news=news,
            as_of=datetime.now(UTC),
            gaps=gaps,
        )

    async def issue(self, symbol: str) -> IpoDetail:
        symbol = symbol.strip().upper()
        gaps: list[str] = []
        today = _today()
        register = await self._register()
        row = next((r for r in register if r["symbol"].upper() == symbol), None)
        live_rows: list[dict] = []
        for key, fn in (("ipo:current", self._nse.current), ("ipo:upcoming", self._nse.upcoming)):
            with contextlib.suppress(AppError):
                live_rows += [self._live_row(r) for r in await self._nse_call(key, LIVE_TTL, fn)]
        live = next((r for r in live_rows if r["symbol"].upper() == symbol), None)
        base = live or row
        if base is None:
            raise NotFound(f"No NSE IPO found for {symbol}.")
        if base["listing"] and base["listing"] <= today:
            stage = "listed"
        elif base["open"] and base["open"] > today:
            stage = "upcoming"
        elif base["close"] and base["close"] < today:
            stage = "closed"
        else:
            stage = "open"
        issue = self._issue_from_row(base, stage)
        history = self._history()
        facts: dict[str, str] = {}
        raw: dict = {}
        if stage != "upcoming":
            try:
                raw = await self._detail_raw(base["symbol"], live=stage == "open")
            except AppError as exc:
                gaps.append(f"Issue details unavailable: {exc.message}")
        if raw:
            facts = I.parse_issue_info((raw.get("issueInfo") or {}).get("dataList") or [])
            self._enrich(issue, raw, history, None)
        series: list[dict] = []
        if stage == "listed":
            isin = (raw.get("metaInfo") or {}).get("isin")
            issue.listing = await self._listing(isin, issue.issue_price, issue.listing_date)
            if issue.listing and issue.listing.instrument_key:
                with contextlib.suppress(AppError):
                    s = await self._candles.series(issue.listing.instrument_key, "1D")
                    series = [
                        {
                            "time": (session_date(c.time // 86400) - date(1970, 1, 1)).days * 86400,
                            "value": c.close,
                        }
                        for c in s.candles
                    ]
        managers = [
            m.strip(" ,")
            for m in re.split(r"\n|,(?![^()]*\))", facts.get("Book Running Lead Managers", ""))
            if m.strip(" ,")
        ]
        documents = {
            t: v
            for t, v in facts.items()
            if v.startswith("https://nsearchives")
            and t
            in (
                "Red Herring Prospectus",
                "Ratios / Basis of Issue Price",
                "Anchor Allocation Report",
            )
        }
        keep = (
            "Issue Size",
            "Issue Type",
            "Price Range",
            "Face Value",
            "Bid Lot",
            "Discount",
            "Name of the Registrar",
            "Issue Period",
        )
        shown = {k: facts[k] for k in keep if facts.get(k)}
        news = await self._news(f'"{_short(issue.company)}" IPO', 30)
        return IpoDetail(
            issue=issue,
            facts=shown,
            lead_managers=managers[:20],
            documents=documents,
            price_series=series,
            news=news,
            as_of=datetime.now(UTC),
            gaps=gaps,
        )

    async def aclose(self) -> None:
        if self._study:
            self._study.cancel()
        await self._nse.aclose()
