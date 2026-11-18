"""What deserves the user's attention right now. Pure rules over a snapshot: no I/O.

Each rule looks at facts the app already holds (accounts, orders, watchlist prices, IPOs,
strategies) and may produce one nudge: a plain statement, why it matters, and a next step.
Rules never predict; they point at things that are true now. Thresholds are constants here
so they can be explained and tested.
"""

from dataclasses import dataclass, field
from datetime import date

from app.schemas.chat import Nudge, ProgressStep

CONCENTRATION = 0.40  # one stock above this share of an account
BIG_SINCE_ENTRY = 0.08  # a holding this far from its buy price
BIG_DAY = 0.03  # a watched stock's move in one session
NEAR_HIGH = 0.02  # within this of the 52-week high
NEAR_LOW = 0.03  # within this of the 52-week low
RSI_LOW, RSI_HIGH = 30.0, 70.0
BREADTH = 0.8  # share of sectors moving one way
STRONG_QIB = 10.0
MAX_NUDGES = 8
_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Holding:
    symbol: str
    value: float | None
    pnl_pct: float | None  # after buy charges, a fraction
    has_stop: bool


@dataclass
class Account:
    id: str
    name: str
    value: float
    cash: float
    orders_total: int
    open_orders: int
    closed_trades: int
    reasons_written: int
    holdings: list[Holding] = field(default_factory=list)


@dataclass
class Watch:
    symbol: str
    day_pct: float | None = None  # a fraction
    from_high: float | None = None  # 0 at the 52-week high, negative below it
    from_low: float | None = None  # 0 at the 52-week low, positive above it
    rsi: float | None = None


@dataclass
class OpenIpo:
    symbol: str
    company: str
    closes: date | None
    qib: float | None
    board: str = "mainboard"


@dataclass
class Snapshot:
    today: date
    market_open: bool
    accounts: list[Account] = field(default_factory=list)
    watch: list[Watch] = field(default_factory=list)
    research_changes: list[tuple[str, str]] = field(default_factory=list)  # (symbol, title)
    ipos: list[OpenIpo] = field(default_factory=list)
    strategies_saved: int = 0
    strategy_notes: list[tuple[str, str]] = field(default_factory=list)  # (name, note)
    sectors_up: int = 0
    sectors_total: int = 0


def _pct(v: float, digits: int = 1) -> str:
    return f"{abs(v) * 100:.{digits}f}%"


def _account_nudges(s: Snapshot) -> list[Nudge]:
    out: list[Nudge] = []
    if not s.accounts:
        return [
            Nudge(
                id="start:account",
                kind="start",
                severity="medium",
                title="Open a paper account to start practising",
                body="You get virtual cash, live prices and the real charges on every order, "
                "so mistakes cost nothing.",
                action_label="Create an account",
                action_to="/portfolios",
                ask="How do I open a paper account?",
            )
        ]
    for a in s.accounts:
        to = f"/portfolios/{a.id}"
        if a.orders_total == 0:
            out.append(
                Nudge(
                    id=f"start:order:{a.id}",
                    kind="start",
                    severity="medium",
                    title=f"{a.name} is all cash: place your first practice trade",
                    body="Pick a company you know, write why you are buying, and set a "
                    "stop-loss. The journal will show how that reasoning held up.",
                    action_label="Open the account",
                    action_to=to,
                    ask="How do I place an order?",
                )
            )
            continue
        for h in a.holdings:
            share = h.value / a.value if h.value and a.value else 0.0
            if share > CONCENTRATION:
                out.append(
                    Nudge(
                        id=f"conc:{a.id}:{h.symbol}",
                        kind="account",
                        severity="high",
                        symbol=h.symbol,
                        title=f"{h.symbol} is {share:.0%} of {a.name}",
                        body="One stock this large decides the whole account's result. "
                        "Spreading across a few stocks limits the damage of one bad pick.",
                        action_label="Review holdings",
                        action_to=to,
                        ask="What does diversification mean?",
                    )
                )
            if not h.has_stop:
                out.append(
                    Nudge(
                        id=f"stop:{a.id}:{h.symbol}",
                        kind="account",
                        severity="medium",
                        symbol=h.symbol,
                        title=f"{h.symbol} has no stop-loss",
                        body="Without one, the decision to sell a falling stock is made in "
                        "the moment. A stop-loss order makes it in advance.",
                        action_label="Add a stop-loss",
                        action_to=to,
                        ask="How do I set a stop-loss?",
                    )
                )
            if h.pnl_pct is not None and abs(h.pnl_pct) >= BIG_SINCE_ENTRY:
                up = h.pnl_pct > 0
                out.append(
                    Nudge(
                        id=f"move:{a.id}:{h.symbol}",
                        kind="account",
                        severity="medium" if not up else "low",
                        symbol=h.symbol,
                        title=f"{h.symbol} is {'up' if up else 'down'} {_pct(h.pnl_pct)} "
                        "since you bought it",
                        body="Check whether your reason for buying still holds, and what "
                        "moved it: the market, its sector or the company."
                        if not up
                        else "Worth checking what drove it, and whether your target or "
                        "stop should move.",
                        action_label="See why",
                        action_to=to,
                        ask=f"Why did {h.symbol} move this month?",
                    )
                )
        if a.open_orders and not s.market_open:
            n = a.open_orders
            out.append(
                Nudge(
                    id=f"orders:{a.id}",
                    kind="account",
                    severity="low",
                    title=f"{n} order{'s' if n != 1 else ''} waiting in {a.name}",
                    body="The market is closed. Market orders fill at the first trade after "
                    "the open; limit and stop orders wait for their price.",
                    action_label="View orders",
                    action_to=to,
                    ask="What is an after-market order?",
                )
            )
        if a.closed_trades >= 3:
            out.append(
                Nudge(
                    id=f"score:{a.id}:{a.closed_trades}",
                    kind="account",
                    severity="low",
                    title=f"Your scorecard has {a.closed_trades} closed trades to learn from",
                    body="Win rate, charges and how you did against simply holding the "
                    "NIFTY 50 over the same dates.",
                    action_label="Open scorecard",
                    action_to=to,
                    ask="How am I doing in my account?",
                )
            )
    return out


