"""Check every number the README states, with no keys, cluster or network.

  python3 prove.py

Each claim is checked twice: the README must say it (so the docs can't
drift), and a fresh run must produce it. Runs replay the recorded Zetaris
and Nightshift responses in data/sample_cache; memory uses a throwaway
H-MEM directory. Exit code 0 only if every claim passes.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["SAMPLE_MODE"] = "true"
os.environ["HMEM_DIR"] = tempfile.mkdtemp(prefix="hmem-prove-")

from app import config  # noqa: E402
import run  # noqa: E402
from app.agents import coordinator, memory_keeper  # noqa: E402
from app.trace import FIELDS  # noqa: E402

sys.path.insert(0, str(config.ROOT / "eval"))
import backtest_forecaster  # noqa: E402
import season  # noqa: E402

README = (config.ROOT / "README.md").read_text()
EXAMPLES = config.ROOT / "examples"
results: list[tuple[bool, str, str]] = []


def claim(text: str, says: str | None, actual, expected) -> None:
    """says: the exact phrase the README must contain (None: not a README number)."""
    ok = actual == expected and (says is None or says in README)
    why = "" if ok else (f"README lacks {says!r}" if says and says not in README else f"got {actual!r}, expected {expected!r}")
    results.append((ok, text, why))


def fresh_memory() -> None:
    config.HMEM_DIR = Path(tempfile.mkdtemp(prefix="hmem-prove-"))


def plan(as_of: str) -> dict:
    status, body = run.handle(json.dumps({"as_of": as_of}))
    if status != 200:
        raise SystemExit(f"replay of {as_of} failed: {body}")
    return body


def trace_events(body: dict) -> list[dict]:
    return [json.loads(l) for l in (config.ROOT / body["trace"]).read_text().splitlines() if l]


def examples() -> None:
    keep = ("status", "cost", "plan", "held", "purchase_order", "unmet", "retries", "briefing")
    for inp in sorted((EXAMPLES / "input_examples").glob("*.json")):
        fresh_memory()
        status, body = run.handle(inp.read_text())
        want = json.loads((EXAMPLES / "output_examples" / inp.name).read_text())
        got = {k: body.get(k) for k in keep if k in want}
        claim(f"{inp.name} reproduces its recorded output", None, got, {k: want[k] for k in got})


def july() -> None:
    fresh_memory()
    b = plan("2022-07-04")
    kinds = [l["kind"] for l in b["plan"]]
    claim("07-04 plan costs ₦514,850", "₦514,850", b["cost"], 514850)
    claim("07-04 plan: 4 transfers, 1 purchase", "4 transfers, 1 purchase", (kinds.count("transfer"), kinds.count("purchase")), (4, 1))
    claim("07-04 puts P6 on HOLD", "P6 on HOLD", [h.get("clinic") or h.get("to") for h in b["held"]], ["P6"])
    events = trace_events(b)
    claim("every trace event has all fields", None, all(set(FIELDS) <= e.keys() for e in events), True)


def august() -> None:
    fresh_memory()
    b = plan("2022-08-08")
    roads = {c: r["closes_in_days"] for c, r in b["roads"].items() if r["closes_in_days"] is not None}
    claim("08-08 plan costs ₦521,900", "₦521,900", b["cost"], 521900)
    claim("08-08 flags P3 and P5 (23.9 and 12.1 days)", None, roads, {"P3": 23.9, "P5": 12.1})
    claim("08-08 needs one Critic retry", None, b["retries"], 1)
    rejected = [e for e in trace_events(b) if e["agent_name"] == "Critic" and e["status"] == "rejected"]
    claim("the Critic rejects the 8-day purchase to P3", "rejects an 8-day purchase to P3",
          any("P3" in e["output_summary"] for e in rejected), True)
    f = coordinator.facts(b)
    claim("08-08 briefing is from Nemotron", None, b["briefing"]["source"], "nemotron")
    claim("every number in the briefing is in the plan", None, coordinator.unsupported_numbers(b["briefing"]["text"], f), [])


def memory() -> None:
    fresh_memory()
    order = lambda b: (b["purchase_order"]["supplier"], b["purchase_order"]["qty"], b["purchase_order"]["cost"])
    claim("no notes: order is 200 from S2, ₦500,000", "200 courses from S2, ₦500,000", order(plan("2022-08-08")), ("S2", 200, 500000))
    m = memory_keeper.learn("S2 was late again, use S3")
    claim("a note is stored at confidence 0.80", "confidence 0.80", [c["confidence"] for c in m], [0.8])
    b = plan("2022-08-08")
    claim("after the note: 500 from S3, ₦1,000,000", "500 courses from S3, ₦1,000,000", order(b), ("S3", 500, 1000000))
    claim("the plan stays inside the ₦4,000,000 budget", "₦4,000,000 budget", b["cost"] <= 4_000_000, True)
    m = memory_keeper.learn("S2 is fine now")
    claim("a contradicting note drops it to 0.60", "0.80 → 0.60", [round(c["confidence"], 2) for c in m], [0.6])
    b = plan("2022-08-08")
    claim("below 0.70 it is escalated, not applied", "0.70 gate", (b["memory"]["escalate"], order(b)[0]), (["S2"], "S2"))


def backtest() -> None:
    rows = {r["road"]: r for r in backtest_forecaster.rows(backtest_forecaster.load())}
    readme = {  # road: (README row, first warning, days ahead, missed, late/flagged, held missed, held late/flagged)
        "P3": ("| P3 | 2022-08-28 | 2022-07-29, 30 days ahead | 9 | 5 of 21 | 0, 5 of 30 |", "2022-07-29", 30, 9, (5, 21), 0, (5, 30)),
        "P5": ("| P5 | 2022-08-14 | 2022-07-23, 22 days ahead | 9 | 13 of 21 | 8, 14 of 22 |", "2022-07-23", 22, 9, (13, 21), 8, (14, 22)),
        "P7": ("| P7 | 2022-09-12 | 2022-08-13, 30 days ahead | 12 | 6 of 18 | 0, 6 of 30 |", "2022-08-13", 30, 12, (6, 18), 0, (6, 30)),
    }
    for road, (row, first, ahead, missed, late, h_missed, h_late) in readme.items():
        r = rows[road]
        got = (r["closes"], r["first_warning"], r["missed"], (r["late"], r["flagged"]), r["held_missed"], (r["held_late"], r["held_flagged"]))
        want = (row.split(" | ")[1], (first, ahead), missed, late, h_missed, h_late)
        claim(f"backtest row {road} matches the real 2022 river", row, got, want)


def season_replay() -> None:
    river = backtest_forecaster.load()
    naive, ours = season.simulate("naive", river), season.simulate("stocksense", river)
    fresh_memory()
    claim("season: naive rule leaves 93 clinic-days without medicine", "| 93 | 654 | ₦24,541,000 |",
          (naive["stockout_days"], naive["courses_short"], naive["spend"]), (93, 654, 24541000))
    claim("season: StockSense leaves 73", "| **73** | **498** | **₦18,279,200** |",
          (ours["stockout_days"], ours["courses_short"], ours["spend"]), (73, 498, 18279200))
    claim("season: 20 fewer clinic-days, 26% less spend", "20 fewer clinic-days without medicine than the naive rule, at 26% less spend",
          (naive["stockout_days"] - ours["stockout_days"], round(100 * (1 - ours["spend"] / naive["spend"]))), (20, 26))
    ui = (config.ROOT / "app" / "ui" / "index.html").read_text()
    claim("UI header states the same season result", None,
          all(s in ui for s in ("<b>20 fewer clinic-days without medicine</b>", "<b>26% less spend</b>")), True)


def main() -> int:
    for section in (examples, july, august, memory, backtest, season_replay):
        section()
    for ok, text, why in results:
        print(f"{'PASS' if ok else 'FAIL'}  {text}" + (f"  ({why})" if why else ""))
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} claims proven" + (f", {failed} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
