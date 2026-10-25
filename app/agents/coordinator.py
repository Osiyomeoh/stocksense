"""Coordinator: writes the pharmacist's briefing from the verified plan, on
Nemotron through Nightshift.

The model only words what the other agents decided. Every number in its
text must appear in the facts it was given; if one doesn't, or Nightshift
can't be reached, the briefing falls back to a fixed template and says so.
"""

from __future__ import annotations

import json
import os
import re

from app.adapters import cache, nightshift

MODEL = os.environ.get("COORDINATOR_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

PROMPT = """You brief a district pharmacist in Nigeria on today's malaria-medicine (ACT) plan.
Use ONLY the facts in the JSON. Do not add numbers, clinics, suppliers or advice that are not in it.
Write at most 120 words, plain text, no lists or headings:
1. which clinics are at risk and why (road closing, below safety stock);
2. what moves where, what is bought, the total cost in naira;
3. anything on HOLD or not covered, which the pharmacist must decide.
End with: "Approve, edit or reject each line."
"""

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def facts(result: dict) -> dict:
    return {
        "status": result["status"],
        "flags": {c: f for c, f in result["flags"].items() if f},
        "roads": {c: r["reason"] for c, r in result["roads"].items() if r.get("closes_in_days") is not None},
        "plan": [{k: l[k] for k in ("kind", "source", "to", "qty", "deliver_day")} for l in result["plan"]],
        "purchase_order": result["purchase_order"] and {k: result["purchase_order"][k] for k in ("supplier", "qty", "cost", "lead_days")},
        "held": [h.get("clinic") or h.get("to") for h in result["held"]],
        "unmet": result["unmet"],
        "cost_naira": result["cost"],
    }


def numbers(text: str) -> set[str]:
    out = set()
    for n in NUMBER.findall(text):
        n = n.replace(",", "").rstrip(".")
        out.add(n[:-2] if n.endswith(".0") else n)
    return out


def unsupported_numbers(text: str, f: dict) -> list[str]:
    allowed = numbers(json.dumps(f, ensure_ascii=False)) | set("123")  # 1–3: the prompt's own numbering
    return sorted(numbers(text) - allowed)


def template(f: dict) -> str:
    lines = [f"{l['kind']} {l['qty']} from {l['source']} to {l['to']} (day {l['deliver_day']})" for l in f["plan"]]
    parts = [f"Status: {f['status']}. Plan: " + ("; ".join(lines) or "nothing to move") + f". Total ₦{f['cost_naira']:,}."]
    if f["held"]:
        parts.append("On HOLD: " + ", ".join(map(str, f["held"])) + ".")
    if f["unmet"]:
        parts.append("Not covered: " + ", ".join(f"{c} short by {n}" for c, n in f["unmet"].items()) + ".")
    return " ".join(parts) + " Approve, edit or reject each line."


def brief(result: dict) -> dict:
    """Return {"text", "model", "source": "nemotron"|"template", "reason"}."""
    f = facts(result)
    messages = [{"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps(f, ensure_ascii=False)}]
    try:
        out = nightshift.chat(messages, model=MODEL)
    except (nightshift.NightshiftError, cache.CacheMiss) as e:
        return {"text": template(f), "model": None, "source": "template", "reason": f"Nightshift unavailable: {e}"}
    bad = unsupported_numbers(out["text"], f)
    if bad:
        return {"text": template(f), "model": out["model"], "source": "template",
                "reason": f"model text had numbers not in the plan: {', '.join(bad)}"}
    return {"text": out["text"].strip(), "model": out["model"], "source": "nemotron", "reason": "all numbers match the plan"}
