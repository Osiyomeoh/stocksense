"""H-MEM changes a real decision: a pharmacist's note moves the next
purchase order to another supplier, and a correction moves it back to
asking the pharmacist. Runs the real H-MEM reference through the sidecar."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import config, data, pipeline
from app.adapters import hmem, nightshift
from app.agents import coordinator, memory_keeper
from app.trace import Trace


class MemoryChangesDecisionTests(unittest.TestCase):
    def setUp(self):
        d = mock.patch.object(config, "HMEM_DIR", Path(tempfile.mkdtemp(prefix="hmem-")))
        d.start()
        self.addCleanup(d.stop)

    def plan(self):
        # The recorded 2022-08-08 snapshot (rising river), replayed from data/sample_cache.
        reply = {"text": "Approve, edit or reject each line.", "model": coordinator.MODEL, "raw": {}}
        with mock.patch.object(config, "SAMPLE_MODE", True), \
             mock.patch.object(nightshift, "chat", return_value=reply):
            return pipeline.run("2022-08-08", Trace("test-memory"))

    def test_note_moves_the_order_then_a_correction_escalates_it(self):
        before = self.plan()["purchase_order"]
        self.assertEqual(before["supplier"], "S2")

        changes = memory_keeper.learn("S2 was late again, use S3")
        self.assertEqual([(c["action"], c["supplier"]) for c in changes], [("remembered", "S2")])

        out = self.plan()
        self.assertEqual(out["memory"]["avoid"], ["S2"])
        self.assertEqual(out["purchase_order"]["supplier"], "S3")
        self.assertLessEqual(out["cost"], data.SCENARIO["budget_per_quarter"])

        changes = memory_keeper.learn("S2 is fine now")
        self.assertEqual(changes[0]["action"], "marked_wrong")
        self.assertAlmostEqual(changes[0]["confidence"], 0.60)   # 0.80 - 0.20, H-MEM's "wrong" delta
        self.assertIn("review", changes[0]["tags"])

        out = self.plan()
        self.assertEqual(out["memory"]["escalate"], ["S2"])      # below 0.70: shown, not applied
        self.assertEqual(out["purchase_order"]["supplier"], "S2")

    def test_a_run_remembers_its_road_warnings_once(self):
        self.plan()
        self.plan()
        w = memory_keeper.road_warnings("2022-08-08")
        self.assertEqual(sorted(w), ["P3", "P5"])
        self.assertEqual(memory_keeper.road_warnings("2022-08-07"), {})  # no hindsight
        self.assertEqual(len(hmem.find("road", "warning")), 2)

    def test_note_without_a_known_supplier_stores_nothing(self):
        self.assertEqual(memory_keeper.learn("S9 was late; roads are bad"), [])
        self.assertEqual(self.plan()["memory"]["memories"], [])


