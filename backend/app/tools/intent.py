"""Reads a question and decides which tool should answer it. Pure rules: no I/O, no model.

The router is deliberately transparent. Each decision names the rule that fired, so a wrong
answer can be traced to a line here, and its accuracy is measured on a labelled question set
in ``tests/test_intent.py``.

Tools
- glossary   what a market term means
- charges    what an order costs, and the break-even price
- why        why a stock moved over a period (market, sector, company)
- account    the user's paper account: value, holdings, orders, lessons
- ipo        open issues, recent listings, the listing track record
- backtest   test a classic rule on a stock's past prices
- market     indices, sector breadth, movers
- today      what deserves attention right now
- howto      how to do something in the app
- planner    plan-level what-ifs, objective comparisons and goals
- stock      a snapshot of one stock
- help       greetings and "what can you do"
- unknown    nothing matched: say so and offer what can be answered
"""

import re
from dataclasses import dataclass, field

from app.tools.glossary import GLOSSARY

# Capitalised tokens that are market vocabulary, never a stock the user means.
NOT_SYMBOLS = {
    "STT", "RSI", "IPO", "IPOS", "GTC", "AMO", "FIFO", "QIB", "QIBS", "NII", "RII", "HNI",
    "CAGR", "LTCG", "STCG", "NSE", "BSE", "SIP", "GST", "DP", "PE", "SL", "ETF", "NIFTY",
    "SENSEX", "UPI", "SMA", "DMA", "EMA", "VIX", "PNL", "FAQ", "OK", "I", "A", "IT", "AI",
    "SME", "RHP", "FII", "DII", "ROE", "EPS", "IC",
}  # fmt: skip
# Lower-case words that are also NSE symbols or company first names: too ambiguous to accept
# unless the user already follows that stock.
AMBIGUOUS = {
    "idea", "oil", "just", "can", "gold", "best", "home", "max", "ace", "sun", "star", "page",
    "coal", "bank", "india", "indian", "power", "global", "united", "general", "national",
    "central", "state", "life", "first", "future", "info", "tech", "new", "great", "action",
    "fact", "route", "signature", "campus", "gland", "graphite", "safari", "trident", "swan",
    "sail", "metropolis", "rec", "bse", "nse", "team", "happy", "blue", "aditya", "tata",
    "bajaj", "adani", "mahindra", "godrej", "jindal", "hindustan", "bharat", "steel", "cement",
    "pharma", "finance", "capital", "energy", "green", "data", "one", "five", "sell", "buy",
    "market", "stock", "share", "price", "today", "week", "month", "year", "test", "trade",
    "target", "stop", "loss", "limit", "order", "cash", "value", "high", "low", "open", "close",
    "the", "and", "for", "with", "why", "how", "what", "who", "when", "does", "did", "has",
    "are", "was", "its", "this", "that", "from", "into", "over", "about", "than", "then",
    "mrs", "amber", "aster", "elecon", "angel", "cera", "vip", "ion", "pcs", "bls", "ami",
}  # fmt: skip
COMMON_NAMES = {
    "reliance": "RELIANCE",
    "sbi": "SBIN",
    "state bank": "SBIN",
    "airtel": "BHARTIARTL",
    "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK",
    "kotak": "KOTAKBANK",
    "axis bank": "AXISBANK",
    "larsen": "LT",
    "l&t": "LT",
    "infosys": "INFY",
    "maruti": "MARUTI",
    "jio": "JPL",
}

TERM_ALIASES = {
    "stop loss": "stop-loss",
    "stoploss": "stop-loss",
    "sl order": "stop-loss",
    "breakeven": "break-even",
    "break even": "break-even",
    "break-even price": "break-even",
    "sma": "moving average",
    "dma": "moving average",
    "moving averages": "moving average",
    "pe": "P/E",
    "pe ratio": "P/E",
    "p/e ratio": "P/E",
    "52 week high": "52-week high",
    "52w high": "52-week high",
    "dp charges": "DP charge",
    "dp": "DP charge",
    "circuit": "circuit limit",
    "upper circuit": "circuit limit",
    "lower circuit": "circuit limit",
    "ex dividend": "ex-dividend",
    "listing gains": "listing gain",
    "qibs": "QIB",
    "hni": "NII",
    "retail investor": "RII",
    "retail investors": "RII",
    "times subscribed": "subscription",
    "oversubscribed": "subscription",
    "oversubscription": "subscription",
    "after market order": "AMO",
    "good till cancelled": "GTC",
    "max drawdown": "drawdown",
    "maximum drawdown": "drawdown",
    "backtesting": "backtest",
    "out of sample": "out-of-sample",
    "buy and hold": "buy-and-hold",
    "realised": "realised P&L",
    "unrealised": "realised P&L",
    "realized": "realised P&L",
    "capital gains": "STCG",
    "capital gains tax": "STCG",
    "short term capital gains": "STCG",
    "long term capital gains": "LTCG",
    "securities transaction tax": "STT",
    "nifty": "NIFTY 50",
    "lot": "lot size",
    "index": "benchmark",
    "limit": "limit order",
    "market orders": "market order",
    "limit orders": "limit order",
}

