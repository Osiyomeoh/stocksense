"""Forecaster: when will each clinic's road close?

Uses only river readings up to as_of. Days to each road's threshold are
estimated at the fastest daily rise of the last 7 days, not the average
trend: the 2022 surge outran both (eval/backtest_forecaster.py). Even so the
date runs late, so it is a warning only; the Critic never relies on it.
Confidence is the R² of the 7-day trend: how steady the rise is.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from app.data import Clinic

TREND_DAYS = 7


@dataclass(frozen=True)
class RoadForecast:
    clinic_id: str
    closes_in_days: float | None  # None = not forecast to close within the horizon
    confidence: float | None
    river_m3s: float
    slope_m3s_per_day: float
    reason: str


def _trend(values: list[float]) -> tuple[float, float]:
    """(slope per day, R²) of a least-squares line through values."""
    n = len(values)
    if n < 2:
        return 0.0, 0.0
    xs = range(n)
    mx, my = (n - 1) / 2, sum(values) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    syy = sum((y - my) ** 2 for y in values)
    slope = sxy / sxx
    r2 = 1.0 if syy == 0 else (sxy * sxy) / (sxx * syy)
    return slope, r2


def forecast(clinics: list[Clinic], river: list[tuple[str, float]], horizon_days: int) -> dict[str, RoadForecast]:
    if not river:
        raise ValueError("no river readings up to as_of")
    recent = [q for _, q in river[-TREND_DAYS:]]
    now = recent[-1]
    _, r2 = _trend(recent)
    slope = max((b - a for a, b in zip(recent, recent[1:])), default=0.0)
    out = {}
    for c in clinics:
        thr = c.closes_above_m3s
        if thr is None:
            f = (None, None, "road not flood-prone")
        elif now >= thr:
            f = (0.0, 1.0, f"river {now:.0f} is already above {thr:.0f}")
        elif slope <= 0:
            f = (None, round(r2, 2), f"river {now:.0f} not rising; closes above {thr:.0f}")
        else:
            days = (thr - now) / slope
            if days > horizon_days:
                f = (None, round(r2, 2), f"at up to +{slope:.0f}/day, {thr:.0f} is {days:.0f} days away (beyond {horizon_days})")
            else:
                f = (round(days, 1), round(r2, 2), f"at up to +{slope:.0f}/day, could reach {thr:.0f} in {days:.1f} days")
        out[c.clinic_id] = RoadForecast(c.clinic_id, f[0], f[1], now, round(slope, 2), f[2])
    return out


def hold(roads: dict[str, RoadForecast], warnings: dict[str, dict], as_of: str, horizon_days: int) -> dict[str, RoadForecast]:
    """Keep an earlier warning on while it is fresh and the river hasn't fallen.

    The fastest-rise slope dips for a day or two inside a surge, which turned
    a road's warning off and on again (eval/backtest_forecaster.py). A warning
    {"since", "days", "river"} from at most horizon_days before as_of stays on,
    counting down from its own estimate, unless the river is now below the
    reading that raised it. Warnings dated after as_of are ignored.
    """
    out = dict(roads)
    for cid, w in warnings.items():
        r = roads.get(cid)
        if r is None or r.closes_in_days is not None:
            continue
        age = (date.fromisoformat(as_of) - date.fromisoformat(w["since"])).days
        if 0 < age <= horizon_days and r.river_m3s >= w["river"]:
            out[cid] = replace(r, closes_in_days=round(max(0.0, w["days"] - age), 1),
                               reason=f"warning from {w['since']} held: river {r.river_m3s:.0f} has not fallen below {w['river']:.0f}")
    return out
