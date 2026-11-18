"""The app-wide assistant: a question goes to a tool, the tool computes the answer.

    question -> router (rules; the model only when rules find nothing)
             -> one tool (deterministic: prices, attribution, charges, accounts, IPOs, tests)
             -> answer + cards + the facts it rests on + next questions
             -> optional rephrasing by the language model, kept only if every number in it
                appears in the facts

The assistant therefore works with the language model off, and cannot state a figure the
engine did not compute. It explains and measures; it never tells the user to buy or sell.
"""

import asyncio
import logging
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.db import Database
from app.errors import AppError, NotFound, RateLimited
from app.schemas.chat import (
    Bar,
    ChatAction,
    ChatAnswer,
    ChatCard,
    ChatContext,
    ChatRequest,
    Row,
    Stat,
)
from app.schemas.insights import AskRequest
from app.schemas.market import Instrument, Quote
from app.schemas.strategy import BacktestIn
from app.services.assistant import Assistant
from app.services.candles import CandleService
from app.services.insights import FactBook, pct
from app.services.instruments import INDUSTRY_UNIVERSE, InstrumentService
from app.services.ipo import IpoService
from app.services.market import MarketService
from app.services.paper import PaperService
from app.services.research import ResearchService
from app.services.research_data import ResearchData
from app.services.session import SessionClock
from app.services.strategy import StrategyService
from app.services.today import TodayService
from app.services.tracker import TrackerService
from app.tools import intent as I
from app.tools.charges import PLANS, break_even, order_charges
from app.tools.glossary import GLOSSARY
from app.tools.market_hours import to_ist
from app.tools.rules import PRESETS
from app.tools.technicals import period_return, rsi, sma

log = logging.getLogger(__name__)

PER_MINUTE = 30
MARKET = "Upstox market data"
ENGINE = "FinCortext calculation"
RESEARCH = "FinCortext research agents"
NEWS = "Google News search"
NSE = "NSE IPO data"
PHRASED = {"stock", "why", "account", "market", "ipo", "backtest"}

PERIOD_DAYS = {"1w": 7, "1m": 30, "3m": 91, "6m": 182, "1y": 365}
PERIOD_LABEL = {
    "today": "today",
    "1w": "over the past week",
    "1m": "over the past month",
    "3m": "over the past three months",
    "6m": "over the past six months",
    "1y": "over the past year",
}
TOOL_HELP = {
    "stock": "a snapshot of one stock: price, trend, research view, news",
    "why": "why a stock moved over a period (market, sector, company)",
    "charges": "what an order costs and its break-even price",
    "account": "the user's paper trading account: value, holdings, orders, lessons",
    "ipo": "IPOs open now, recent listings and their track record",
    "backtest": "test a classic trading rule on a stock's past prices",
    "market": "how the market, indices and sectors are doing",
    "today": "what deserves the user's attention right now",
    "glossary": "what a market term means",
    "howto": "how to do something in the app",
    "planner": "portfolio plan what-ifs, objective comparisons and long-term goals",
}
HOWTO: dict[str, tuple[str, list[str], str, str]] = {
    "place_order": (
        "Placing a practice order",
        [
            "Open Portfolios and choose your paper account (create one if you have none).",
            "Press New order, search the stock and choose Buy or Sell.",
            "Enter an amount in rupees or a number of shares; pick Market, Limit or Stop-loss.",
            "Write why you are buying and, for a buy, an optional target and stop-loss.",
            "Check the charges and break-even shown, then place the order.",
        ],
        "Open Portfolios",
        "/portfolios",
    ),
    "stop_loss": (
        "Setting a stop-loss or target",
        [
            "When buying: fill Stop-loss (sell below) and Target (sell above) on the ticket.",
            "Once the buy fills they become linked sell orders; if one fills, the other is "
            "cancelled.",
            "For a stock you already hold: press Sell, choose Stop-loss, and enter the trigger "
            "price.",
            "Choose Until cancelled so the order stays beyond today.",
        ],
        "Open Portfolios",
        "/portfolios",
    ),
    "sell": (
        "Selling a holding",
        [
            "Open your paper account and find the stock under Holdings.",
            "Press Sell on its row; the ticket opens with the shares you hold.",
            "Write why you are selling, check what you receive after charges, and place it.",
            "The closed trade then appears in your journal and scorecard.",
        ],
        "Open Portfolios",
        "/portfolios",
    ),
    "cancel_order": (
        "Cancelling an order",
        [
            "Open your paper account and switch to the Orders tab.",
            "Open orders are listed first; press Cancel on the one you want to stop.",
            "Cash that a buy order was holding is freed immediately.",
        ],
        "Open Portfolios",
        "/portfolios",
    ),
    "open_account": (
        "Opening a paper account",
        [
            "Open Portfolios and press New portfolio.",
            "Choose Paper trading account, name it, and set the starting cash.",
            "Pick a brokerage plan: zero on delivery, or Rs 20 / 0.1% per order.",
            "Create it. You can now trade at live prices with virtual money.",
        ],
        "Open Portfolios",
        "/portfolios",
    ),
    "backtest": (
        "Testing a trading idea",
        [
            "Open Strategy Lab and start from one of the classic ideas, or build your own rules.",
            "Choose up to ten stocks and how many years of history to test.",
            "Run the backtest and compare the rules with buy-and-hold and the NIFTY 50.",
            "Check the earlier 70% against the later 30%: do the rules hold up on later years?",
            "Save the strategy to run it forward in a paper account.",
        ],
        "Open Strategy Lab",
        "/lab",
    ),
    "watchlist": (
        "Following a stock",
        [
            "Search the stock with the search bar (Ctrl+K) and open its page.",
            "Press the star next to its name to add it to your watchlist.",
            "Starred stocks get live prices, research reports and alerts.",
        ],
        "Open Watchlist",
        "/watchlist",
    ),
    "ipo": (
        "Reading an IPO",
        [
            "Open IPOs to see issues open for bidding, upcoming and recently listed.",
            "Open an issue to see who is bidding: institutions (QIB), HNIs and retail.",
            "Compare its demand with the track record of similar past issues.",
            "FinCortext does not apply for IPOs; applications go through your broker or bank.",
        ],
        "Open IPOs",
        "/ipos",
    ),
    "journal": (
        "Using the journal and scorecard",
        [
            "Write a reason and pick a tag each time you buy.",
            "The Journal tab shows each decision next to its result and the NIFTY 50's.",
            "After you close trades, the Scorecard tab shows win rate, charges, tax and the "
            "habits your record reveals.",
        ],
        "Open Portfolios",
        "/portfolios",
    ),
    "general": (
        "Getting started",
        [
            "Star a few companies you know to follow them.",
            "Open a paper account and place a practice trade with a written reason.",
            "Come back later: the account explains what moved your stocks and why.",
            "Test an idea in the Strategy Lab before trusting it.",
        ],
        "Open Learn",
        "/learn",
    ),
}


