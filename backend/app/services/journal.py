"""Trade journal and scorecard for a paper account: each decision next to what came of it, and
the habits the record shows. Pure functions over the account and its closed trades.

Lessons are fixed rules over the record (no language model): each needs a minimum number of
trades before it is shown, so one lucky or unlucky trade does not produce a "pattern".
"""

from collections import defaultdict
from datetime import datetime

from app.schemas.paper import ClosedTrade, JournalEntry, Scorecard, TagStat, TaxYear
from app.schemas.tracker import TrackedPortfolio
from app.tools.backtest import TaxModel, capital_gains_tax
from app.tools.market_hours import to_ist

MIN_FOR_PATTERN = 3
TAX = TaxModel()


def _pct(v: float) -> str:
    return f"{v * 100:+.1f}%"


def _rs(v: float) -> str:
    return f"{'-' if v < 0 else '+'}Rs {abs(v):,.0f}"


def verdict(ret: float | None, index: float | None, closed: bool) -> str:
    if ret is None:
        return "No price yet."
    lead = "Closed" if closed else "So far"
    if index is None:
        return f"{lead}: {_pct(ret)}."
    vs = f"NIFTY 50 {_pct(index)} over the same dates"
    if ret > 0 and ret > index:
        return f"{lead}: {_pct(ret)}, ahead of the market ({vs})."
    if ret > 0:
        return f"{lead}: {_pct(ret)}, but holding the index would have done better ({vs})."
    if ret > index:
        return f"{lead}: {_pct(ret)}, a loss but smaller than the market's ({vs})."
    return f"{lead}: {_pct(ret)} while the market did better ({vs})."


def build_journal(
    portfolio: TrackedPortfolio,
    trades: list[ClosedTrade],
    lots: dict[str, tuple],
    sources: dict[str, str],
    index_now: float | None,
) -> list[JournalEntry]:
    out: list[JournalEntry] = []
    for p in portfolio.positions:
        index_entry, order_id = lots.get(p.id, (None, None))
        cost = p.cost + p.charges
        ret = (p.value - cost) / cost if p.value is not None and cost else None
        index_ret = index_now / index_entry - 1 if index_now and index_entry else None
        out.append(
            JournalEntry(
                kind="open",
                symbol=p.symbol,
                at=p.entry_at,
                quantity=p.quantity,
                price=p.entry_price,
                reason=p.reason,
                tag=p.tag,
                outcome_pct=ret,
                outcome=p.value - cost if p.value is not None else None,
                index_return=index_ret,
                verdict=verdict(ret, index_ret, closed=False),
                source=sources.get(order_id) if order_id else None,
            )
        )
    for t in trades:
        out.append(
            JournalEntry(
                kind="closed",
                symbol=t.symbol,
                at=t.buy_at,
                quantity=t.quantity,
                price=t.buy_price,
                reason=t.buy_reason,
                tag=t.buy_tag,
                outcome_pct=t.return_pct,
                outcome=t.net,
                index_return=t.index_return,
                verdict=verdict(t.return_pct, t.index_return, closed=True)
                + (f" Sold after {t.holding_days} days" if t.holding_days else " Sold same day")
                + (f": {t.sell_reason}" if t.sell_reason else "."),
                source=t.source,
            )
        )
    out.sort(key=lambda e: e.at, reverse=True)
    return out


def _fy(moment: datetime) -> str:
    d = to_ist(moment).date()
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY {start}-{str(start + 1)[-2:]}"


def tax_years(trades: list[ClosedTrade]) -> list[TaxYear]:
    """Estimated capital gains tax per financial year. STT is not deductible, so it is added
    back to the net gain; losses carry forward between years."""
    years: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for t in trades:
        stt = round(t.buy_price * t.quantity * 0.001) + round(t.sell_price * t.quantity * 0.001)
        taxable = t.net + stt
        years[_fy(t.sell_at)][1 if t.term == "long" else 0] += taxable
    out = []
    carry = (0.0, 0.0)
    for fy in sorted(years):
        st, lt = years[fy]
        due, carry = capital_gains_tax(st, lt, carry, TAX)
        out.append(
            TaxYear(
                year=fy,
                short_term_gain=st,
                long_term_gain=lt,
                estimated_tax=due,
                note=(
                    "Short-term gains (held 12 months or less) at 20%; long-term at 12.5% above "
                    "Rs 1.25 lakh a year. STT is not deductible. An estimate for learning, "
                    "not tax advice."
                ),
            )
        )
    return out


