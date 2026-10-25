"""Memory Keeper: what the pharmacist taught us about suppliers, kept in H-MEM.

learn() turns an EDIT note ("S2 was late again, use S3") into memories;
recall() runs before planning and hands trusted ones to the Planner as
avoid_suppliers. A memory below TRUST is not applied: it is shown to the
pharmacist to confirm, so one wrong note can't quietly steer every plan.
"""

from __future__ import annotations

import re

from app import data
from app.adapters import hmem

TRUST = 0.70  # H-MEM's auto-resolve gate
NOTE_CONFIDENCE = 0.80
NEGATIVE = re.compile(r"\b(late|avoid|skip|stop|don'?t|do not|never|short|failed|unreliable)\b", re.I)
POSITIVE = re.compile(r"\b(fine|ok|okay|reliable|on time|back|good)\b", re.I)


def _suppliers(clause: str) -> list[str]:
    return [s for s in re.findall(r"\bS\d+\b", clause.upper()) if s in data.SCENARIO["suppliers"]]


def learn(note: str) -> list[dict]:
    """Store or correct supplier memories from one note. Returns what changed."""
    changes = []
    for clause in re.split(r"[,.;]|\bbut\b", note):
        for s in _suppliers(clause):
            if NEGATIVE.search(clause):
                m = hmem.add(f"Avoid supplier {s}: {note.strip()}", ["supplier", "avoid", s],
                             NOTE_CONFIDENCE, "pharmacist", "pharmacist edit")
                changes.append({"action": "remembered", "supplier": s, **m})
            elif POSITIVE.search(clause):
                for m in hmem.find("supplier", "avoid", s):
                    changes.append({"action": "marked_wrong", "supplier": s, **hmem.feedback(m["id"], "wrong")})
    return changes


def recall() -> dict:
    """{"avoid": [...], "escalate": [...], "memories": [...]} for the suppliers we know."""
    avoid, escalate, used = set(), set(), []
    for m in hmem.find("supplier", "avoid"):
        s = next((t for t in m["tags"] if t in data.SCENARIO["suppliers"]), None)
        if s is None:
            continue
        (avoid if m["confidence"] >= TRUST else escalate).add(s)
        used.append(m)
    return {"avoid": sorted(avoid), "escalate": sorted(escalate - avoid), "memories": used}


def road_warnings(as_of: str) -> dict[str, dict]:
    """The latest remembered road warning per clinic, raised on or before as_of."""
    out: dict[str, dict] = {}
    for m in hmem.find("road", "warning"):
        t = dict(x.split(":", 1) for x in m["tags"] if ":" in x)
        if {"clinic", "since", "days", "river"} <= t.keys() and t["since"] <= as_of \
                and t["since"] >= out.get(t["clinic"], {}).get("since", ""):
            out[t["clinic"]] = {"since": t["since"], "days": float(t["days"]), "river": float(t["river"]), "id": m["id"]}
    return out


def remember_roads(roads: dict, as_of: str, known: dict[str, dict]) -> list[dict]:
    """Store each fresh warning (forecast, not held) not already stored for this date."""
    out = []
    for cid, r in roads.items():
        if r.closes_in_days is None or r.reason.startswith("warning from") or known.get(cid, {}).get("since") == as_of:
            continue
        out.append(hmem.add(f"Road to {cid} warned on {as_of}: {r.reason}",
                            ["road", "warning", f"clinic:{cid}", f"since:{as_of}", f"days:{r.closes_in_days}",
                             f"river:{r.river_m3s}"], r.confidence or 0.5, "forecaster", "road warning"))
    return out
