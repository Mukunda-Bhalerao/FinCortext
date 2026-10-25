"""Investor objectives and how each turns a covariance matrix and signals into weights.

Every objective is point-in-time computable: its weights depend only on trailing returns,
trailing dividends and caps, so a backtest can rebuild them on any past date. The research
overlay (agent composite scores) has no such history and is applied to current weights only.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.tools import portfolio as P


@dataclass(frozen=True)
class Objective:
    key: str
    label: str
    tagline: str
    method: str
    base: str  # "min_variance" | "risk_parity" | "equal_weight"
    tilt: str | None  # "momentum" | "yield"
    tilt_strength: float
    cap: Callable[[int], float]
    sector_cap: float


def _cap(floor: float, per: float) -> Callable[[int], float]:
    return lambda n: min(1.0, max(floor, per / n)) if n else 1.0


OBJECTIVES: dict[str, Objective] = {
    o.key: o
    for o in (
        Objective(
            "lower_risk",
            "Lower risk",
            "Smaller swings. Favours steadier stocks and stocks that offset each other.",
            "Lowest estimated volatility from a shrunk covariance matrix, within caps.",
            "min_variance",
            None,
            0.0,
            _cap(0.20, 1.2),
            0.35,
        ),
        Objective(
            "balanced",
            "Balanced growth",
            "Every stock carries an equal share of the risk, so no single name dominates.",
            "Equal risk contribution from a shrunk covariance matrix.",
            "risk_parity",
            None,
            0.0,
            _cap(0.25, 1.5),
            0.40,
        ),
        Objective(
            "growth",
            "Aggressive growth",
            "Leans into stocks with strong 12-month price trends and accepts bigger swings.",
            "Equal weight tilted by 12-1 month price momentum (relative to the other holdings).",
            "equal_weight",
            "momentum",
            0.8,
            _cap(0.35, 2.0),
            0.50,
        ),
        Objective(
            "income",
            "Dividend income",
            "Leans toward stocks that paid more dividends over the last year, with balanced risk.",
            "Equal risk contribution tilted by trailing 12-month dividend yield.",
            "risk_parity",
            "yield",
            0.8,
            _cap(0.25, 1.5),
            0.40,
        ),
    )
}
DEFAULT_OBJECTIVE = "balanced"
OVERLAY_STRENGTH = 0.5


def base_weights(base: str, S: P.Matrix, cap: float) -> list[float]:
    if base == "min_variance":
        return P.minimum_variance(S, cap)
    if base == "risk_parity":
        return P.risk_parity(S)
    return P.equal_weight(S)


def objective_weights(
    obj: Objective,
    S: P.Matrix,
    sectors: Sequence[str],
    signals: Sequence[float] | None = None,
    overlay: Sequence[float | None] | None = None,
    max_weight: float | None = None,
) -> tuple[list[float], bool, str | None]:
    """Weights for ``obj``. ``signals`` are cross-sectional scores in [-1, 1] for the tilt;
    ``overlay`` are research composite x confidence (None leaves a weight unchanged).
    Returns (weights, caps met, note)."""
    n = len(S)
    if n == 0:
        return [], True, None
    cap = max_weight if max_weight is not None else obj.cap(n)
    cap = max(cap, 1.0 / n)
    w = base_weights(obj.base, S, cap)
    if obj.tilt and signals is not None:
        w = P.score_tilt(w, list(signals), obj.tilt_strength)
    if overlay is not None and any(x is not None for x in overlay):
        w = P.score_tilt(w, list(overlay), OVERLAY_STRENGTH)
    distinct = len(set(sectors))
    groups = list(sectors) if distinct >= 3 else None
    w, ok = P.apply_caps(w, cap, groups, obj.sector_cap if groups else 1.0)
    note = None
    if not ok:
        note = "The caps cannot all hold with these stocks; the closest weights are shown."
    elif groups is None and n > 1:
        note = f"Sector cap not applied: the stocks span {distinct} sector(s)."
    return w, ok, note
