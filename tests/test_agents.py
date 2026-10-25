import json
import unittest
from unittest import mock

from app import config, data, pipeline
from app.adapters import zetaris
from app.agents import critic, forecaster, planner
from app.trace import Trace

RECORDED = json.loads((config.SAMPLE_DIR / "zetaris" / "4a8de106818241d8.json").read_text())["response"]
CLINIC_ROWS = [dict(zip(RECORDED["headers"], r)) for r in RECORDED["data"]]


def river_rows(values):
    return [{"obs_date": f"2022-06-{d:02d}", "discharge_m3s": str(q)} for d, q in enumerate(values, 1)]


def fake_query(river, clinic_rows=CLINIC_ROWS, fail_on=None):
    def query(sql, limit=1000):
        if fail_on and fail_on in sql:
            raise zetaris.ZetarisError("cluster suspended")
        if "glofas" in sql:
            return river_rows(river)
        ids = [c for c in "P1 P2 P3 P4 P5 P6 P7 P8".split() if f"'{c}'" in sql]
        return [r for r in clinic_rows if not ids or r["clinic_id"] in ids]
    return query


RISING = [1000 + 100 * i for i in range(7)]  # +100/day, ends at 1600


class ForecasterTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(zetaris, "query", fake_query(RISING)):
            self.clinics = data.load_clinics("2022-07-04")

    def test_days_to_threshold_from_the_trend(self):
        roads = forecaster.forecast(self.clinics, [("d", q) for q in RISING], 30)
        self.assertEqual(roads["P5"].closes_in_days, 14.0)   # (3000-1600)/100
        self.assertEqual(roads["P3"].closes_in_days, 24.0)   # (4000-1600)/100
        self.assertIsNone(roads["P7"].closes_in_days)        # 74 days: beyond horizon
        self.assertIsNone(roads["P1"].closes_in_days)        # tarred, no threshold
        self.assertEqual(roads["P5"].confidence, 1.0)

    def test_falling_river_closes_nothing(self):
        roads = forecaster.forecast(self.clinics, [("d", q) for q in reversed(RISING)], 30)
        self.assertTrue(all(r.closes_in_days is None for r in roads.values()))


class PlannerCriticTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(zetaris, "query", fake_query(RISING)):
            self.clinics = data.load_clinics("2022-07-04")
        self.roads = forecaster.forecast(self.clinics, [("d", q) for q in RISING], 30)

    def test_missing_reading_is_held_not_planned(self):
        p = planner.plan(self.clinics, self.roads, data.SCENARIO)
        self.assertEqual([h["clinic"] for h in p.holds], ["P6"])
        self.assertNotIn("P6", {l.to for l in p.lines})

    def test_plan_passes_the_critic_and_keeps_donors_safe(self):
        p = planner.plan(self.clinics, self.roads, data.SCENARIO)
        self.assertEqual(critic.review(p, self.clinics, self.roads, data.SCENARIO), [])
        # rising river: gap 316, so S2 (316 x 2500 = 790k) beats S3 (min 500 x 2000 = 1M)
        self.assertEqual((p.order["supplier"], p.order["cost"]), ("S2", 790000))

    def test_late_purchase_to_a_closing_road_is_rejected_with_a_fix(self):
        roads = dict(self.roads)
        roads["P5"] = forecaster.RoadForecast("P5", 5.0, 0.9, 1600, 100, "test")
        p = planner.Plan(lines=[planner.Line("purchase", "P5", 100, 0, 8, "S3", "test")])
        v = critic.review(p, self.clinics, roads, data.SCENARIO)
        self.assertEqual([(x["rule"], x["fix"]) for x in v], [("road_open_on_delivery", {"no_purchase_to": ["P5"]})])


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, river, **kw):
        with mock.patch.object(zetaris, "query", fake_query(river, **kw)):
            return pipeline.run("2022-07-04", Trace("test-agents"))

    def test_critic_retry_reroutes_a_closing_road_to_transfers(self):
        fast = [1000 + 300 * i for i in range(7)]  # 2800 now, P5 (3000) closes in under a day
        out = self.run_pipeline(fast)
        self.assertGreaterEqual(out["retries"], 1)
        p5 = [l for l in out["plan"] if l["to"] == "P5"]
        self.assertTrue(p5 and all(l["kind"] == "transfer" for l in p5) or "P5" in out["unmet"])

    def test_evaluator_holds_lines_when_zetaris_fails_on_re_query(self):
        out = self.run_pipeline(RISING, fail_on="WHERE clinic_id IN")
        self.assertEqual(out["plan"], [])
        self.assertTrue(all("could not be re-read" in h["hold_reason"] for h in out["held"] if "hold_reason" in h))
        self.assertEqual(out["status"], "needs_review")

    def test_no_snapshot_for_another_date(self):
        with mock.patch.object(zetaris, "query", fake_query(RISING)):
            with self.assertRaises(data.NoSnapshot):
                pipeline.run("2022-08-01", Trace("test-agents"))


if __name__ == "__main__":
    unittest.main()
