"""Backtest the Forecaster on the real 2022 GloFAS season at Lokoja.

For every day before each road's actual first closure, run the app's own
forecaster on readings up to that day only, and compare its warning with
what happened. Reads the saved Open-Meteo response; --fetch refreshes it.

  python3 eval/backtest_forecaster.py [--fetch]
"""

import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app import data  # noqa: E402
from app.agents import forecaster  # noqa: E402
from app.data import Clinic  # noqa: E402

DATA = HERE / "glofas_lokoja_2022.json"
URL = ("https://flood-api.open-meteo.com/v1/flood?latitude=7.80&longitude=6.74"
       "&daily=river_discharge&start_date=2022-07-01&end_date=2022-10-31")
ROADS = {"P3": 4000.0, "P5": 3000.0, "P7": 9000.0}  # killtests/k2/road_register.csv, SYNTHETIC
HORIZON = data.SCENARIO["forecast_horizon_days"]


def main(argv):
    if "--fetch" in argv:
        DATA.write_bytes(urllib.request.urlopen(URL, timeout=60).read())
    daily = json.loads(DATA.read_text())["daily"]
    river = [(t, q) for t, q in zip(daily["time"], daily["river_discharge"]) if q is not None]

    print(f"GloFAS Lokoja {river[0][0]}..{river[-1][0]}, horizon {HORIZON} days")
    print("road  closes      first warning           unflagged in last 30d  forecast date late  with held warnings: unflagged, late")
    for cid, thr in ROADS.items():
        closes = next(i for i, (_, q) in enumerate(river) if q >= thr)
        clinic = Clinic(cid, cid, "", 0, 1.0, None, None, thr, 0, 0)
        flagged, late, first, missed = 0, 0, None, 0
        h_flagged, h_late, h_missed, warning = 0, 0, 0, {}
        for i in range(1, closes):
            f = forecaster.forecast([clinic], river[: i + 1], HORIZON)
            held = forecaster.hold(f, warning, river[i][0], HORIZON)[cid]
            if f[cid].closes_in_days is not None:  # a fresh warning replaces the held one, as in the app
                warning = {cid: {"since": river[i][0], "days": f[cid].closes_in_days, "river": f[cid].river_m3s}}
            f = f[cid]
            actual = closes - i
            if actual > HORIZON:
                continue
            if held.closes_in_days is None:
                h_missed += 1
            else:
                h_flagged += 1
                h_late += held.closes_in_days > actual
            if f.closes_in_days is None:
                missed += 1
                continue
            flagged += 1
            first = first or (river[i][0], actual)
            late += f.closes_in_days > actual
        warn = f"{first[0]} ({first[1]}d ahead)" if first else "never"
        print(f"{cid:4}  {river[closes][0]}  {warn:22}  {f"{missed} days":22}  {f"{late}/{flagged} days":18}  {h_missed} days, {h_late}/{h_flagged}")


if __name__ == "__main__":
    main(sys.argv[1:])