def inr(v: float, digits: int = 2) -> str:
    """Rupees with Indian digit grouping: 1,23,456.78"""
    whole, _, frac = f"{abs(v):.{digits}f}".partition(".")
    if len(whole) > 3:
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", whole[:-3])
        whole = f"{head},{whole[-3:]}"
    return ("-" if v < 0 else "") + "₹" + whole + (f".{frac}" if frac else "")


def _tone(v: float | None) -> str | None:
    if v is None or v == 0:
        return None
    return "up" if v > 0 else "down"


def _day(q: Quote | None) -> float | None:
    if q is None or q.change is None or not q.prev_close:
        return None
    return q.change / q.prev_close


@dataclass
class Draft:
    answer: str
    cards: list[ChatCard] = field(default_factory=list)
    book: FactBook = field(default_factory=FactBook)
    follow_ups: list[str] = field(default_factory=list)
    actions: list[ChatAction] = field(default_factory=list)
    symbol: str | None = None
    notice: str | None = None


class ChatService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        market: MarketService,
        candles: CandleService,
        data: ResearchData,
        research: ResearchService,
        tracker: TrackerService,
        paper: PaperService,
        ipo: IpoService,
        strategies: StrategyService,
        today: TodayService,
        assistant: Assistant,
        clock: SessionClock,
    ):
        self._db = db
        self._instruments = instruments
        self._market = market
        self._candles = candles
        self._data = data
        self._research = research
        self._tracker = tracker
        self._paper = paper
        self._ipo = ipo
        self._strategies = strategies
        self._today = today
        self._assistant = assistant
        self._clock = clock
        self._calls: deque[float] = deque()
        self._universe: tuple[str | None, set[str], dict[str, str]] | None = None

    # --- vocabulary ------------------------------------------------------------------------

    def _vocabulary(self) -> tuple[set[str], dict[str, str]]:
        """Every NSE equity symbol, and the lower-case names people use for the larger ones.
        Rebuilt when the instrument list is reloaded."""
        stamp = self._instruments.loaded_on()
        if self._universe is None or self._universe[0] != stamp:
            rows = self._db.fetchall(
                "SELECT trading_symbol FROM instruments WHERE segment = 'NSE_EQ'"
            )
            known = {r[0].upper() for r in rows}
            members = self._instruments.constituents(INDUSTRY_UNIVERSE)
            aliases = I.build_aliases([(m.symbol, m.name) for m in members])
            self._universe = (stamp, known, aliases)
        return self._universe[1], self._universe[2]

    def _familiar(self) -> set[str]:
        keys = set(self._market.watchlist_keys()) | set(self._tracker.keys())
        return {i.symbol.upper() for i in self._instruments.get_many(sorted(keys)).values()}

    def _inst(self, symbol: str) -> Instrument:
        return self._instruments.by_symbol(symbol.upper())

    def _limit(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 60:
            self._calls.popleft()
        if len(self._calls) >= PER_MINUTE:
            raise RateLimited("Too many questions in a minute; try again shortly.")
        self._calls.append(now)

    # --- entry point -----------------------------------------------------------------------

    async def ask(self, req: ChatRequest) -> ChatAnswer:
        self._limit()
        question = req.question.strip()
        ctx = req.context
        known, aliases = self._vocabulary()
        intent = I.route(question, known, aliases, self._familiar(), ctx.symbol)
        if intent.tool == "unknown":
            picked = await self._assistant.pick_tool(question, TOOL_HELP)
            tool = str((picked or {}).get("tool") or "")
            if tool in TOOL_HELP:
                sym = str(picked.get("symbol") or "").upper()
                intent.tool, intent.rule = tool, "chosen by the language model"
                if sym in known:
                    intent.symbols = [sym]
                if tool == "glossary":
                    intent.term = I.find_term(str(picked.get("term") or ""))
                    if intent.term is None:
                        intent.tool = "unknown"
        if not intent.symbols and ctx.symbol and intent.tool in ("why", "backtest", "charges"):
            intent.symbols = [ctx.symbol.upper()]
        try:
            draft = await self._run(intent, req)
        except NotFound as exc:
            draft = Draft(
                f"{exc.message} Check the symbol, or search the stock with Ctrl+K.",
                follow_ups=["How is the market doing?", "What can you do?"],
            )
        except RateLimited:
            raise
        except AppError as exc:
            draft = Draft(
                f"I could not work that out just now: {exc.message}",
                follow_ups=["How is the market doing?", "What can you do?"],
            )
        answer, by = draft.answer, "engine"
        if intent.tool in PHRASED and draft.book.facts:
            history = [{"role": t.role, "content": t.content} for t in req.history]
            phrased = await self._assistant.phrase(
                question, draft.answer, draft.book.facts, history
            )
            if phrased:
                answer, by = phrased[0], "model"
        return ChatAnswer(
            answer=answer,
            tool=intent.tool,
            rule=intent.rule,
            cards=draft.cards,
            facts=draft.book.facts,
            follow_ups=draft.follow_ups[:4],
            actions=draft.actions[:3],
            answered_by=by,  # type: ignore[arg-type]
            model=self._assistant.model_name if by == "model" else None,
            notice=draft.notice,
            symbol=draft.symbol or (intent.symbols[0] if intent.symbols else None),
            generated_at=datetime.now(UTC),
        )

    async def _run(self, intent: I.Intent, req: ChatRequest) -> Draft:
        sym = intent.symbols[0] if intent.symbols else None
        match intent.tool:
            case "help":
                return self._help(req.context, thanks=intent.rule == "thanks")
            case "glossary":
                return self._glossary(intent.term or "")
            case "howto":
                return self._howto(intent.topic or "general")
            case "charges":
                return await self._charges(sym, intent, req.context)
            case "why":
                if sym is None:
                    return self._need_stock("Which stock? For example: Why did INFY fall?")
                return await self._why(sym, intent.period or "1m")
            case "stock":
                return await self._stock(sym or "")
            case "account":
                return await self._account(intent, req.context)
            case "ipo":
                return await self._ipos()
            case "backtest":
                if sym is None:
                    return self._need_stock(
                        "Which stock should I test it on? For example: Test golden cross on INFY."
                    )
                return await self._backtest(sym, intent.preset or "dip", intent.years or 5)
            case "market":
                return await self._market_now()
            case "today":
                return await self._attention()
            case "planner":
                return await self._planner(req)
        return await self._unknown(req.question, req.context)

    # --- tools: no data needed -------------------------------------------------------------

    def starters(self, ctx: ChatContext) -> list[str]:
        """Questions worth asking from the page the user is on."""
        return self._suggestions(ctx)

    def _suggestions(self, ctx: ChatContext) -> list[str]:
        path = ctx.path or "/"
        if ctx.symbol and path.startswith("/stock"):
            s = ctx.symbol.upper()
            return [
                f"Tell me about {s}",
                f"Why did {s} move this month?",
                f"What would it cost to buy 10 {s}?",
                f"Test buying the dips on {s}",
            ]
        if path.startswith("/portfolios"):
            return [
                "How am I doing in my account?",
                "Why did my portfolio move this week?",
                "How do I set a stop-loss?",
                "What is break-even?",
            ]
        if path.startswith("/ipos"):
            return [
                "Which IPOs are open?",
                "How have recent IPOs listed?",
                "What is QIB?",
                "What does times subscribed mean?",
            ]
        if path.startswith("/lab"):
            return [
                "Test golden cross on RELIANCE",
                "What is a backtest?",
                "What is out-of-sample?",
                "How do I test a strategy?",
            ]
        return [
            "What should I look at today?",
            "How is the market doing?",
            "Tell me about RELIANCE",
            "How do I place an order?",
        ]

    def _help(self, ctx: ChatContext, thanks: bool = False) -> Draft:
        if thanks:
            return Draft("Any time. Ask when something moves and you want to know why.",
                         follow_ups=self._suggestions(ctx)[:3])  # fmt: skip
        return Draft(
            "I answer from this app's own data, and I show what each answer rests on. "
            "Ask me about a stock, why something moved, what an order costs, how your "
            "paper account is doing, open IPOs, or what a term means. I can also test a "
            "classic trading rule on any stock's past prices. I don't predict prices or "
            "tell you what to buy.",
            cards=[
                ChatCard(
                    kind="steps",
                    title="Things you can ask",
                    steps=[
                        "Tell me about INFY",
                        "Why did RELIANCE move this month?",
                        "What would it cost to buy 10 TCS?",
                        "How am I doing in my account?",
                        "Test golden cross on HDFCBANK for 5 years",
                        "What is STT?",
                    ],
                )
            ],
            follow_ups=self._suggestions(ctx),
        )

    def _need_stock(self, text: str) -> Draft:
        names = sorted(self._familiar())[:3]
        return Draft(text, follow_ups=[f"Tell me about {n}" for n in names])

    def _glossary(self, key: str) -> Draft:
        term, group, text = GLOSSARY[key]
        related = [k for k, (_, g, _) in GLOSSARY.items() if g == group and k != key][:3]
        d = Draft(
            f"{term}: {text}",
            cards=[ChatCard(kind="definition", title=term, note=group, text=text)],
            follow_ups=[f"What is {k}?" for k in related],
            actions=[ChatAction(label="Open the glossary", to="/learn")],
        )
        d.book.add(f"{term}: {text}", "FinCortext glossary", "observed")
        return d

    def _howto(self, topic: str) -> Draft:
        title, steps, label, to = HOWTO.get(topic, HOWTO["general"])
        related = {
            "place_order": ["How do I set a stop-loss?", "What is a limit order?"],
            "stop_loss": ["What is a stop-loss?", "How do I cancel an order?"],
            "backtest": ["What is out-of-sample?", "Test golden cross on RELIANCE"],
            "open_account": ["How do I place an order?", "What is break-even?"],
        }.get(topic, ["How do I place an order?", "What can you do?"])
        return Draft(
            f"{title}, step by step:",
            cards=[ChatCard(kind="steps", title=title, steps=steps)],
            follow_ups=related,
            actions=[ChatAction(label=label, to=to)],
        )

    async def _unknown(self, question: str, ctx: ChatContext) -> Draft:
        concept = await self._assistant.concept(question)
        if concept:
            return Draft(
                concept,
                follow_ups=self._suggestions(ctx),
                notice="A general explanation from the language model, with no figures. "
                "Ask about a specific stock or account for calculated answers.",
            )
        return Draft(
            "I couldn't match that to something I can calculate from this app's data. I can "
            "explain a stock, why it moved, what an order costs, your paper account, IPOs, "
            "market terms, or test a classic rule on past prices.",
            follow_ups=self._suggestions(ctx),
        )

    # --- tools: market data ----------------------------------------------------------------

    async def _closes(self, inst: Instrument) -> list[float]:
        series = await self._candles.series(inst.instrument_key, "1D")
        return [c.close for c in series.candles]

    async def _nifty(self) -> list[float]:
        try:
            return await self._closes(self._instruments.by_symbol("NIFTY", "NSE_INDEX"))
        except AppError:
            return []

    async def _stock(self, symbol: str) -> Draft:
        inst = self._inst(symbol)
        sym = inst.symbol
        summary = await self._market.summary(inst)
        closes: list[float] = []
        try:
            closes = await self._closes(inst)
        except AppError as exc:
            log.info("chat: no candles for %s (%s)", sym, exc.message)
        q = summary.quote
        price = q.ltp if q and q.ltp else (closes[-1] if closes else None)
        d = Draft("", symbol=sym)
        if price is None:
            d.answer = f"No price is available for {sym} right now. " + " ".join(summary.problems)
            return d
        day = _day(q)
        live = q is not None and q.freshness in ("live", "delayed")
        nifty = await self._nifty()
        r1m, r1y = period_return(closes, 21), period_return(closes, 252)
        n1m, n1y = period_return(nifty, 21), period_return(nifty, 252)
        s200 = sma(closes, 200)
        strength = rsi(closes) if len(closes) > 20 else None
        hi = max(summary.week52_high, price) if summary.week52_high else None
        from_high = price / hi - 1 if hi else None
        name = inst.name or sym

        parts = [
            f"{name} ({sym}) {'is trading at' if live else 'last closed at'} {inr(price)}"
            + (f", {pct(day, True, 2)} {'today' if live else 'in that session'}" if day else "")
            + "."
        ]
        d.book.add(parts[0], MARKET, "observed", q.fetched_at if q else None)
        if r1m is not None:
            text = f"Over the past month it is {pct(r1m, True)}"
            if n1m is not None:
                text += f" against {pct(n1m, True)} for the NIFTY 50"
            if r1y is not None:
                text += f"; over a year, {pct(r1y, True)}"
                if n1y is not None:
                    text += f" against {pct(n1y, True)}"
            parts.append(text + ".")
            d.book.add(parts[-1], MARKET, "measured")
        if from_high is not None and hi:
            where = (
                "at its 52-week high"
                if from_high > -0.005
                else f"{pct(-from_high)} below its 52-week high of {inr(hi)}"
            )
            text = f"It is {where}"
            if s200:
                above = price > s200
                text += (
                    f" and {'above' if above else 'below'} its 200-day average of {inr(s200)}, "
                    f"which many read as a long {'up' if above else 'down'}trend"
                )
            parts.append(text + ".")
            d.book.add(parts[-1], MARKET, "measured")
        if strength is not None:
            mood = (
                "heavily sold recently"
                if strength <= 30
                else "stretched after a run"
                if strength >= 70
                else "neither stretched nor washed out"
            )
            parts.append(f"RSI(14) is {strength:.0f}: {mood}.")
            d.book.add(parts[-1], MARKET, "measured")
        report = self._research.latest(inst.instrument_key)
        if report and report.composite.score is not None:
            parts.append(
                f"FinCortext's research view is {report.composite.signal} "
                f"({report.composite.score:+.2f}). Replay tests have not shown these scores "
                "to predict returns, so read it as context."
            )
            d.book.add(parts[-1], RESEARCH, "observed", report.computed_at)
        d.answer = " ".join(parts)

        stats = [Stat(label="Price", value=inr(price), hint="live" if live else "last close")]
        if day is not None:
            stats.append(Stat(label="Day", value=pct(day, True, 2), tone=_tone(day)))
        if r1m is not None:
            stats.append(Stat(label="1 month", value=pct(r1m, True), tone=_tone(r1m)))
        if r1y is not None:
            stats.append(Stat(label="1 year", value=pct(r1y, True), tone=_tone(r1y)))
        if from_high is not None:
            stats.append(Stat(label="From 52w high", value=pct(from_high, True)))
        if strength is not None:
            stats.append(Stat(label="RSI(14)", value=f"{strength:.0f}"))
        d.cards.append(ChatCard(kind="stats", title=f"{sym} at a glance", stats=stats))
        if len(closes) >= 20:
            d.cards.append(ChatCard(kind="spark", title="Last 90 sessions", points=closes[-90:]))
        try:
            items, _ = await asyncio.wait_for(self._data.headlines(inst), 6)
        except (TimeoutError, AppError):
            items = []
        if items:
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Recent headlines",
                    note="Context, not proof of what moved the price",
                    rows=[Row(label=n.title, sub=n.publisher, href=n.link) for n in items[:3]],
                )
            )
            for n in items[:2]:
                d.book.add(f"{sym} headline ({n.publisher}): {n.title}", NEWS, "observed")
        d.follow_ups = [
            f"Why did {sym} move this month?",
            f"What would it cost to buy 10 {sym}?",
            f"Test buying the dips on {sym}",
        ]
        d.actions = [ChatAction(label=f"Open {sym}", to=f"/stock/{sym}")]
        return d

    async def _why(self, symbol: str, period: str) -> Draft:
        inst = self._inst(symbol)
        sym = inst.symbol
        now = datetime.now(UTC)
        if period == "today":
            since = to_ist(now).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            since = now - timedelta(days=PERIOD_DAYS.get(period, 30))
        r = await self._tracker.explain_stock(inst, since)
        d = Draft("", symbol=sym)
        label = PERIOD_LABEL.get(period, "over the past month")
        if r is None:
            d.answer = f"There is not enough price history to explain {sym} {label}."
            return d
        lead = (
            f"{sym} is {pct(r.return_pct, True)} {label}: {inr(r.start_price)} "
            f"({r.start_basis}) to {inr(r.end_price)}."
        )
        rest = r.explanation.split(". ", 1)[1] if ". " in r.explanation else ""
        rest = re.sub(r"Rs (?=\d)", "₹", rest)
        d.answer = f"{lead} {rest}".strip()
        d.book.add(lead, MARKET, "measured")
        if rest:
            d.book.add(rest, ENGINE, "measured")
        near = [h for h in r.headlines if h.near_move]
        if near:
            d.answer += " Headlines show what was reported around the move; they don't prove cause."
        bars = []
        if r.market_return is not None:
            bars.append(Bar(label="NIFTY 50 (the market)", value=r.market_return))
            if r.sector_return is not None:
                bars.append(
                    Bar(
                        label=f"{r.sector_label} beyond the market",
                        value=r.sector_return - r.market_return,
                    )
                )
            if r.stock_specific is not None:
                bars.append(
                    Bar(
                        label=f"{sym} beyond its "
                        f"{'sector' if r.sector_return is not None else 'market'}",
                        value=r.stock_specific,
                    )
                )
        if bars:
            d.cards.append(
                ChatCard(
                    kind="bars",
                    title=f"What made up {sym}'s {pct(r.return_pct, True)}",
                    note="The three parts add up to the stock's move",
                    bars=bars,
                )
            )
        if r.moves:
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Unusually big days",
                    rows=[
                        Row(
                            label="Today so far" if m.live else f"{m.date:%d %b %Y}",
                            change=m.change_pct,
                        )
                        for m in r.moves
                    ],
                )
            )
        if r.headlines:
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Reported in this period",
                    rows=[
                        Row(
                            label=h.title,
                            sub=h.publisher
                            + (f" · around the {h.near_move:%d %b} move" if h.near_move else ""),
                            href=h.link,
                        )
                        for h in r.headlines[:3]
                    ],
                )
            )
            for h in r.headlines[:2]:
                d.book.add(f"{sym} headline ({h.publisher}): {h.title}", NEWS, "observed")
        other = "this year" if period != "1y" else "this week"
        d.follow_ups = [
            f"Why did {sym} move {other}?",
            f"Tell me about {sym}",
            "How is the market doing?",
        ]
        d.actions = [ChatAction(label=f"Open {sym}", to=f"/stock/{sym}")]
        return d

    async def _market_now(self) -> Draft:
        d = Draft("")
        is_open = self._clock.state()[0] == "open"
        indices = [i for i in await self._market.indices() if i.quote and i.quote.ltp]
        parts: list[str] = []
        if indices:
            head = indices[0]
            day = _day(head.quote)
            text = (
                f"The {head.label} {'is at' if is_open else 'last closed at'} "
                f"{head.quote.ltp:,.2f}" + (f" ({pct(day, True, 2)})" if day is not None else "")
            )
            others = [
                f"{i.label} {pct(_day(i.quote), True, 2)}"
                for i in indices[1:4]
                if _day(i.quote) is not None
            ]
            if others:
                text += "; " + ", ".join(others)
            parts.append(text + ".")
            d.book.add(parts[-1], MARKET, "observed", head.quote.fetched_at)
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Indices",
                    rows=[
                        Row(
                            label=i.label,
                            value=f"{i.quote.ltp:,.2f}",
                            change=_day(i.quote),
                            to=f"/?chart={i.instrument.instrument_key}",
                        )
                        for i in indices[:5]
                    ],
                )
            )
        try:
            sectors = [i for i in await self._market.sectors() if _day(i.quote) is not None]
        except AppError:
            sectors = []
        if sectors:
            ranked = sorted(sectors, key=lambda i: _day(i.quote) or 0, reverse=True)
            up = sum(1 for i in sectors if (_day(i.quote) or 0) > 0)
            best, worst = ranked[0], ranked[-1]
            parts.append(
                f"{up} of {len(sectors)} sectors {'are up' if is_open else 'rose'}, led by "
                f"{best.label} ({pct(_day(best.quote), True, 2)}); the weakest is "
                f"{worst.label} ({pct(_day(worst.quote), True, 2)})."
            )
            d.book.add(parts[-1], MARKET, "observed")
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Strongest and weakest sectors",
                    rows=[Row(label=i.label, change=_day(i.quote)) for i in ranked[:3]]
                    + [Row(label=i.label, change=_day(i.quote)) for i in ranked[-3:]],
                )
            )
        try:
            movers = await self._market.movers()
        except AppError:
            movers = None
        if movers and movers.gainers and movers.losers:
            g, lo = movers.gainers[0], movers.losers[0]
            parts.append(
                f"In the {movers.universe}, {movers.advances} stocks advanced and "
                f"{movers.declines} declined; {g.label} gained most "
                f"({pct(_day(g.quote), True, 2)}) and {lo.label} lost most "
                f"({pct(_day(lo.quote), True, 2)})."
            )
            d.book.add(parts[-1], MARKET, "observed")
        d.answer = " ".join(parts) or "Market data is not available right now."
        d.follow_ups = ["What should I look at today?", "Which IPOs are open?"]
        if movers and movers.gainers:
            d.follow_ups.insert(0, f"Why did {movers.gainers[0].label} move today?")
        d.actions = [ChatAction(label="Open Markets", to="/markets")]
        return d

    # --- tools: orders and accounts --------------------------------------------------------

    async def _charges(self, symbol: str | None, intent: I.Intent, ctx: ChatContext) -> Draft:
        plan = "zero"
        pid = self._pick_account(ctx)
        if pid:
            plan = self._tracker.account(pid)[3]
        d = Draft("")
        if symbol is None:
            value = intent.amount or 10_000.0
            buy, sell = order_charges("BUY", value, plan), order_charges("SELL", value, plan)
            d.answer = (
                f"On a delivery order worth {inr(value, 0)}, buying costs {inr(buy.total)} in "
                f"charges and selling costs {inr(sell.total)}. STT (0.1%) is the largest part "
                "on both sides; stamp duty applies when buying, and a fixed depository (DP) "
                f"charge of {inr(sell.dp)} applies when selling. Name a stock and a quantity "
                "for an exact figure with its break-even price."
            )
            d.book.add(d.answer, ENGINE, "measured")
            d.cards.append(self._charges_card("BUY", value, buy, f"Buying {inr(value, 0)}"))
            d.cards.append(self._charges_card("SELL", value, sell, f"Selling {inr(value, 0)}"))
            d.follow_ups = ["What is STT?", "What is a DP charge?", "What is break-even?"]
            return d
        inst = self._inst(symbol)
        sym = inst.symbol
        d.symbol = sym
        q = (await self._market.summary(inst)).quote
        if q is None or not q.ltp:
            d.answer = f"No price is available for {sym} right now, so I can't cost the order."
            return d
        price = q.ltp
        basis = "live price" if q.freshness in ("live", "delayed") else "last traded price"
        assumed = ""
        if intent.quantity:
            qty = intent.quantity
        elif intent.amount:
            qty = math.floor(intent.amount / (price * 1.002))
            if qty < 1:
                d.answer = (
                    f"{inr(intent.amount, 0)} does not buy one share of {sym} at {inr(price)}."
                )
                return d
        else:
            qty, assumed = 10, " (I assumed 10 shares)"
        side = intent.side
        value = qty * price
        c = order_charges(side, value, plan)  # type: ignore[arg-type]
        if side == "BUY":
            be = break_even(price, qty, plan)
            d.answer = (
                f"Buying {qty} {sym}{assumed} at {inr(price)} ({basis}) is {inr(value)} plus "
                f"{inr(c.total)} in charges, so you pay {inr(value + c.total)}. The price must "
                f"reach {inr(be)} ({pct(be / price - 1, True, 2)}) before selling makes any "
                "money: that is the break-even after charges on both sides."
            )
        else:
            d.answer = (
                f"Selling {qty} {sym}{assumed} at {inr(price)} ({basis}) brings {inr(value)} "
                f"less {inr(c.total)} in charges, so you receive {inr(value - c.total)}."
            )
        d.answer += f" Brokerage plan: {PLANS.get(plan, plan).split(' (')[0].lower()}."
        d.book.add(d.answer, ENGINE, "measured", q.fetched_at)
        verb = "Buying" if side == "BUY" else "Selling"
        d.cards.append(self._charges_card(side, value, c, f"{verb} {qty} {sym}"))
        d.follow_ups = ["What is STT?", "How do I place an order?", f"Tell me about {sym}"]
        d.actions = [
            ChatAction(
                label="Practise this trade", to=f"/portfolios/{pid}" if pid else "/portfolios"
            )
        ]
        return d

    @staticmethod
    def _charges_card(side: str, value: float, c, title: str) -> ChatCard:
        stats = [
            Stat(label="Order value", value=inr(value)),
            Stat(label="STT", value=inr(c.stt, 0)),
        ]
        if c.stamp:
            stats.append(Stat(label="Stamp duty", value=inr(c.stamp, 0)))
        stats.append(Stat(label="Exchange + SEBI", value=inr(c.exchange + c.sebi)))
        stats.append(Stat(label="GST", value=inr(c.gst)))
        if c.brokerage:
            stats.append(Stat(label="Brokerage", value=inr(c.brokerage)))
        if c.dp:
            stats.append(Stat(label="DP charge", value=inr(c.dp)))
        total = value + c.total if side == "BUY" else value - c.total
        stats.append(Stat(label="You pay" if side == "BUY" else "You receive", value=inr(total)))
        return ChatCard(kind="stats", title=title, note=f"Charges {inr(c.total)}", stats=stats)

    def _pick_account(self, ctx: ChatContext) -> str | None:
        rows = self._db.fetchall(
            "SELECT id, coalesce(kind, 'tracking') FROM tracked_portfolios ORDER BY created_at"
        )
        ids = {r[0]: r[1] for r in rows}
        if ctx.portfolio_id in ids:
            return ctx.portfolio_id
        return next((i for i, k in ids.items() if k == "paper"), next(iter(ids), None))

    async def _account(self, intent: I.Intent, ctx: ChatContext) -> Draft:
        pid = self._pick_account(ctx)
        if pid is None:
            return Draft(
                "You don't have a portfolio yet. Open a paper account to practise with "
                "virtual money at live prices.",
                follow_ups=["How do I open a paper account?", "How do I place an order?"],
                actions=[ChatAction(label="Create an account", to="/portfolios")],
            )
        p = await self._tracker.portfolio(pid)
        d = Draft("", actions=[ChatAction(label=f"Open {p.name}", to=f"/portfolios/{pid}")])
        parts: list[str] = []
        paper = p.kind == "paper"
        if paper:
            parts.append(
                f"{p.name} is worth {inr(p.account_value or 0, 0)}, "
                f"{pct(p.account_return, True, 2)} on the {inr(p.starting_cash or 0, 0)} it "
                f"started with; {inr(p.cash or 0, 0)} of that is cash."
            )
        elif p.value is not None:
            parts.append(
                f"{p.name} is worth {inr(p.value, 0)} against {inr(p.cost, 0)} invested "
                f"({pct(p.pnl_pct, True)})."
            )
        d.book.add(parts[0] if parts else f"{p.name} has no priced holdings.", ENGINE, "measured")
        priced = [x for x in p.positions if x.pnl_pct is not None]
        if priced:
            best = max(priced, key=lambda x: x.pnl_pct or 0)
            worst = min(priced, key=lambda x: x.pnl_pct or 0)
            text = f"It holds {len({x.symbol for x in p.positions})} stock(s)"
            if best is not worst:
                text += (
                    f": {best.symbol} is doing best ({pct(best.pnl_pct, True)}) and "
                    f"{worst.symbol} worst ({pct(worst.pnl_pct, True)})"
                )
            else:
                text += f": {best.symbol} is {pct(best.pnl_pct, True)} since you bought it"
            parts.append(text + ".")
            d.book.add(parts[-1], ENGINE, "measured")
        elif not p.positions:
            parts.append("It holds no stocks yet.")
        lessons: list[str] = []
        open_orders = 0
        if paper:
            act = await self._paper.activity(pid)
            open_orders = sum(1 for o in act.orders if o.status == "OPEN")
            if open_orders:
                parts.append(
                    f"{open_orders} order{'s are' if open_orders != 1 else ' is'} open"
                    + ("" if self._clock.state()[0] == "open" else ", waiting for the market")
                    + "."
                )
            s = act.scorecard
            if s.closed_trades:
                parts.append(
                    f"Closed trades have made {inr(s.realized_net, 0)} after charges "
                    f"({s.wins} of {s.closed_trades} won)."
                )
                d.book.add(parts[-1], ENGINE, "measured")
            lessons = [re.sub(r"Rs (?=\d)", "₹", x) for x in s.lessons]
        if intent.scope == "account" and p.positions:
            period = intent.period if intent.period in ("today", "1w", "1m") else "1w"
            review = await self._tracker.review(pid, period)  # type: ignore[arg-type]
            head = re.sub(r"Rs (?=\d)", "₹", review.headline)
            parts = [head, *[re.sub(r"Rs (?=\d)", "₹", x) for x in review.points[:2]]]
            for f in review.facts[:6]:
                d.book.add(re.sub(r"Rs (?=\d)", "₹", f.text), f.source, f.basis, f.as_of)
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="What each stock did",
                    rows=[
                        Row(
                            label=s.symbol,
                            sub=f"largest factor: {s.driver}" if s.driver != "mixed" else None,
                            value=inr(s.contribution, 0),
                            change=s.return_pct,
                            to=f"/stock/{s.symbol}",
                        )
                        for s in review.stocks[:5]
                    ],
                )
            )
        d.answer = " ".join(parts)
        stats = []
        if paper:
            stats = [
                Stat(label="Account value", value=inr(p.account_value or 0, 0)),
                Stat(
                    label="Return",
                    value=pct(p.account_return, True, 2),
                    tone=_tone(p.account_return),
                ),
                Stat(label="Cash", value=inr(p.cash or 0, 0)),
                Stat(label="Realised", value=inr(p.realized, 0), tone=_tone(p.realized)),
                Stat(label="Charges paid", value=inr(p.charges_paid, 0)),
                Stat(label="Open orders", value=str(open_orders)),
            ]
        elif p.value is not None:
            stats = [
                Stat(label="Value", value=inr(p.value, 0)),
                Stat(label="Invested", value=inr(p.cost, 0)),
                Stat(label="Gain", value=pct(p.pnl_pct, True), tone=_tone(p.pnl)),
            ]
        if stats:
            d.cards.insert(0, ChatCard(kind="stats", title=p.name, stats=stats))
        if p.positions and intent.scope != "account":
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Holdings",
                    rows=[
                        Row(
                            label=x.symbol,
                            sub=f"{x.quantity:g} at {inr(x.entry_price)}",
                            value=inr(x.value, 0) if x.value is not None else None,
                            change=x.pnl_pct,
                            to=f"/stock/{x.symbol}",
                        )
                        for x in p.positions[:6]
                    ],
                )
            )
        if lessons:
            d.cards.append(
                ChatCard(kind="steps", title="What your record shows", steps=lessons[:3])
            )
        d.follow_ups = (
            ["Why did my portfolio move this week?", "How do I set a stop-loss?"]
            if p.positions
            else ["How do I place an order?", "What should I look at today?"]
        )
        if p.positions:
            d.follow_ups.append(f"Why did {p.positions[0].symbol} move this month?")
        return d

    # --- tools: IPOs, tests, attention, planner --------------------------------------------

    async def _ipos(self) -> Draft:
        try:
            o = await asyncio.wait_for(self._ipo.overview(), 30)
        except TimeoutError:
            return Draft(
                "IPO data from NSE is still loading. Ask again in a few seconds.",
                actions=[ChatAction(label="Open IPOs", to="/ipos")],
            )
        d = Draft("", actions=[ChatAction(label="Open IPOs", to="/ipos")])
        parts: list[str] = []
        if o.open:
            names = ", ".join(i.company for i in o.open[:4])
            parts.append(f"{len(o.open)} IPO(s) are open for bidding on NSE: {names}.")
        else:
            parts.append("No IPO is open for bidding on NSE right now.")
        d.book.add(parts[-1], NSE, "observed", o.as_of)
        mood = next((m for m in o.mood if m.listed), None)
        if mood and mood.above_issue_at_open is not None:
            parts.append(
                f"Of {mood.listed} mainboard IPOs listed in the last {mood.days} days, "
                f"{mood.above_issue_at_open:.0%} opened above their issue price"
                + (
                    f", with a median listing move of {pct(mood.median_listing_gain, True)}"
                    if mood.median_listing_gain is not None
                    else ""
                )
                + "."
            )
            d.book.add(parts[-1], ENGINE, "measured")
        strong = next((t for t in reversed(o.odds_table) if t.sample >= 8), None)
        weak = next((t for t in o.odds_table if t.sample >= 8), None)
        if strong and weak and strong is not weak:
            parts.append(
                f"Institutional demand has mattered: issues with QIB demand {strong.bucket} "
                f"opened higher {strong.above_issue:.0%} of the time ({strong.sample} issues), "
                f"against {weak.above_issue:.0%} for {weak.bucket} ({weak.sample} issues). "
                "That is a record of the past, not a forecast."
            )
            d.book.add(parts[-1], ENGINE, "measured")
        d.answer = " ".join(parts)
        live = o.open + o.upcoming
        if live:
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Open and upcoming",
                    rows=[
                        Row(
                            label=i.company,
                            sub=f"{i.stage} · closes {i.close_date:%d %b}"
                            if i.close_date
                            else i.stage,
                            value=f"{i.subscription.total:.1f}x"
                            if i.subscription and i.subscription.total
                            else None,
                            to=f"/ipos/{i.symbol}",
                        )
                        for i in live[:5]
                    ],
                )
            )
        recent = [i for i in o.recent_listings if i.listing and i.listing.listing_gain is not None]
        if recent:
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Latest listings",
                    note="Change shown is the listing-day open against the issue price",
                    rows=[
                        Row(
                            label=i.company,
                            sub=f"listed {i.listing_date:%d %b}" if i.listing_date else None,
                            change=i.listing.listing_gain,
                            to=f"/ipos/{i.symbol}",
                        )
                        for i in recent[:5]
                    ],
                )
            )
        if o.odds_table:
            d.cards.append(
                ChatCard(
                    kind="rows",
                    title="Track record by institutional (QIB) demand",
                    rows=[
                        Row(
                            label=f"QIB {t.bucket}",
                            sub=f"{t.sample} issues · {t.above_issue:.0%} opened higher",
                            change=t.average_gain,
                        )
                        for t in o.odds_table
                    ],
                )
            )
        d.follow_ups = ["What is QIB?", "What does times subscribed mean?", "How do I read an IPO?"]
        return d

    async def _backtest(self, symbol: str, preset: str, years: int) -> Draft:
        inst = self._inst(symbol)
        sym = inst.symbol
        name, rules = PRESETS.get(preset, PRESETS["dip"])
        result = await self._strategies.backtest(
            BacktestIn(symbols=[sym], rules=rules, years=years, capital=100_000)
        )
        d = Draft("", symbol=sym, actions=[ChatAction(label="Open Strategy Lab", to="/lab")])
        if not result.results:
            d.answer = f"I could not test {sym}: " + " ".join(result.skipped)
            return d
        r = result.results[0]
        d.answer = (
            f"{name} on {sym} over {years} years, starting with {inr(100_000, 0)}. "
            f"{' '.join(result.rules_text)} {r.verdict}"
        )
        d.book.add(" ".join(result.rules_text), ENGINE, "observed")
        d.book.add(r.verdict, ENGINE, "replay")
        closed = [t for t in r.trades if t.exit_reason != "still held"]
        stats = [
            Stat(label="Rules", value=pct(r.total_return, True), tone=_tone(r.total_return)),
            Stat(label="Buy and hold", value=pct(r.hold_return, True), tone=_tone(r.hold_return)),
        ]
        if r.index_return is not None:
            stats.append(
                Stat(label="NIFTY 50", value=pct(r.index_return, True), tone=_tone(r.index_return))
            )
        stats += [
            Stat(label="Closed trades", value=str(len(closed))),
            Stat(label="Win rate", value=pct(r.win_rate) if r.win_rate is not None else "n/a"),
            Stat(label="Worst fall", value=pct(r.max_drawdown), tone="down"),
        ]
        d.cards.append(
            ChatCard(
                kind="stats",
                title=f"{name} on {sym}",
                note="Signals at the close, fills at the next open, all charges included",
                stats=stats,
            )
        )
        d.cards.append(
            ChatCard(
                kind="spark", title="Growth of the account", points=[p.value for p in r.equity]
            )
        )
        others = [k for k in PRESETS if k != preset][:2]
        ask = {
            "dip": "Test buying the dips",
            "golden_cross": "Test golden cross",
            "momentum": "Test momentum",
            "breakout": "Test a 52-week high breakout",
        }
        d.follow_ups = [f"{ask[k]} on {sym}" for k in others] + ["What is out-of-sample?"]
        return d

    async def _attention(self) -> Draft:
        feed = await self._today.feed()
        d = Draft("")
        if not feed.nudges:
            d.answer = (
                "Nothing needs your attention right now: no large moves in your watchlist, "
                "no open orders waiting and no IPO closing today."
            )
            d.follow_ups = ["How is the market doing?", "How am I doing in my account?"]
            return d
        top = feed.nudges[:5]
        d.answer = f"{len(top)} thing{'s' if len(top) != 1 else ''} worth a look. " + " ".join(
            f"{n.title}." for n in top[:3]
        )
        d.cards.append(
            ChatCard(
                kind="rows",
                title="Worth a look",
                rows=[Row(label=n.title, sub=n.body, to=n.action_to) for n in top],
            )
        )
        d.follow_ups = [n.ask for n in top if n.ask][:3]
        return d

    async def _planner(self, req: ChatRequest) -> Draft:
        out = await self._assistant.ask(
            AskRequest(question=req.question[:500], history=req.history[-6:])
        )
        d = Draft(out.answer, actions=[ChatAction(label="Open Planner", to="/portfolio")])
        d.book.facts = list(out.cited)
        d.notice = out.notice
        d.follow_ups = ["Compare the objectives", "What should I look at today?"]
        return d
