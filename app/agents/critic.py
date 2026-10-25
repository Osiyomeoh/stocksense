"""Critic: checks a draft plan against the LGA's rules (docs/SCENARIO.md).

Each violation carries the constraint that would fix it, which the
orchestrator hands back to the Planner for a retry.
"""

from __future__ import annotations

from app.agents.forecaster import RoadForecast
from app.agents.planner import Plan
from app.data import Clinic


def review(plan: Plan, clinics: list[Clinic], roads: dict[str, RoadForecast], cfg: dict) -> list[dict]:
    by_id = {c.clinic_id: c for c in clinics}
    violations = []

    after = {c.clinic_id: c.stock for c in clinics if c.stock is not None}
    for l in plan.lines:
        after[l.to] += l.qty
        if l.kind == "transfer":
            after[l.source] -= l.qty

    for cid, stock in after.items():
        c = by_id[cid]
        floor = cfg["safety_stock_days"] * c.daily_use
        donated = any(l.kind == "transfer" and l.source == cid for l in plan.lines)
        if donated and stock < floor:
            violations.append({"rule": "donor_safety", "clinic": cid,
                               "reason": f"{cid} would drop to {stock}, below {floor:.0f} ({cfg['safety_stock_days']} days)"})
        received = any(l.to == cid for l in plan.lines)
        if received and stock > c.capacity:
            violations.append({"rule": "capacity", "clinic": cid,
                               "reason": f"{cid} would hold {stock}, over its capacity {c.capacity}"})

    for l in plan.lines:
        closes = roads[l.to].closes_in_days
        if closes is not None and l.deliver_day >= closes:
            violations.append({"rule": "road_open_on_delivery", "clinic": l.to,
                               "reason": f"{l.source}→{l.to} arrives day {l.deliver_day}, road forecast to close in {closes} days",
                               "fix": {"no_purchase_to": [l.to]} if l.kind == "purchase" else None})

    if plan.cost > cfg["budget_per_quarter"]:
        violations.append({"rule": "budget", "reason": f"₦{plan.cost:,} is over the ₦{cfg['budget_per_quarter']:,} budget"})
    return violations
