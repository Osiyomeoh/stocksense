"""Replay the whole 2022 rainy season and compare planning policies.

Every 7 days from 2022-07-04 to 2022-10-31 each policy plans from the
stock it would have on that day and the real GloFAS river up to that day.
Then the days are played out: clinics use medicine every day, and a
delivery reaches a clinic only on a day its road is open (the real river
is below the road's threshold); otherwise it waits. Stock, use, roads and
supplier lateness are SYNTHETIC (docs/SCENARIO.md); the river is real.

  python3 eval/season.py        # prints the table, writes eval/season_2022.json

Policies:
  naive          reorder every clinic to 4 weeks of stock from the cheapest
                 supplier; no transfers, no roads
  no_river       StockSense with the river join switched off (no forecast)
  no_critic      StockSense, Planner only: the Critic never rejects
  no_held        StockSense without held road warnings (H-MEM off)
  no_supplier_memory  StockSense, but late deliveries are never remembered
  stocksense     everything on
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("HMEM_DIR", tempfile.mkdtemp(prefix="hmem-season-"))

from app import config, data  # noqa: E402
from app.agents import critic, forecaster, memory_keeper, planner  # noqa: E402
from app.data import Clinic  # noqa: E402
from app.pipeline import MAX_RETRIES  # noqa: E402

import backtest_forecaster  # noqa: E402

START, END = date(2022, 7, 4), date(2022, 10, 31)
PLAN_EVERY = 7
OUT = HERE / "season_2022.json"

# Starting stock, use and roads: the recorded 2022-07-04 clinic_risk rows.
# P6 did not report that day; docs/SCENARIO.md gives it 60 courses.
ROWS = json.loads((config.SAMPLE_DIR / "zetaris" / "4a8de106818241d8.json").read_text())["response"]
START_STOCK = {"P6": 60}

# SYNTHETIC lateness, from docs/SCENARIO.md's supplier history: S3 is late
# by 3+ weeks on 75% of orders, S2 on 10%. Deterministic: S3's orders
# 1, 2, 3 of every 4 are 21 days late; S2's every 10th is 14 days late.
def late_days(sid: str, n: int) -> int:
    return {"S3": 21 if n % 4 != 0 else 0, "S2": 14 if n % 10 == 9 else 0}.get(sid, 0)


def clinics_from_rows() -> list[Clinic]:
    out = []
    for r in (dict(zip(ROWS["headers"], row)) for row in ROWS["data"]):
        if r["as_of"] != "2022-07-04":
            continue
        cfg = data.SCENARIO["clinics"][r["clinic_id"]]
        stock = START_STOCK.get(r["clinic_id"], r["stock_courses"])
        out.append(Clinic(r["clinic_id"], r["clinic_name"], r["as_of"], int(float(stock)), float(r["daily_use_rainy"]),
                          r["road_id"], r["road_surface"],
                          None if r["closes_above_m3s"] is None else float(r["closes_above_m3s"]),
                          cfg["capacity"], cfg["km_to_store"]))
    return out


def naive(clinics, river, cfg, state):
    gap = {c.clinic_id: max(0, math.ceil(cfg["safety_stock_days"] * c.daily_use) - c.stock) for c in clinics}
    total = sum(gap.values())
    if not total:
        return planner.Plan()
    options = [(sid, s) for sid, s in cfg["suppliers"].items() if s.get("available", True)]
    sid, s = min(options, key=lambda o: max(total, o[1]["min_order"]) * o[1]["price"])
    qty = max(total, s["min_order"])
    p = planner.Plan(order={"supplier": sid, "qty": qty, "cost": qty * s["price"], "lead_days": s["lead_days"]})
    p.lines = [planner.Line("purchase", cid, n, 0, s["lead_days"] + cfg["transfer_delivery_days"], sid, "")
               for cid, n in gap.items() if n]
    return p


def stocksense(river_on=True, critic_on=True, held_on=True, supplier_memory=True):
    def policy(clinics, river, cfg, state):
        today = river[-1][0]
        if river_on:
            roads = forecaster.forecast(clinics, river, cfg["forecast_horizon_days"])
            if held_on:
                roads = forecaster.hold(roads, state["warnings"], today, cfg["forecast_horizon_days"])
                for cid, r in roads.items():
                    if r.closes_in_days is not None and not r.reason.startswith("warning from"):
                        state["warnings"][cid] = {"since": today, "days": r.closes_in_days, "river": r.river_m3s}
        else:
            roads = {c.clinic_id: forecaster.RoadForecast(c.clinic_id, None, None, river[-1][1], 0.0, "river off")
                     for c in clinics}
        constraints = {}
        if supplier_memory:
            constraints["avoid_suppliers"] = memory_keeper.recall()["avoid"]
        for attempt in range(MAX_RETRIES + 1):
            draft = planner.plan(clinics, roads, cfg, constraints)
            if not critic_on:
                break
            violations = critic.review(draft, clinics, roads, cfg)
            fixes = [v["fix"] for v in violations if v.get("fix")]
            if not violations or not fixes:
                break
            for fix in fixes:
                for k, v in fix.items():
                    constraints[k] = sorted(set(constraints.get(k, [])) | set(v))
        return draft
    return policy


POLICIES = {
    "naive": (naive, False),
    "no_river": (stocksense(river_on=False), True),
    "no_critic": (stocksense(critic_on=False), True),
    "no_held": (stocksense(held_on=False), True),
    "no_supplier_memory": (stocksense(supplier_memory=False), False),
    "stocksense": (stocksense(), True),
}


def simulate(name: str, river_all: list[tuple[str, float]]) -> dict:
    policy, learns = POLICIES[name]
    config.HMEM_DIR = Path(tempfile.mkdtemp(prefix=f"hmem-{name}-"))
    cfg = data.SCENARIO
    base = clinics_from_rows()
    stock = {c.clinic_id: float(c.stock) for c in base}
    q = dict(river_all)
    closed = lambda cid, d: (lambda c: c.closes_above_m3s is not None and q[d.isoformat()] >= c.closes_above_m3s)(
        next(c for c in base if c.clinic_id == cid))
    pending: list[dict] = []  # {"to", "qty", "day", "promised", "supplier"}
    orders = {"S2": 0, "S3": 0}
    out = {"stockout_days": 0, "courses_short": 0, "spend": 0, "waited_for_road_days": 0,
           "late_supplier_deliveries": 0, "by_clinic": {c.clinic_id: 0 for c in base}, "suppliers": []}
    state = {"warnings": {}}
    d = START
    while d <= END:
        for p in [p for p in pending if p["day"] <= d]:
            if closed(p["to"], d):
                p["day"] = d + timedelta(days=1)
                out["waited_for_road_days"] += 1
                continue
            stock[p["to"]] += p["qty"]
            pending.remove(p)
            if p["supplier"] and p["promised"] < d and learns:
                memory_keeper.learn(f"{p['supplier']} was late")
        if (d - START).days % PLAN_EVERY == 0:
            clinics = [replace(c, stock=int(stock[c.clinic_id]), as_of=d.isoformat()) for c in base]
            river = [(t, v) for t, v in river_all if t <= d.isoformat()]
            draft = policy(clinics, river, cfg, state)
            late = 0
            if draft.order:
                sid = draft.order["supplier"]
                late = late_days(sid, orders[sid])
                orders[sid] += 1
                out["spend"] += draft.order["cost"]
                out["suppliers"].append(sid)
                out["late_supplier_deliveries"] += late > 0
                # Whatever the minimum order adds beyond the clinics' gaps stays in
                # the LGA store, which is at P1 (0 km), and can be transferred later.
                spare = draft.order["qty"] - sum(l.qty for l in draft.lines if l.kind == "purchase")
                if spare > 0:
                    draft.lines.append(planner.Line("purchase", "P1", spare, 0, draft.order["lead_days"], sid, ""))
            for l in draft.lines:
                if l.kind == "transfer":
                    stock[l.source] -= l.qty
                    out["spend"] += l.cost
                extra = late if l.kind == "purchase" else 0
                pending.append({"to": l.to, "qty": l.qty, "day": d + timedelta(days=l.deliver_day + extra),
                                "promised": d + timedelta(days=l.deliver_day),
                                "supplier": l.source if l.kind == "purchase" else None})
        for c in base:
            if stock[c.clinic_id] >= c.daily_use:
                stock[c.clinic_id] -= c.daily_use
            else:
                out["courses_short"] += c.daily_use - stock[c.clinic_id]
                stock[c.clinic_id] = 0.0
                out["stockout_days"] += 1
                out["by_clinic"][c.clinic_id] += 1
        d += timedelta(days=1)
    out["courses_short"] = round(out["courses_short"])
    return out


def main() -> int:
    river = backtest_forecaster.load()
    results = {name: simulate(name, river) for name in POLICIES}
    OUT.write_text(json.dumps({"window": [START.isoformat(), END.isoformat()], "plan_every_days": PLAN_EVERY,
                               "results": results}, indent=1) + "\n")
    days = (END - START).days + 1
    print(f"2022-07-04..2022-10-31 ({days} days, 8 clinics, planning every {PLAN_EVERY} days), real GloFAS river")
    print(f"{'policy':20} {'stockout clinic-days':>21} {'courses short':>14} {'spend ₦':>12} {'waited for road':>16}  worst clinics")
    for name, r in results.items():
        worst = ", ".join(f"{c} {n}" for c, n in sorted(r["by_clinic"].items(), key=lambda kv: -kv[1]) if n)[:40]
        print(f"{name:20} {r['stockout_days']:>21} {r['courses_short']:>14} {r['spend']:>12,} {r['waited_for_road_days']:>16}  {worst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