HOWTO_TOPICS: tuple[tuple[str, str], ...] = (
    (r"\b(stop.?loss|target)\b", "stop_loss"),
    (r"\bcancel\b", "cancel_order"),
    (r"\b(sell|exit|close (a |my )?(position|trade))\b", "sell"),
    (r"\b(place|buy|order|trade)\b", "place_order"),
    (r"\b(paper|practice|practise|virtual|account|portfolio)\b", "open_account"),
    (r"\b(back-?test|strategy|strategies|rules?|lab)\b", "backtest"),
    (r"\b(star|watch ?list|follow|track)\b", "watchlist"),
    (r"\b(ipo|apply)\b", "ipo"),
    (r"\b(journal|reason|scorecard)\b", "journal"),
)

PRESETS: tuple[tuple[str, str], ...] = (
    (r"golden cross|50.?day.*200.?day|crossover", "golden_cross"),
    (r"momentum|trend following|trend-following", "momentum"),
    (r"break-?out|52.?week high|new high", "breakout"),
    (r"\bdips?\b|oversold|pull-?back|rsi|mean reversion", "dip"),
)

PERIODS: tuple[tuple[str, str], ...] = (
    (r"\btoday\b|\bthis session\b|\bintraday\b", "today"),
    (r"\b(3|three) months?\b|\bquarter\b", "3m"),
    (r"\b(6|six) months?\b|\bhalf.year\b", "6m"),
    (r"\b(1 |one |a |past |last |this )?year\b|\b12 months\b|\b1y\b", "1y"),
    (r"\bmonth\b|\b30 days\b|\b1m\b", "1m"),
    (r"\bweek\b|\b7 days\b|\b1w\b|\bfew days\b|\brecently\b|\blately\b", "1w"),
)

_UNITS = {"crore": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "k": 1e3}
_AMOUNT = re.compile(
    r"(?:(₹|rs\.?|inr)\s*)?(\d[\d,]*(?:\.\d+)?)\s*(crore|cr|lakhs?|lac|k)?\b(?:\s*(rupees|rs))?",
    re.I,
)
_QTY = re.compile(
    r"\b(\d{1,6})\s*(?:shares?|qty|quantity|units?|stocks?)\b"
    r"|\b(?:buy|sell|buying|selling|of)\s+(\d{1,6})\b(?!\s*(?:k\b|lakh|lac|crore|,\d|\.\d|%|rs|rupees))",
    re.I,
)
_PRONOUN = re.compile(r"\b(it|its|it's|this stock|that stock|this one|the stock|this share)\b")
_DEFINE = re.compile(
    r"^(?:so\s+)?(?:what(?:'s| is| are| does| do)|whats|define|explain|meaning of|"
    r"tell me about|what do you mean by)\s+",
    re.I,
)


@dataclass
class Intent:
    tool: str
    rule: str = ""  # the rule that fired, for transparency and tests
    symbols: list[str] = field(default_factory=list)
    quantity: int | None = None
    amount: float | None = None
    side: str = "BUY"
    term: str | None = None
    period: str | None = None
    preset: str | None = None
    years: int | None = None
    topic: str | None = None
    scope: str | None = None  # why: "stock" | "account" | "market"


def build_aliases(pairs: list[tuple[str, str | None]]) -> dict[str, str]:
    """Lower-case ways people write a stock, from (symbol, company name) pairs: the symbol
    itself, and the company's first word when it is distinctive and names only one company."""
    out: dict[str, str] = {}
    first_words: dict[str, set[str]] = {}
    for sym, name in pairs:
        low = sym.lower()
        if len(low) >= 3 and low not in AMBIGUOUS:
            out[low] = sym
        word = re.sub(r"[^a-z&]", "", (name or "").split(" ")[0].lower()) if name else ""
        if len(word) >= 5 and word not in AMBIGUOUS:
            first_words.setdefault(word, set()).add(sym)
    for word, syms in first_words.items():
        if len(syms) == 1:
            out.setdefault(word, next(iter(syms)))
    known = {s for s, _ in pairs}
    for alias, sym in COMMON_NAMES.items():
        if sym in known:
            out[alias] = sym
    return out


