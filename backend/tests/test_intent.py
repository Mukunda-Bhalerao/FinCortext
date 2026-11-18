"""The assistant's question router and daily-feed rules.

``test_router_accuracy`` is the measurable one: a labelled set of questions written the way a
beginner would type them, scored as a percentage. It is the number to quote for the router.
"""

from datetime import date

import pytest

from app.tools import intent as I
from app.tools import nudges as N
from app.tools.glossary import GLOSSARY

KNOWN = {"INFY", "RELIANCE", "TCS", "HDFCBANK", "SBIN", "ITC", "WIPRO", "TITAN", "LT", "JPL"}
ALIASES = I.build_aliases(
    [
        ("INFY", "Infosys Limited"),
        ("RELIANCE", "Reliance Industries Limited"),
        ("TCS", "Tata Consultancy Services Limited"),
        ("HDFCBANK", "HDFC Bank Limited"),
        ("SBIN", "State Bank of India"),
        ("ITC", "ITC Limited"),
        ("WIPRO", "Wipro Limited"),
        ("TITAN", "Titan Company Limited"),
        ("LT", "Larsen & Toubro Limited"),
        ("JPL", "Jio Platforms Limited"),
    ]
)

# (question, expected tool). Written as a beginner would type them, including lower case.
CASES: list[tuple[str, str]] = [
    # definitions
    ("What is STT?", "glossary"),
    ("what does break-even mean", "glossary"),
    ("explain stop loss", "glossary"),
    ("what is an IPO", "glossary"),
    ("define RSI", "glossary"),
    ("what is a limit order", "glossary"),
    ("what are capital gains", "glossary"),
    ("tell me about QIB", "glossary"),
    ("what is out of sample", "glossary"),
    ("meaning of drawdown", "glossary"),
    # one stock
    ("Tell me about RELIANCE", "stock"),
    ("how is infosys doing", "stock"),
    ("TCS", "stock"),
    ("what about HDFCBANK", "stock"),
    ("give me a summary of wipro", "stock"),
    # why something moved
    ("Why did INFY fall this month?", "why"),
    ("why is reliance up so much", "why"),
    ("what happened to TITAN today", "why"),
    ("explain the drop in SBIN", "why"),
    ("why did tcs drop last week", "why"),
    ("reasons behind the ITC rally", "why"),
    # cost of an order
    ("What would it cost to buy 10 TCS?", "charges"),
    ("how much are the charges on 50 shares of INFY", "charges"),
    ("brokerage for selling 20 RELIANCE", "charges"),
    ("what is the total cost to buy 5000 rupees of ITC", "charges"),
    ("how much do i pay in fees", "charges"),
    # the user's own account
    ("How am I doing in my account?", "account"),
    ("show my holdings", "account"),
    ("what is my cash balance", "account"),
    ("am i up or down", "account"),
    ("why did my portfolio fall this week", "account"),
    ("what are my open orders", "account"),
    ("how were my trades", "account"),
    # IPOs
    ("Which IPOs are open?", "ipo"),
    ("any ipos this week", "ipo"),
    ("how have recent listings done", "ipo"),
    ("what was the subscription for the last ipo", "ipo"),
    # strategy tests
    ("Test golden cross on RELIANCE", "backtest"),
    ("backtest buying the dips on INFY", "backtest"),
    ("would momentum have worked on TCS", "backtest"),
    ("test a 52 week high breakout on HDFCBANK", "backtest"),
    ("simulate this strategy for 5 years", "backtest"),
    # market
    ("How is the market doing?", "market"),
    ("how is nifty today", "market"),
    ("which sectors are up", "market"),
    ("show me the top gainers", "market"),
    ("why is the market down", "market"),
    # attention
    ("What should I look at today?", "today"),
    ("anything important for me today", "today"),
    ("what's new", "today"),
    ("brief me", "today"),
    # how to
    ("How do I place an order?", "howto"),
    ("how to set a stop loss", "howto"),
    ("how can i cancel an order", "howto"),
    ("how do i open a paper account", "howto"),
    ("how do i follow a stock", "howto"),
    # planner
    ("what if i add ITC to my plan", "planner"),
    ("compare the objectives", "planner"),
    ("can i reach 50 lakh in 10 years", "planner"),
    # conversation
    ("hi", "help"),
    ("what can you do", "help"),
    ("thanks", "help"),
]


def _route(q: str) -> I.Intent:
    return I.route(q, KNOWN, ALIASES, familiar={"INFY", "RELIANCE"})


def test_router_accuracy():
    """The router places a labelled beginner question set. It currently scores 62/62; the bar
    leaves one miss of slack so a genuine regression fails rather than a reworded case."""
    wrong = [(q, want, _route(q).tool) for q, want in CASES if _route(q).tool != want]
    accuracy = 1 - len(wrong) / len(CASES)
    assert accuracy >= 0.95, f"router accuracy {accuracy:.0%}; wrong: {wrong}"


def test_every_tool_is_reachable():
    covered = {want for _, want in CASES}
    assert covered >= {
        "glossary", "stock", "why", "charges", "account",
        "ipo", "backtest", "market", "today", "howto", "planner", "help",
    }  # fmt: skip


def test_definitions_win_over_data_for_bare_terms():
    """'What is an IPO' explains the term; 'which IPOs are open' fetches data."""
    assert _route("what is an ipo").tool == "glossary"
    assert _route("which ipos are open").tool == "ipo"
    assert _route("what is a stop loss").tool == "glossary"
    assert _route("how do i set a stop loss").tool == "howto"


