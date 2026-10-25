import json
import unittest
from unittest import mock

import run
from app import config
from app.adapters import cache
from app.trace import FIELDS


class RunTests(unittest.TestCase):
    def test_bad_date_is_a_structured_400(self):
        status, body = run.handle('{"as_of": "July"}')
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["type"], "bad_input")

    def test_bad_json_is_a_structured_400(self):
        status, body = run.handle("{")
        self.assertEqual((status, body["error"]["type"]), (400, "bad_json"))

    def test_sample_mode_replays_cache_and_writes_a_full_trace(self):
        clinics = json.loads((config.SAMPLE_DIR / "zetaris" / "4a8de106818241d8.json").read_text())["response"]
        river = {"headers": ["obs_date", "discharge_m3s"], "data": [["2022-07-04", "1058.25"]]}
        replay = lambda kind, req: river if "glofas" in req["sql"] else clinics
        with mock.patch.object(config, "SAMPLE_MODE", True), mock.patch.object(cache, "load", side_effect=replay):
            status, body = run.handle('{"as_of": "2022-07-04"}')
        self.assertEqual(status, 200)
        self.assertEqual(body["held"][-1]["clinic"], "P6")
        event = json.loads((config.ROOT / body["trace"]).read_text().splitlines()[0])
        self.assertEqual(tuple(event)[: len(FIELDS)], FIELDS)

    def test_sample_mode_cache_miss_is_a_structured_503(self):
        with mock.patch.object(config, "SAMPLE_MODE", True), \
             mock.patch.object(config, "SAMPLE_DIR", config.ROOT / "logs" / "no-cache-here"):
            status, body = run.handle('{"as_of": "2022-07-04"}')
        self.assertEqual((status, body["error"]["type"]), (503, "sample_cache_miss"))


if __name__ == "__main__":
    unittest.main()