def find_symbols(
    text: str, known: set[str], aliases: dict[str, str], familiar: set[str] = frozenset()
) -> list[str]:
    """Stocks named in ``text``: capitalised NSE symbols, symbols the user already follows in
    any case, and distinctive company names."""
    out: list[str] = []
    low = text.lower()
    for alias, sym in aliases.items():
        if " " in alias or "&" in alias:
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low) and sym not in out:
                out.append(sym)
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9&-]{1,19}", text):
        up = tok.upper()
        sym = None
        if tok == up and up in known and up not in NOT_SYMBOLS:
            sym = up
        elif up in familiar and tok.lower() not in AMBIGUOUS:
            sym = up
        elif tok.lower() in aliases:
            sym = aliases[tok.lower()]
        if sym and sym not in out:
            out.append(sym)
    return out


def _term_table() -> dict[str, str]:
    table = {a: k for a, k in TERM_ALIASES.items()}
    for key, (term, _, _) in GLOSSARY.items():
        table[key.lower()] = key
        table[term.lower()] = key
        short = re.sub(r"\s*\(.*\)$", "", term.lower())
        table[short] = key
    return table


_TERMS = _term_table()


def find_term(text: str) -> str | None:
    """The glossary key when ``text`` is, in substance, just a term."""
    t = re.sub(r"[?!.\"']+", "", text.lower()).strip()
    t = re.sub(r"^(a|an|the)\s+", "", t)
    t = re.sub(
        r"\s+(mean|means|meaning|stand for|stands for|in (stocks?|trading|the market|"
        r"investing|an ipo|ipos?|simple (words|terms))|exactly|please)$",
        "",
        t,
    ).strip()
    for cand in (t, t.rstrip("s"), t.replace("-", " ")):
        if cand in _TERMS:
            return _TERMS[cand]
    return None


def parse_quantity(text: str) -> int | None:
    m = _QTY.search(text)
    if not m:
        return None
    n = int(m.group(1) or m.group(2))
    return n if n > 0 else None


def parse_amount(text: str) -> float | None:
    """A rupee amount: needs a currency mark, a unit (k, lakh) or the word rupees."""
    best = None
    for m in _AMOUNT.finditer(text):
        if not (m.group(1) or m.group(3) or m.group(4)):
            continue
        v = float(m.group(2).replace(",", "")) * _UNITS.get((m.group(3) or "").lower(), 1.0)
        if v >= 100 and (best is None or v > best):
            best = v
    return best


def parse_period(text: str) -> str | None:
    low = text.lower()
    return next((p for pat, p in PERIODS if re.search(pat, low)), None)


def parse_years(text: str) -> int | None:
    m = re.search(r"\b(\d{1,2})\s*(?:years?|yrs?|y)\b", text, re.I)
    return max(1, min(10, int(m.group(1)))) if m else None


