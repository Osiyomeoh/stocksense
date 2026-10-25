"""Evaluator: re-queries Zetaris for every number a plan line rests on.

A line whose inputs can't be re-read, or no longer match, is put on HOLD
instead of being sent to the pharmacist. Nothing is guessed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app import data
from app.agents.planner import Plan
from app.data import Clinic


def verify(plan: Plan, clinics: list[Clinic], river_now: float, as_of: str, river_table: str = data.RIVER_TABLE) -> dict:
    used = {c.clinic_id: c for c in clinics}
    ids = sorted({l.to for l in plan.lines} | {l.source for l in plan.lines if l.kind == "transfer"})
    checks, failed = [], {}

    # Both re-reads go to Zetaris at once; each is checked on its own.
    with ThreadPoolExecutor(2) as pool:
        clinic_job = pool.submit(data.load_clinics, as_of, ids) if ids else None
        river_job = pool.submit(data.load_river_on, as_of, river_table)

    try:
        fresh = {c.clinic_id: c for c in clinic_job.result()} if clinic_job else {}
        for cid in ids:
            a, b = used[cid], fresh.get(cid)
            ok = b is not None and (a.stock, a.daily_use) == (b.stock, b.daily_use)
            checks.append({"check": f"{cid} stock and daily use", "ok": ok})
            if not ok:
                failed[cid] = "stock or daily use changed on re-query"
    except Exception as e:  # any failure to re-read is a reason to hold, not to guess
        for cid in ids:
            failed[cid] = f"clinic data could not be re-read: {e}"
        checks.append({"check": "clinic data", "ok": False, "error": str(e)})

    river_ok = True
    try:
        river_ok = river_job.result() == river_now
        checks.append({"check": "river discharge on as_of", "ok": river_ok})
    except Exception as e:
        river_ok = False
        checks.append({"check": "river discharge on as_of", "ok": False, "error": str(e)})

    verified, held = [], []
    for l in plan.lines:
        reason = failed.get(l.to) or (failed.get(l.source) if l.kind == "transfer" else None)
        if not reason and not river_ok and used[l.to].closes_above_m3s is not None:
            reason = "river source could not be re-verified, so this road's status is unknown"
        (held if reason else verified).append({**l.as_dict(), **({"hold_reason": reason} if reason else {})})
    return {"verified": verified, "held": held, "checks": checks}
