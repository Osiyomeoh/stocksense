"""One planning run: Forecaster → Sentinels → Memory Keeper → Planner ⇄ Critic → Evaluator → Coordinator."""

from __future__ import annotations

from typing import Any

from app import data
from app.agents import coordinator, critic, evaluator, forecaster, memory_keeper, planner, sentinels
from app.adapters import hmem
from app.trace import Trace

MAX_RETRIES = 2


def run(as_of: str, trace: Trace, constraints: dict | None = None) -> dict[str, Any]:
    cfg = data.SCENARIO

    clinics = data.load_clinics(as_of)
    trace.log("DataAgent", "zetaris.clinic_risk", as_of, f"{len(clinics)} clinics", target_agent="Forecaster")
    river = data.load_river(as_of)
    trace.log("DataAgent", "zetaris.river", f"<= {as_of}", f"{len(river)} days, last {river[-1][1] if river else None}",
              target_agent="Forecaster")

    roads = forecaster.forecast(clinics, river, cfg["forecast_horizon_days"])
    for r in roads.values():
        trace.log("Forecaster", "road_forecast", r.clinic_id, r.reason, target_agent="Sentinel", confidence=r.confidence)

    flags = sentinels.run_all(clinics, roads, cfg["safety_stock_days"])
    for cid, f in flags.items():
        trace.log(f"Sentinel:{cid}", "flags", cid, ",".join(f) or "none", target_agent="Planner",
                  status="hold" if "missing_reading" in f else "ok")

    constraints = {k: list(v) for k, v in (constraints or {}).items()}
    try:
        memory = memory_keeper.recall()
    except hmem.HMemError as e:
        memory = {"avoid": [], "escalate": [], "memories": [], "error": str(e)}
        trace.log("MemoryKeeper", "hmem.recall", "supplier", f"skipped: {e}", target_agent="Planner", status="fallback")
    else:
        for m in memory["memories"]:
            applied = m["confidence"] >= memory_keeper.TRUST
            trace.log("MemoryKeeper", "hmem.recall", m["id"], f"{m['content']} (confidence {m['confidence']:.2f})",
                      target_agent="Planner" if applied else "Pharmacist", confidence=m["confidence"],
                      status="ok" if applied else "escalated")
    if memory["avoid"]:
        constraints["avoid_suppliers"] = sorted(set(constraints.get("avoid_suppliers", [])) | set(memory["avoid"]))
    for attempt in range(MAX_RETRIES + 1):
        draft = planner.plan(clinics, roads, cfg, constraints)
        trace.log("Planner", "draft", str(constraints), f"{len(draft.lines)} lines, ₦{draft.cost:,}",
                  target_agent="Critic", retry_count=attempt)
        violations = critic.review(draft, clinics, roads, cfg)
        fixes = [v["fix"] for v in violations if v.get("fix")]
        trace.log("Critic", "review", f"{len(draft.lines)} lines", "; ".join(v["reason"] for v in violations) or "ok",
                  target_agent="Planner" if violations else "Evaluator", retry_count=attempt,
                  status="rejected" if violations else "ok")
        if not violations or not fixes or attempt == MAX_RETRIES:
            break
        for fix in fixes:
            for k, v in fix.items():
                constraints[k] = sorted(set(constraints.get(k, [])) | set(v))

    result = evaluator.verify(draft, clinics, river[-1][1], as_of)
    trace.log("Evaluator", "re-query", f"{len(draft.lines)} lines",
              f"{len(result['verified'])} verified, {len(result['held'])} held", target_agent="Coordinator",
              status="hold" if result["held"] else "ok")

    out = {
        "status": "needs_review" if violations or result["held"] or draft.holds or draft.unmet else "ok",
        "roads": {cid: r.__dict__ for cid, r in roads.items()},
        "flags": flags,
        "plan": result["verified"],
        "held": result["held"] + draft.holds,
        "purchase_order": draft.order,
        "unmet": draft.unmet,
        "violations": violations,
        "checks": result["checks"],
        "cost": draft.cost,
        "retries": attempt,
        "memory": memory,
    }

    b = coordinator.brief(out)
    trace.log("Coordinator", "briefing", f"{len(out['plan'])} lines, ₦{out['cost']:,}", b["reason"],
              target_agent="Pharmacist", model=b["model"], status="ok" if b["source"] == "nemotron" else "fallback")
    out["briefing"] = b
    return out