def route(
    question: str,
    known: set[str],
    aliases: dict[str, str],
    familiar: set[str] = frozenset(),
    context_symbol: str | None = None,
) -> Intent:
    q = question.strip()
    low = q.lower()
    symbols = find_symbols(q, known, aliases, familiar)
    if not symbols and context_symbol and _PRONOUN.search(low):
        symbols = [context_symbol]
    side = "SELL" if re.search(r"\b(sell|selling|sold|exit)\b", low) else "BUY"
    base = {
        "symbols": symbols,
        "quantity": parse_quantity(q),
        "amount": parse_amount(q),
        "side": side,
        "period": parse_period(q),
        "years": parse_years(q),
    }

    def hit(tool: str, rule: str, **extra) -> Intent:
        return Intent(tool=tool, rule=rule, **{**base, **extra})

    if re.fullmatch(r"(hi+|hello+|hey+|yo|namaste|good (morning|evening|afternoon))[\s!.]*", low):
        return hit("help", "greeting")
    if re.search(
        r"\b(what can you (do|answer|help)|what do you do|who are you|help me$|^help$|"
        r"how (do|can) (i|you) use (you|this))\b",
        low,
    ):
        return hit("help", "capabilities")
    if re.fullmatch(r"(thanks|thank you|thx|ok|okay|cool|great|nice)[\s!.]*", low):
        return hit("help", "thanks")

    # Definitions come first so "what is an IPO" is not read as a request for IPO data.
    lead = _DEFINE.match(q)
    term = find_term(q[lead.end() :]) if lead else find_term(q) if len(q.split()) <= 4 else None
    if term and not symbols:
        return hit("glossary", "definition", term=term)

    if not symbols and re.search(r"\bhow (do|can|should|to|would)\b", low):
        topic = next((t for pat, t in HOWTO_TOPICS if re.search(pat, low)), None)
        if topic:
            return hit("howto", f"howto:{topic}", topic=topic)

    if (
        re.search(
            r"\b(what if|objectives?|allocation|re-?balance|weights?|corpus|retire\w*|sip|"
            r"goal of|my plan|the plan|planner)\b",
            low,
        )
        or re.search(r"\b(reach|accumulate|save up to|build up to)\s+(₹|rs\.?|inr|\d)", low)
        or (re.search(r"\b(swap|replace)\b", low) and len(symbols) >= 2)
    ):
        return hit("planner", "plan question")

    if re.search(
        r"\b(charges?|fees?|brokerage|break-?even|taxes?|stt|stamp duty|"
        r"(what|how much) (does|do|will|would) it cost|cost (to|of) (buy|sell)\w*|"
        r"how much (to|will i|would i|do i) (pay|need)|total cost)\b",
        low,
    ):
        return hit("charges", "cost question")

    preset = next((p for pat, p in PRESETS if re.search(pat, low)), None)
    if re.search(
        r"\b(back-?test\w*|test (the |a |this |my |that )?(strategy|rule|idea|golden|momentum|"
        r"dip|break-?out)|simulate|would (it|this|that|\w+) have (worked|made|done)|"
        r"how (would|did) .* (strategy|rule|cross|momentum) (have )?"
        r"(do|done|perform\w*|work\w*))\b",
        low,
    ) or (preset in ("golden_cross", "breakout") and symbols):
        return hit("backtest", "strategy test", preset=preset or "dip")

    if re.search(r"\b(ipos?|listing gains?|listings?|subscription|grey market|gmp)\b", low):
        return hit("ipo", "ipo question")

    mine = re.search(
        r"\b(my|our) (paper |practice |practise )?"
        r"(open |pending |current|latest |recent |last |total |overall |best |worst )?"
        r"(account|portfolio|holdings?|positions?|"
        r"orders?|cash|trades?|journal|scorecard|p&l|pnl|profit|loss(es)?|returns?|money|"
        r"stop.?loss(es)?|balance)\b|\bhow am i doing\b|\bam i (up|down|winning|losing)\b|"
        r"\bdid my\b|\bmy (win rate|mistakes?|habits?|lessons?)\b|\bhow (are|were) my trades\b",
        low,
    )
    moved = re.search(
        r"\bwhy\b|\bwhat happened\b|\bwhat moved\b|\breason (for|behind)\b|\bwhat caused\b|"
        r"\bhow come\b|\bexplain (the )?(move|fall|drop|rise|rally|jump|crash)\b",
        low,
    )
    if moved:
        if symbols:
            return hit("why", "why:stock", scope="stock")
        if mine:
            return hit("account", "why:account", scope="account")
        if re.search(r"\b(market|nifty|sensex|index|indices|sectors?)\b", low):
            return hit("market", "why:market", scope="market")
    if mine:
        return hit("account", "account question")

    if re.search(
        r"\b(what should i (look at|watch|do|know|check)|anything (new|important|i should)|"
        r"what'?s new|whats new|for me today|insights?|heads.?up|what needs (my )?attention|"
        r"what to watch|brief me|catch me up|summary for today)\b",
        low,
    ):
        return hit("today", "attention")

    if not symbols and re.search(
        r"\b(markets?|nifty|sensex|sectors?|movers|gainers?|losers?|breadth|vix|indices|"
        r"index|bank nifty|rally|sell-?off)\b",
        low,
    ):
        return hit("market", "market question")

    if symbols:
        if re.search(
            r"\b(fell|fall\w*|drop\w*|down|crash\w*|rose|rise\w*|rising|up so much|jump\w*|"
            r"rall\w+|surg\w+|underperform\w*|outperform\w*|lagging)\b",
            low,
        ):
            return hit("why", "move words", scope="stock")
        return hit("stock", "stock named")

    if not symbols and re.search(r"\bhow (do|can|should|to|would)\b", low):
        return hit("howto", "howto:general", topic="general")
    return hit("unknown", "no rule matched")
