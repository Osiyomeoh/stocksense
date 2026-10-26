"""Planner: transfers first, then one purchase order, as plain arithmetic.

It sizes needs and surpluses and picks the cheapest route. Safety, capacity,
budget and road-open checks belong to the Critic; the Planner only obeys the
constraints the Critic hands back on a retry:

  no_purchase_to: clinics a purchase cannot reach in time; they may then
                  draw donors down to safety stock instead of safety + resupply
  unreachable:    clinics whose road is already shut; nothing is planned to them
  avoid_suppliers: suppliers memory or the user ruled out
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.agents.forecaster import RoadForecast
from app.data import Clinic


@dataclass
class Line:
    kind: str  # "transfer" | "purchase"
    to: str
    qty: int
    cost: int
    deliver_day: int
    source: str  # donor clinic or supplier id
    why: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Plan:
    lines: list[Line] = field(default_factory=list)
    order: dict[str, Any] | None = None  # the purchase order, if any
    unmet: dict[str, int] = field(default_factory=dict)  # clinic -> courses not covered
    holds: list[dict[str, str]] = field(default_factory=list)

    @property
    def cost(self) -> int:
        transfer = sum(l.cost for l in self.lines if l.kind == "transfer")
        return transfer + (self.order["cost"] if self.order else 0)


def target_days(road: RoadForecast, cfg: dict) -> int:
    return cfg["road_risk_target_days"] if road.closes_in_days is not None else cfg["safety_stock_days"]


def plan(clinics: list[Clinic], roads: dict[str, RoadForecast], cfg: dict, constraints: dict | None = None) -> Plan:
    constraints = constraints or {}
    no_purchase = set(constraints.get("no_purchase_to", []))
    avoid = set(constraints.get("avoid_suppliers", []))
    unreachable = set(constraints.get("unreachable", []))
    out = Plan()

    known = [c for c in clinics if c.stock is not None]
    for c in clinics:
        if c.stock is None:
            out.holds.append({"clinic": c.clinic_id, "reason": c.problem or "no stock reading for this snapshot; ask the clinic before planning"})

    need = {}
    for c in known:
        want = min(c.capacity, math.ceil(target_days(roads[c.clinic_id], cfg) * c.daily_use))
        if want > c.stock:
            if c.clinic_id in unreachable:
                out.unmet[c.clinic_id] = want - c.stock
            else:
                need[c.clinic_id] = want - c.stock

    by_id = {c.clinic_id: c for c in known}
    keep_days = cfg["safety_stock_days"] + cfg["donor_keep_extra_days"]
    donors = [c for c in known if c.clinic_id not in need and c.clinic_id not in unreachable]
    spare = {c.clinic_id: max(0, c.stock - math.ceil(keep_days * c.daily_use)) for c in donors}
    # Only clinics a purchase can't reach may dig into donors' resupply buffer,
    # and never below safety stock.
    buffer = {c.clinic_id: max(0, c.stock - math.ceil(cfg["safety_stock_days"] * c.daily_use)) - spare[c.clinic_id]
              for c in donors}

    def urgency(cid: str):
        r = roads[cid]
        return (r.closes_in_days if r.closes_in_days is not None else math.inf, by_id[cid].days_of_stock)

    for cid in sorted(need, key=urgency):
        dest = by_id[cid]
        for donor in sorted(set(spare) | set(buffer), key=lambda d: abs(by_id[d].km_to_store - dest.km_to_store)):
            if need[cid] == 0:
                break
            avail = spare.get(donor, 0) + (buffer.get(donor, 0) if cid in no_purchase else 0)
            qty = min(avail, need[cid])
            if qty <= 0:
                continue
            from_spare = min(qty, spare.get(donor, 0))
            spare[donor] = spare.get(donor, 0) - from_spare
            buffer[donor] = buffer.get(donor, 0) - (qty - from_spare)
            need[cid] -= qty
            km = by_id[donor].km_to_store + dest.km_to_store
            out.lines.append(Line("transfer", cid, qty, round(km * cfg["transfer_cost_per_km"]),
                                  cfg["transfer_delivery_days"], donor,
                                  f"{donor} has {qty} above its keep level; {km:g} km via the LGA store"))

    gap = {cid: n for cid, n in need.items() if n > 0}
    blocked = {cid: n for cid, n in gap.items() if cid in no_purchase}
    out.unmet.update(blocked)
    gap = {cid: n for cid, n in gap.items() if cid not in no_purchase}
    # A purchase can't reach a blocked clinic in time, but it can reach the LGA
    # store (always open), so the next run can send it on by next-day transfer.
    staged = {cid: n for cid, n in blocked.items() if cid not in unreachable}
    if gap or staged:
        options = [(sid, s) for sid, s in cfg["suppliers"].items() if s.get("available", True) and sid not in avoid]
        if not options:
            out.unmet.update(gap)
        else:
            total = sum(gap.values()) + sum(staged.values())
            # Cheapest whole order, not cheapest unit: a minimum order can outweigh the price.
            sid, s = min(options, key=lambda o: max(total, o[1]["min_order"]) * o[1]["price"])
            qty = max(total, s["min_order"])
            out.order = {"supplier": sid, "qty": qty, "cost": qty * s["price"], "lead_days": s["lead_days"],
                         "why": f"cheapest whole order: gap {total}, min order {s['min_order']} at ₦{s['price']}/course"}
            if staged:
                out.order["staged_at_store_for"] = staged
            for cid, n in sorted(gap.items(), key=lambda kv: urgency(kv[0])):
                out.lines.append(Line("purchase", cid, n, 0, s["lead_days"] + cfg["transfer_delivery_days"], sid,
                                      f"from the {sid} order, delivered via the LGA store"))
    return out
