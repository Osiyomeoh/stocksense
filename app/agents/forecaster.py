"""Forecaster: when will each clinic's road close?

Uses only river readings up to as_of: a least-squares trend over the last
7 days, extrapolated to each road's closure threshold. Confidence is the
trend's R² (1.0 when the river is already above the threshold).
"""

from __future__ import annotations

from dataclasses import dataclass

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
    slope, r2 = _trend(recent)
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
                f = (None, round(r2, 2), f"at +{slope:.0f}/day, {thr:.0f} is {days:.0f} days away (beyond {horizon_days})")
            else:
                f = (round(days, 1), round(r2, 2), f"at +{slope:.0f}/day, reaches {thr:.0f} in {days:.1f} days")
        out[c.clinic_id] = RoadForecast(c.clinic_id, f[0], f[1], now, round(slope, 2), f[2])
    return out