def build_scorecard(
    portfolio: TrackedPortfolio, trades: list[ClosedTrade], journal: list[JournalEntry]
) -> Scorecard:
    wins = [t for t in trades if t.net > 0]
    losses = [t for t in trades if t.net <= 0]
    gross_profit = sum(t.gross for t in trades if t.gross > 0)
    charges = sum(t.charges for t in trades)
    profit_won = sum(t.net for t in wins)
    profit_lost = -sum(t.net for t in losses)
    compared = [t for t in trades if t.beat_index is not None]
    index_equivalent = (
        sum((t.buy_price * t.quantity) * t.index_return for t in compared) if compared else None
    )
    tags: dict[str, list[ClosedTrade]] = defaultdict(list)
    for t in trades:
        tags[t.buy_tag or "No tag"].append(t)
    by_tag = [
        TagStat(
            tag=tag,
            trades=len(ts),
            wins=sum(t.net > 0 for t in ts),
            net=sum(t.net for t in ts),
            average_return=sum(t.return_pct for t in ts) / len(ts),
        )
        for tag, ts in sorted(tags.items(), key=lambda kv: -len(kv[1]))
    ]

    def avg(xs):
        xs = list(xs)
        return sum(xs) / len(xs) if xs else None

    days_w = avg(t.holding_days for t in wins)
    days_l = avg(t.holding_days for t in losses)
    lessons = lessons_for(portfolio, trades, journal, by_tag, charges, gross_profit, days_w, days_l)
    return Scorecard(
        closed_trades=len(trades),
        open_positions=len(portfolio.positions),
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / len(trades) if trades else None,
        average_win=avg(t.return_pct for t in wins),
        average_loss=avg(t.return_pct for t in losses),
        best=max(trades, key=lambda t: t.return_pct) if trades else None,
        worst=min(trades, key=lambda t: t.return_pct) if trades else None,
        profit_factor=profit_won / profit_lost if profit_lost > 0 else None,
        realized_net=sum(t.net for t in trades),
        charges_paid=portfolio.charges_paid,
        charges_share_of_gross=charges / gross_profit if gross_profit > 0 else None,
        days_held_winners=days_w,
        days_held_losers=days_l,
        beat_index=sum(bool(t.beat_index) for t in compared),
        compared=len(compared),
        index_equivalent=index_equivalent,
        by_tag=by_tag,
        tax=tax_years(trades),
        lessons=lessons,
    )


def lessons_for(
    portfolio, trades, journal, by_tag, charges, gross_profit, days_w, days_l
) -> list[str]:
    out: list[str] = []
    n = len(trades)
    if n == 0:
        out.append(
            "Close a trade (sell what you bought) to start your scorecard. Until then, the "
            "journal shows how each open position is doing against the market."
        )
    if gross_profit > 0 and charges / gross_profit >= 0.1 and n >= 2:
        out.append(
            f"Charges took {charges / gross_profit:.0%} of your gross profit ({_rs(-charges)}). "
            "Fewer, larger trades keep more of what you make."
        )
    wins = [t for t in trades if t.net > 0]
    losses = [t for t in trades if t.net <= 0]
    if (
        len(wins) >= 2
        and len(losses) >= 2
        and days_w is not None
        and days_l is not None
        and days_l > 1.5 * max(days_w, 1)
    ):
        out.append(
            f"You hold losing trades longer than winning ones ({days_l:.0f} vs {days_w:.0f} days "
            "on average). This is the most common beginner habit: selling winners early and "
            "hoping losers recover. Deciding a stop-loss before buying helps."
        )
    compared = [t for t in trades if t.beat_index is not None]
    if len(compared) >= MIN_FOR_PATTERN:
        beat = sum(bool(t.beat_index) for t in compared)
        if beat * 2 < len(compared):
            out.append(
                f"Only {beat} of {len(compared)} closed trades beat simply holding the NIFTY 50 "
                "over the same dates. An index fund is the benchmark any stock pick has to beat."
            )
        else:
            out.append(
                f"{beat} of {len(compared)} closed trades beat the NIFTY 50 over the same dates."
            )
    for s in by_tag:
        if s.trades >= MIN_FOR_PATTERN and s.tag != "No tag":
            if s.wins * 3 <= s.trades:
                out.append(
                    f"Trades tagged '{s.tag}' worked {s.wins} of {s.trades} times "
                    f"({_rs(s.net)} in total)."
                )
            elif s.wins * 3 >= 2 * s.trades:
                out.append(
                    f"Your '{s.tag}' trades worked {s.wins} of {s.trades} times "
                    f"({_rs(s.net)}): your best-tested reason so far."
                )
    if n >= MIN_FOR_PATTERN:
        rate = len(wins) / n
        avg_w = sum(t.return_pct for t in wins) / len(wins) if wins else 0.0
        avg_l = sum(t.return_pct for t in losses) / len(losses) if losses else 0.0
        if rate < 0.5 and avg_w > abs(avg_l) and sum(t.net for t in trades) > 0:
            out.append(
                f"You win {rate:.0%} of trades but your average winner ({_pct(avg_w)}) is bigger "
                f"than your average loser ({_pct(avg_l)}), so you are still ahead."
            )
        elif rate >= 0.5 and avg_w and abs(avg_l) > 2 * avg_w:
            out.append(
                f"You win {rate:.0%} of trades, but losers ({_pct(avg_l)} on average) are much "
                f"bigger than winners ({_pct(avg_w)}). A few large losses can undo many wins."
            )
    unexplained = [e for e in journal if not e.reason]
    if len(journal) >= MIN_FOR_PATTERN and len(unexplained) * 2 > len(journal):
        out.append(
            f"{len(unexplained)} of {len(journal)} trades have no written reason. Writing one "
            "down before buying is what makes this review useful."
        )
    if portfolio.account_value:
        for p in portfolio.positions:
            if p.value and p.value / portfolio.account_value > 0.4:
                out.append(
                    f"{p.symbol} is {p.value / portfolio.account_value:.0%} of your account. "
                    "One stock that large can move your whole result."
                )
    if n >= MIN_FOR_PATTERN and all(t.term == "short" for t in trades) and gross_profit > 0:
        out.append(
            "All your gains so far are short-term, taxed at 20%. Gains on shares held more "
            "than a year are taxed at 12.5%, with the first Rs 1.25 lakh a year exempt."
        )
    return out