def test_market_words_are_not_read_as_stock_symbols():
    for q in ("What is STT?", "how is the IPO market", "what does RSI mean", "NSE vs BSE"):
        assert _route(q).symbols == [], q


def test_company_names_and_pronouns_resolve_to_symbols():
    assert _route("how is infosys doing").symbols == ["INFY"]
    assert _route("tell me about reliance").symbols == ["RELIANCE"]
    assert _route("state bank results").symbols == ["SBIN"]
    # "it" takes the stock the user is looking at
    assert I.route("why did it fall?", KNOWN, ALIASES, context_symbol="TCS").symbols == ["TCS"]
    assert I.route("why did it fall?", KNOWN, ALIASES).symbols == []


def test_quantities_amounts_and_periods_are_read():
    r = _route("what would it cost to buy 10 TCS")
    assert (r.quantity, r.amount, r.side) == (10, None, "BUY")
    r = _route("charges for selling 25 shares of INFY")
    assert (r.quantity, r.side) == (25, "SELL")
    r = _route("cost to buy 50,000 rupees of RELIANCE")
    assert r.amount == 50_000 and r.quantity is None
    assert _route("cost of ₹2.5 lakh of ITC").amount == 250_000
    assert _route("why did INFY fall this week").period == "1w"
    assert _route("why did INFY fall this year").period == "1y"
    assert _route("what happened to INFY today").period == "today"
    assert _route("test golden cross on TCS for 3 years").years == 3


def test_glossary_matches_the_frontend():
    """Every term the assistant can explain also exists in the interface glossary."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "glossary.ts"
    keys = set(re.findall(r'\n  (?:"([^"]+)"|([A-Za-z0-9_]+)):\s*\{', src.read_text("utf-8")))
    frontend = {a or b for a, b in keys}
    assert frontend == set(GLOSSARY), frontend.symmetric_difference(set(GLOSSARY))


# --- the daily feed --------------------------------------------------------------------------

TODAY = date(2026, 11, 18)


def _snapshot(**kw) -> N.Snapshot:
    return N.Snapshot(today=TODAY, market_open=kw.pop("market_open", False), **kw)


def test_an_empty_app_invites_the_first_step():
    feed = N.build_nudges(_snapshot())
    assert [n.kind for n in feed] == ["start"]
    assert "paper account" in feed[0].title


def test_concentration_and_missing_stop_are_flagged():
    account = N.Account(
        id="a1", name="Practice", value=100_000, cash=10_000, orders_total=3,
        open_orders=0, closed_trades=0, reasons_written=1,
        holdings=[N.Holding("INFY", value=60_000, pnl_pct=0.02, has_stop=False)],
    )  # fmt: skip
    ids = {n.id: n for n in N.build_nudges(_snapshot(accounts=[account]))}
    assert "conc:a1:INFY" in ids and "60%" in ids["conc:a1:INFY"].title
    assert ids["conc:a1:INFY"].severity == "high"
    assert "stop:a1:INFY" in ids
    # A holding that is small and protected raises neither.
    safe = N.Account(
        id="a2", name="P", value=100_000, cash=90_000, orders_total=2, open_orders=0,
        closed_trades=0, reasons_written=1,
        holdings=[N.Holding("ITC", value=10_000, pnl_pct=0.01, has_stop=True)],
    )  # fmt: skip
    assert not [n for n in N.build_nudges(_snapshot(accounts=[safe])) if n.kind == "account"]


def test_watchlist_rules_fire_on_real_thresholds():
    watch = [
        N.Watch(symbol="INFY", day_pct=0.045),
        N.Watch(symbol="TCS", day_pct=0.001, from_high=-0.005),
        N.Watch(symbol="ITC", day_pct=0.002, from_low=0.01),
        N.Watch(symbol="WIPRO", day_pct=0.000, rsi=82.0),
        N.Watch(symbol="SBIN", day_pct=0.004, from_high=-0.3, from_low=0.4, rsi=55.0),
    ]
    account = N.Account(
        id="a", name="P", value=1, cash=1, orders_total=1, open_orders=0,
        closed_trades=0, reasons_written=1,
    )  # fmt: skip
    ids = {n.id for n in N.build_nudges(_snapshot(accounts=[account], watch=watch))}
    assert {"day:INFY:2026-11-18", "high:TCS", "low:ITC", "rsi:WIPRO:high"} <= ids
    assert not [i for i in ids if i.endswith("SBIN")]  # nothing unusual about SBIN


def test_progress_follows_what_the_user_has_actually_done():
    account = N.Account(
        id="a", name="P", value=100_000, cash=50_000, orders_total=2, open_orders=0,
        closed_trades=1, reasons_written=0,
    )  # fmt: skip
    steps = {s.key: s.done for s in N.build_progress(_snapshot(accounts=[account]), watching=3)}
    assert steps == {
        "watch": True, "account": True, "order": True,
        "reason": False, "strategy": False, "close": True,
    }  # fmt: skip


@pytest.mark.parametrize("up,total,expect", [(15, 16, True), (1, 16, True), (9, 16, False)])
def test_broad_market_moves_are_called_out(up, total, expect):
    snap = _snapshot(sectors_up=up, sectors_total=total)
    assert bool([n for n in N.build_nudges(snap) if n.kind == "market"]) is expect
