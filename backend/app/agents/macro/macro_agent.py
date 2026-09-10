"""Macro Analyst — deterministic Indian-macro environment view.

Market-wide by design: the computation never touches a company symbol. The
optional `symbol` argument exists only so the standard
`/api/agents/macro/{symbol}/run` route stays uniform — it is validated by the
caller, recorded in provenance as `requested_symbol`, and otherwise ignored.
The emitted entity is always MACRO_INDIA.

Output contract is MacroOutput (NOT AgentOutput): the environment vocabulary
POSITIVE / NEUTRAL / NEGATIVE must never be mistaken for buy/sell stock
signals. The 0–100 Macro Environment Score rescales the available-factor vote
and always agrees with the overall signal; it is still an environment gauge,
never a company score to blend.
See methodology.py for the documented rules.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.agents.macro import methodology as M
from app.data.macro.indicators import MIN_MARKET_POINTS, get_indicator
from app.data.universe.universe_config import get_universe_entry
from app.domain.models.macro import (
    MacroDirection,
    MacroEvidence,
    MacroFactorOutput,
    MacroOutput,
    MacroSignal,
)
from app.repositories.macro_repository import MacroRepository

MACRO_ENTITY = "MACRO_INDIA"

# Area order for the seven mandated dimensions.
FACTOR_ORDER = (
    "growth",
    "inflation",
    "interest_rates",
    "liquidity_credit",
    "policy",
    "global",
    "events",
)

GLOBAL_GAUGES = ("usd_inr", "brent_crude", "us10y", "india_vix")

# Stance wording → tilt. The MPC's own vocabulary; unknown wordings stay
# neutral rather than guessed.
_EASING_WORDS = ("accommodat", "easing", "dovish")
_TIGHTENING_WORDS = ("tight", "withdraw", "hawk", "restrict")


class MacroAgent:
    """Deterministic macro environment analysis over stored observations."""

    agent_id = "macro_analyst"

    def __init__(self, macro_repo: MacroRepository):
        # The macro repository stores both observations and outputs.
        self.macro_repo = macro_repo

    # ------------------------------------------------------------------

    def analyze(self, symbol: str | None = None) -> MacroOutput:
        requested = None
        if symbol is not None:
            requested = get_universe_entry(symbol).symbol
        computations = [
            self._growth(),
            self._inflation(),
            self._interest_rates(),
            self._liquidity_credit(),
            self._policy(),
            self._global(),
            self._events(),
        ]
        available = [c for c in computations if c.available]

        votes = [
            1 if c.signal == MacroSignal.POSITIVE else -1
            if c.signal == MacroSignal.NEGATIVE else 0
            for c in available
        ]
        # The score rescales the available-factor vote, so signal and score
        # agree by construction; unavailable areas are excluded, not neutral.
        score = M.macro_score(votes)
        overall_signal = (
            MacroSignal(M.signal_from_macro_score(score))
            if score is not None
            else MacroSignal.UNAVAILABLE
        )

        coverage = len(available) / len(computations)
        fresh = sum(1 for c in available if c.confidence >= 0.6)
        recency = (fresh / len(available)) if available else 0.0
        consistency = 1.0 - M.population_std([float(v) for v in votes]) if votes else 0.0
        confidence = M.combine_confidence(coverage, recency, consistency) if available else 0.0

        if not available:
            status = "UNAVAILABLE"
        elif len(available) < M.MIN_FACTORS_OK:
            status = "DEGRADED"
        else:
            status = "OK"

        limitations: list[str] = []
        for c in computations:
            limitations.extend(c.limitations)

        data_through = {
            c.name: c.data_as_of for c in available if c.data_as_of is not None
        }
        rationale = self._build_rationale(overall_signal, available)

        removed = self._dedupe_evidence(computations)

        return MacroOutput(
            requested_symbol=requested,
            score=score,
            overall_signal=overall_signal,
            confidence=confidence,
            status=status,
            factors=computations,
            rationale=rationale,
            data_limitations=limitations,
            data_through=data_through,
            provenance={
                "methodology": "macro_analyst_v1",
                "factors_available": len(available),
                "factors_total": len(computations),
                "requested_symbol": requested,
                "evidence_duplicates_removed": removed,
            },
        )

    def run(self, symbol: str | None = None, *, persist: bool = True) -> MacroOutput:
        """Analyze and (optionally) persist the output."""
        output = self.analyze(symbol)
        if persist:
            self.macro_repo.save_output(output)
        return output

    # -- series helpers -----------------------------------------------------

    def _points(self, indicator_id: str):
        """Stored (period_end, value, obs) triples, oldest first, dated only."""
        series = self.macro_repo.get_series(indicator_id)
        pts = [
            (o.period_end or o.observed_at, o.value, o)
            for o in series
            if (o.period_end or o.observed_at) is not None
        ]
        pts.sort(key=lambda t: t[0])
        return pts

    def _fresh(self, indicator_id: str) -> bool:
        meta = get_indicator(indicator_id)
        latest = self.macro_repo.latest(indicator_id)
        if latest is None:
            return False
        day = latest.period_end or latest.observed_at
        return M.is_fresh(day, meta.get("freshness_days", 30))

    @staticmethod
    def _sources(pts) -> str:
        names = sorted({p[2].source_name for p in pts if p[2].source_name})
        return "; ".join(names) if names else "no stored observations"

    # -- factors ---------------------------------------------------------------

    def _growth(self) -> MacroFactorOutput:
        pts = self._points("gdp_real_yoy")
        base = "Growth — real GDP YoY."
        if not pts:
            return self._missing(
                "growth", "Real GDP growth",
                "No stored GDP observations — cannot assess growth.",
            )
        value = pts[-1][1]
        as_of = pts[-1][0].isoformat()
        full = len(pts) >= M.TREND_WINDOW_Q
        slope = M.slope_sign([p[1] for p in pts[-M.TREND_WINDOW_Q:]])
        direction = (
            MacroDirection.UP if slope > 0
            else MacroDirection.DOWN if slope < 0
            else MacroDirection.FLAT if len(pts) >= 2
            else MacroDirection.UNKNOWN
        )
        if value >= M.POTENTIAL_GDP:
            signal = MacroSignal.POSITIVE
        elif value >= 6.0:
            signal = MacroSignal.NEUTRAL
        else:
            signal = MacroSignal.NEGATIVE
        bases = sorted({(p[2].notes or "") for p in pts[-M.TREND_WINDOW_Q:] if p[2].notes})
        limitations = []
        if not full:
            limitations.append(
                f"Only {len(pts)} quarterly observations stored — trend uses all available."
            )
        detail = (
            f"Latest real GDP growth {value:.1f}% ({pts[-1][0].isoformat()}); "
            f"5-quarter slope is {direction.value}; benchmark: potential ~{M.POTENTIAL_GDP:.0f}%."
        )
        evidence = [
            MacroEvidence(
                indicator_id="gdp_real_yoy",
                reference=f"gdp_real_yoy@{p[0].isoformat()}",
                value=round(p[1], 2),
                unit="%",
                period=p[0].isoformat(),
                source_name=p[2].source_name,
                source_url=p[2].source_url,
                note=f"Real GDP YoY {p[1]:.1f}%"
                + (f" ({p[2].notes})" if p[2].notes else ""),
            )
            for p in pts[-3:]
        ]
        return MacroFactorOutput(
            name="growth", label="Growth", value=round(value, 2), unit="%",
            direction=direction, signal=signal,
            confidence=M.factor_confidence(full, self._fresh("gdp_real_yoy")),
            available=True, data_as_of=as_of, detail=detail,
            evidence=evidence, limitations=limitations,
        )

    def _inflation(self) -> MacroFactorOutput:
        pts = self._points("cpi_yoy")
        if not pts:
            return self._missing(
                "inflation", "CPI inflation",
                "No stored CPI observations — cannot assess inflation.",
            )
        value = pts[-1][1]
        as_of = pts[-1][0].isoformat()
        full = len(pts) >= M.CPI_CHANGE_LAG + 1
        prev = pts[-(M.CPI_CHANGE_LAG + 1)][1] if full else None
        direction = (
            MacroDirection.UP if prev is not None and value > prev
            else MacroDirection.DOWN if prev is not None and value < prev
            else MacroDirection.UNKNOWN if prev is None
            else MacroDirection.FLAT
        )
        lo, hi = M.CPI_TARGET - M.CPI_TOLERANCE, M.CPI_TARGET + M.CPI_TOLERANCE
        if value < lo:
            signal, why = MacroSignal.NEUTRAL, "below RBI tolerance: demand watch"
        elif value <= M.CPI_TARGET:
            signal, why = MacroSignal.POSITIVE, "within target, at/near 4%"
        elif value <= hi:
            signal, why = MacroSignal.NEUTRAL, "above target but inside tolerance"
        else:
            signal, why = MacroSignal.NEGATIVE, "above RBI tolerance band"
        limitations = []
        if prev is None:
            limitations.append("Fewer than 4 monthly observations — direction unknown.")
        detail = (
            f"Latest CPI {value:.2f}% ({as_of}) vs RBI target {M.CPI_TARGET:.0f}% "
            f"±{M.CPI_TOLERANCE:.0f}pp — {why}."
        )
        evidence = [
            MacroEvidence(
                indicator_id="cpi_yoy",
                reference=f"cpi_yoy@{p[0].isoformat()}",
                value=round(p[1], 2), unit="%", period=p[0].isoformat(),
                source_name=p[2].source_name, source_url=p[2].source_url,
                note=f"CPI YoY {p[1]:.2f}%",
            )
            for p in pts[-3:]
        ]
        return MacroFactorOutput(
            name="inflation", label="Inflation", value=round(value, 2), unit="%",
            direction=direction, signal=signal,
            confidence=M.factor_confidence(full, self._fresh("cpi_yoy")),
            available=True, data_as_of=as_of, detail=detail,
            evidence=evidence, limitations=limitations,
        )

    def _repo_points(self):
        return self._points("repo_rate")

    @staticmethod
    def _stance_of(obs) -> str | None:
        notes = obs.notes or ""
        for part in notes.split(";"):
            part = part.strip()
            if part.lower().startswith("stance="):
                return part.split("=", 1)[1].strip() or None
        return None

    def _interest_rates(self) -> MacroFactorOutput:
        pts = self._repo_points()
        if not pts:
            return self._missing(
                "interest_rates", "Interest Rates",
                "No stored repo-rate observations — cannot assess rates.",
            )
        value = pts[-1][1]
        as_of = pts[-1][0].isoformat()
        stance = self._stance_of(pts[-1][2])
        if len(pts) >= 2:
            move = value - pts[-2][1]
            direction = (
                MacroDirection.DOWN if move <= -M.RATE_MOVE_PP
                else MacroDirection.UP if move >= M.RATE_MOVE_PP
                else MacroDirection.FLAT
            )
        else:
            move, direction = None, MacroDirection.UNKNOWN
        if move is not None and move <= -M.RATE_MOVE_PP:
            signal = MacroSignal.POSITIVE
        elif move is not None and move >= M.RATE_MOVE_PP:
            signal = MacroSignal.NEGATIVE
        else:
            signal = MacroSignal.NEUTRAL
        detail = (
            f"Repo rate {value:.2f}% since {as_of}"
            + (f" (stance: {stance})" if stance else "")
            + (
                f"; last move {move:+.2f}pp on {as_of}."
                if move is not None
                else "; single observation — direction unknown."
            )
        )
        # Evidence ownership: this factor cites only the current level —
        # decision history belongs to the policy/events factors, so the same
        # repo observation is not repeated across the output.
        latest = pts[-1]
        evidence = [
            MacroEvidence(
                indicator_id="repo_rate",
                reference=f"repo_rate@{latest[0].isoformat()}",
                value=round(latest[1], 2), unit="%",
                period=latest[0].isoformat(),
                source_name=latest[2].source_name, source_url=latest[2].source_url,
                note=f"Repo {latest[1]:.2f}%"
                + (f", stance {self._stance_of(latest[2])}" if self._stance_of(latest[2]) else ""),
            )
        ]
        return MacroFactorOutput(
            name="interest_rates", label="Interest Rates",
            value=round(value, 2), unit="%",
            direction=direction, signal=signal,
            confidence=M.factor_confidence(len(pts) >= 2, self._fresh("repo_rate")),
            available=True, data_as_of=as_of, detail=detail,
            evidence=evidence, limitations=[],
        )

    def _liquidity_credit(self) -> MacroFactorOutput:
        return self._missing(
            "liquidity_credit", "Liquidity & Credit",
            "No reliable liquidity/credit series is configured. None is proxied: "
            "a volatility gauge measures risk appetite, not funding conditions.",
        )

    def _policy(self) -> MacroFactorOutput:
        pts = self._repo_points()
        if not pts:
            return self._missing(
                "policy", "Fiscal & Monetary Policy",
                "No stored repo-rate decisions — no policy facts to report.",
                extra_limitations=[
                    "Fiscal developments are not covered: no fiscal-events source is configured."
                ],
            )
        cutoff = date.today() - timedelta(days=365)
        window = [p for p in pts if p[0] >= cutoff]
        changes = [
            (cur[0], cur[1] - prev[1])
            for prev, cur in zip(window, window[1:])
            if abs(cur[1] - prev[1]) >= 0.005
        ]
        base_level = window[0][1] if window else pts[-1][1]
        net = pts[-1][1] - base_level
        stance = self._stance_of(pts[-1][2])
        tilt = _stance_tilt(stance)
        if net <= -M.POLICY_NET_PP or tilt > 0:
            signal = MacroSignal.POSITIVE
        elif net >= M.POLICY_NET_PP or tilt < 0:
            signal = MacroSignal.NEGATIVE
        else:
            signal = MacroSignal.NEUTRAL
        facts = (
            "; ".join(f"{d.isoformat()}: {delta:+.2f}pp" for d, delta in changes)
            or "no repo-rate changes in the trailing 12 months"
        )
        detail = (
            f"FACTS — trailing-12M repo decisions: {facts}; "
            f"net {net:+.2f}pp; stance: {stance or 'unstated'}. "
            f"INTERPRETATION: "
            + (
                "net easing with a dovish tilt reads as supportive."
                if signal == MacroSignal.POSITIVE else
                "net tightening reads as restrictive."
                if signal == MacroSignal.NEGATIVE else
                "no directional tilt either way."
            )
        )
        # Evidence ownership: only the decisions that actually changed the
        # rate (or the latest level, explicitly noted as unchanged) — the
        # full dated decision list belongs to the events factor.
        if changes:
            change_points = [
                p for p in pts
                if p[0] in {d for d, _ in changes}
            ]
            change_note = "MPC decision"
        else:
            change_points = [pts[-1]]
            change_note = "unchanged for 12M"
        evidence = [
            MacroEvidence(
                indicator_id="repo_rate",
                reference=f"repo_rate@{p[0].isoformat()}",
                value=round(p[1], 2), unit="%",
                period=p[0].isoformat(),
                source_name=p[2].source_name, source_url=p[2].source_url,
                note=f"{change_note}: repo {p[1]:.2f}%"
                + (f", stance {self._stance_of(p[2])}" if self._stance_of(p[2]) else ""),
            )
            for p in change_points
        ]
        return MacroFactorOutput(
            name="policy", label="Fiscal & Monetary Policy",
            value=round(net, 2), unit="pp (12M net change)",
            direction=(
                MacroDirection.DOWN if net < 0 else MacroDirection.UP if net > 0
                else MacroDirection.FLAT
            ),
            signal=signal,
            confidence=M.factor_confidence(True, self._fresh("repo_rate")),
            available=True, data_as_of=pts[-1][0].isoformat(), detail=detail,
            evidence=evidence,
            limitations=[
                "Fiscal developments are not covered: no fiscal-events source "
                "is configured, and none is inferred."
            ],
        )

    def _global(self) -> MacroFactorOutput:
        sub: list[tuple[str, int, str]] = []  # (indicator, vote, detail)
        evidence: list[MacroEvidence] = []
        limitations: list[str] = []
        latest_dates: list = []
        for indicator_id in GLOBAL_GAUGES:
            pts = self._points(indicator_id)
            meta = get_indicator(indicator_id)
            if len(pts) < MIN_MARKET_POINTS:
                limitations.append(
                    f"{meta['label']}: only {len(pts)} stored sessions "
                    f"(need {MIN_MARKET_POINTS}) — gauge skipped, not guessed."
                )
                continue
            window = pts[-M.MARKET_TREND_SESSIONS - 1:]
            first, last = window[0][1], window[-1][1]
            chg = (last / first - 1) if first else 0.0
            if indicator_id == "us10y":
                # Yields are judged in absolute basis points, not relative
                # percent (a 10.0→10.5 move is huge in bps, tiny in percent).
                material = abs(last - first) * 100 >= M.US10Y_ABS_BPS
            else:
                material = abs(chg) > M.MATERIALITY_PCT[indicator_id]
            favorable_up = M.GAUGE_UP_FAVORABLE[indicator_id]
            if not material:
                vote = 0
            else:
                vote = 1 if (chg > 0) == favorable_up else -1
            latest_dates.append(window[-1][0])
            sub.append((indicator_id, vote,
                        f"{meta['label']}: {last:,.2f} ({chg:+.1%} over ~3M) → "
                        + ("supportive" if vote > 0 else "adverse" if vote < 0 else "muted")))
            evidence.append(
                MacroEvidence(
                    indicator_id=indicator_id,
                    reference=f"{indicator_id}@{window[-1][0].isoformat()}",
                    value=round(last, 2), unit=meta["unit"],
                    period=window[-1][0].isoformat(),
                    source_name=window[-1][2].source_name,
                    source_url=None,
                    note=f"{meta['label']} {last:,.2f} ({chg:+.1%} over ~3M)",
                )
            )
        if not sub:
            return self._missing(
                "global", "Global Markets",
                "No global gauge has enough stored history — nothing scored.",
            )
        net = sum(v for _, v, _ in sub)
        signal = (
            MacroSignal.POSITIVE if net > 0
            else MacroSignal.NEGATIVE if net < 0
            else MacroSignal.NEUTRAL
        )
        direction = (
            MacroDirection.UP if net > 0
            else MacroDirection.DOWN if net < 0
            else MacroDirection.FLAT
        )
        as_of = max(latest_dates).isoformat() if latest_dates else None
        # A gauge is fresh when its own series is fresh; factor freshness =
        # majority of voting gauges fresh.
        return MacroFactorOutput(
            name="global", label="Global Markets", value=net,
            unit="net votes (-4..4)",
            direction=direction, signal=signal,
            confidence=M.factor_confidence(len(sub) == len(GLOBAL_GAUGES), as_of is not None),
            available=True, data_as_of=as_of,
            detail="; ".join(d for _, _, d in sub),
            evidence=evidence, limitations=limitations,
        )

    def _events(self) -> MacroFactorOutput:
        events: list[tuple[str, str, str]] = []  # (date, label, source)
        for p in self._repo_points()[-5:]:
            stance = self._stance_of(p[2])
            events.append((
                p[0].isoformat(), f"RBI repo {p[1]:.2f}%"
                + (f" (stance: {stance})" if stance else ""),
                p[2].source_name or "RBI MPC statements (curated)",
            ))
        for indicator_id, kind in (("cpi_yoy", "CPI"), ("gdp_real_yoy", "GDP")):
            for p in self._points(indicator_id)[-2:]:
                events.append((
                    p[0].isoformat(), f"{kind} {p[1]:.2f}%",
                    p[2].source_name or "MoSPI releases (curated)",
                ))
        if not events:
            return self._missing(
                "events", "Macro Events",
                "No dated macro events in storage — nothing to list.",
            )
        events.sort(reverse=True)
        lines = [f"{d}: {label} [{src}]" for d, label, src in events[:8]]
        return MacroFactorOutput(
            name="events", label="Macro Events", value=len(lines),
            unit="recent events listed",
            direction=MacroDirection.FLAT, signal=MacroSignal.NEUTRAL,
            confidence=M.factor_confidence(True, True),
            available=True, data_as_of=events[0][0],
            detail="Recent dated developments detected in retrieved data: "
            + " | ".join(lines),
            evidence=[
                MacroEvidence(
                    indicator_id="events", reference=f"event@{d}",
                    value=None, unit=None, period=d,
                    source_name=src, source_url=None, note=label,
                )
                for d, label, src in events[:8]
            ],
            limitations=[
                "Upcoming events (calendars, scheduled releases) have no source "
                "configured and are not listed — only retrieved history is shown."
            ],
        )

    # -- assembly ---------------------------------------------------------------

    @staticmethod
    def _dedupe_evidence(computations) -> int:
        """Drop repeated observations across factor evidence lists.

        The same stored observation (e.g. a repo-rate decision cited by both
        the rates and the events factors) is cited once — by the earliest
        factor in area order — so duplicates can neither clutter the view nor
        suggest more independent evidence than exists. Returns the count
        removed. Factor detail text is untouched: it already names every
        relevant observation explicitly.
        """
        seen: set[tuple[str, str]] = set()
        removed = 0
        for computation in computations:
            kept = []
            for item in computation.evidence:
                key = (item.indicator_id, item.reference)
                if key in seen:
                    removed += 1
                    continue
                seen.add(key)
                kept.append(item)
            computation.evidence = kept
        return removed

    @staticmethod
    def _missing(name: str, label: str, limitation: str,
                 extra_limitations: list[str] | None = None) -> MacroFactorOutput:
        return MacroFactorOutput(
            name=name, label=label, value=None, unit=None,
            direction=MacroDirection.UNKNOWN, signal=MacroSignal.UNAVAILABLE,
            confidence=0.0, available=False, data_as_of=None, detail=None,
            evidence=[], limitations=[limitation, *(extra_limitations or [])],
        )

    @staticmethod
    def _build_rationale(overall: MacroSignal, available) -> str:
        if not available:
            return (
                "Macro environment unavailable: no macro indicator has enough "
                "stored history. Refresh macro data first — nothing is inferred."
            )
        by_signal: dict[str, list[str]] = {}
        for c in available:
            by_signal.setdefault(c.signal.value, []).append(c.label)
        parts = "; ".join(
            f"{label}s: {', '.join(sorted(names))}"
            for label, names in sorted(by_signal.items())
        )
        interpretation = (
            "Interpretation: "
            + (
                "the weight of available evidence leans supportive for Indian equities."
                if overall == MacroSignal.POSITIVE else
                "the weight of available evidence leans adverse for Indian equities."
                if overall == MacroSignal.NEGATIVE else
                "available evidence pulls in both directions or is too thin to lean either way."
            )
        )
        return (
            f"Macro Environment Signal is {overall.value.upper()} from "
            f"{len(available)}/7 areas ({parts}). {interpretation}"
        )


def _stance_tilt(stance: str | None) -> int:
    """+1 easing tilt, −1 tightening tilt, 0 neutral/unknown — from the MPC's
    own stance vocabulary, never guessed from values."""
    text = (stance or "").lower()
    if any(w in text for w in ("accommodat", "easing", "dovish")):
        return 1
    if any(w in text for w in ("tight", "withdraw", "hawk", "restrict")):
        return -1
    return 0