def _watch_nudges(s: Snapshot) -> list[Nudge]:
    out: list[Nudge] = []
    for w in s.watch:
        to = f"/stock/{w.symbol}"
        if w.day_pct is not None and abs(w.day_pct) >= BIG_DAY:
            up = w.day_pct > 0
            out.append(
                Nudge(
                    id=f"day:{w.symbol}:{s.today}",
                    kind="watchlist",
                    severity="medium",
                    symbol=w.symbol,
                    title=f"{w.symbol} {'rose' if up else 'fell'} {_pct(w.day_pct)} "
                    f"{'today' if s.market_open else 'in the last session'}",
                    body="A move this size usually has a cause: results, news or the "
                    "whole sector moving.",
                    action_label="Open chart",
                    action_to=to,
                    ask=f"Why did {w.symbol} move today?",
                )
            )
        if w.from_high is not None and w.from_high >= -NEAR_HIGH:
            out.append(
                Nudge(
                    id=f"high:{w.symbol}",
                    kind="watchlist",
                    severity="low",
                    symbol=w.symbol,
                    title=f"{w.symbol} is within {_pct(max(-w.from_high, 0.0))} of its "
                    "52-week high",
                    body="Some traders buy strength near a high; others wait for a "
                    "pull-back. You can test either idea on its past prices.",
                    action_label="Open chart",
                    action_to=to,
                    ask=f"Test a 52-week high breakout on {w.symbol}",
                )
            )
        elif w.from_low is not None and w.from_low <= NEAR_LOW:
            out.append(
                Nudge(
                    id=f"low:{w.symbol}",
                    kind="watchlist",
                    severity="medium",
                    symbol=w.symbol,
                    title=f"{w.symbol} is within {_pct(max(w.from_low, 0.0))} of its 52-week low",
                    body="Cheap can get cheaper. See what has been driving it before "
                    "treating a low as a bargain.",
                    action_label="Open chart",
                    action_to=to,
                    ask=f"Why did {w.symbol} fall this year?",
                )
            )
        elif w.rsi is not None and (w.rsi <= RSI_LOW or w.rsi >= RSI_HIGH):
            low = w.rsi <= RSI_LOW
            out.append(
                Nudge(
                    id=f"rsi:{w.symbol}:{'low' if low else 'high'}",
                    kind="watchlist",
                    severity="low",
                    symbol=w.symbol,
                    title=f"{w.symbol} RSI is {w.rsi:.0f}: "
                    f"{'heavily sold' if low else 'stretched after a run'}",
                    body="RSI compares recent gains with recent losses. Extremes often "
                    "ease, but they are not a signal on their own.",
                    action_label="Open chart",
                    action_to=to,
                    ask="What is RSI?",
                )
            )
    return out


def _other_nudges(s: Snapshot) -> list[Nudge]:
    out: list[Nudge] = []
    for symbol, title in s.research_changes[:3]:
        out.append(
            Nudge(
                id=f"research:{symbol}:{title[:40]}",
                kind="research",
                severity="low",
                symbol=symbol,
                title=title,
                body="The research view summarises evidence. Replay tests have not shown "
                "it to predict returns, so read it as context.",
                action_label="Open research",
                action_to=f"/stock/{symbol}",
                ask=f"Tell me about {symbol}",
            )
        )
    for i in s.ipos:
        last_day = i.closes is not None and i.closes == s.today
        strong = i.qib is not None and i.qib >= STRONG_QIB
        if not (last_day or strong):
            continue
        bits = []
        if last_day:
            bits.append("bidding closes today")
        if i.qib is not None:
            bits.append(f"institutions have bid {i.qib:.1f}x their portion")
        out.append(
            Nudge(
                id=f"ipo:{i.symbol}",
                kind="ipo",
                severity="medium" if last_day else "low",
                symbol=i.symbol,
                title=f"{i.company} IPO: {' and '.join(bits)}",
                body="Institutional demand has been the clearest single guide to how past "
                "issues listed." + (" SME issues carry extra risk." if i.board == "sme" else ""),
                action_label="Open the issue",
                action_to=f"/ipos/{i.symbol}",
                ask="How have IPOs with strong institutional demand listed?",
            )
        )
    for name, note in s.strategy_notes[:2]:
        out.append(
            Nudge(
                id=f"strategy:{name}:{note[:30]}",
                kind="strategy",
                severity="medium",
                title=f"Strategy {name} acted",
                body=note,
                action_label="Open Strategy Lab",
                action_to="/lab",
            )
        )
    if s.sectors_total >= 8:
        share = s.sectors_up / s.sectors_total
        if share >= BREADTH or share <= 1 - BREADTH:
            broad_up = share >= BREADTH
            out.append(
                Nudge(
                    id=f"breadth:{s.today}:{'up' if broad_up else 'down'}",
                    kind="market",
                    severity="low",
                    title=(
                        f"{s.sectors_up} of {s.sectors_total} sectors rose: a broad rally"
                        if broad_up
                        else f"{s.sectors_total - s.sectors_up} of {s.sectors_total} sectors "
                        "fell: a broad decline"
                    ),
                    body="When nearly everything moves together, most of any one stock's "
                    "move is the market, not the company.",
                    action_label="Open Markets",
                    action_to="/markets",
                    ask="How is the market doing?",
                )
            )
    return out


def build_nudges(s: Snapshot) -> list[Nudge]:
    """Every nudge the snapshot supports, most important first, capped."""
    items = _account_nudges(s) + _watch_nudges(s) + _other_nudges(s)
    seen: set[str] = set()
    unique = [n for n in items if not (n.id in seen or seen.add(n.id))]
    kind_rank = {"account": 0, "start": 1, "ipo": 2, "strategy": 3, "watchlist": 4}
    unique.sort(key=lambda n: (_ORDER[n.severity], kind_rank.get(n.kind, 5)))
    return unique[:MAX_NUDGES]


def build_progress(s: Snapshot, watching: int) -> list[ProgressStep]:
    """The beginner's path, ticked off from what the user has actually done."""
    orders = sum(a.orders_total for a in s.accounts)
    reasons = sum(a.reasons_written for a in s.accounts)
    closed = sum(a.closed_trades for a in s.accounts)
    account_to = f"/portfolios/{s.accounts[0].id}" if s.accounts else "/portfolios"
    return [
        ProgressStep(key="watch", label="Star a stock you know", done=watching > 0, to="/markets"),
        ProgressStep(
            key="account", label="Open a paper account", done=bool(s.accounts), to="/portfolios"
        ),
        ProgressStep(key="order", label="Place a practice trade", done=orders > 0, to=account_to),
        ProgressStep(key="reason", label="Write why you bought", done=reasons > 0, to=account_to),
        ProgressStep(
            key="strategy", label="Test an idea in the lab", done=s.strategies_saved > 0, to="/lab"
        ),
        ProgressStep(
            key="close",
            label="Close a trade and read your scorecard",
            done=closed > 0,
            to=account_to,
        ),
    ]
