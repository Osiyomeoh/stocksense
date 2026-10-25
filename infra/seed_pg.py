"""Add the 2022-08-08 stock snapshot and local copies of the river and rain
series to the StockSense RDS Postgres, and let the Zetaris read-only role
read them.

  stock (+8 rows)   SYNTHETIC Kafin LGA scenario, as_of 2022-08-08
  river_daily       GloFAS discharge at Lokoja, real (eval/glofas_lokoja_2022.json)
  rain_daily        Open-Meteo archive rain at Lokoja, real (eval/rain_lokoja_2022.json)

Zetaris re-fetches a REST table on every query (about 3 minutes each); a
Postgres copy of the same Open-Meteo responses reads in seconds.

Settings come from .env. Secret values are never printed or put on a command
line: the password reaches psql through PGPASSWORD.

  python3 -I infra/seed_pg.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RO_ROLE = "zetaris_k2"

# SYNTHETIC: week 6 of the rainy season. Daily use is the rainy-season monthly figure / 30.
AUGUST = [  # clinic, stock, monthly use
    ("P1", 700, 520), ("P2", 150, 300), ("P3", 90, 260), ("P4", 800, 380),
    ("P5", 60, 170), ("P6", 200, 220), ("P7", 300, 270), ("P8", 850, 330),
]


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    return values


def series_sql(table, column, path, field):
    daily = json.loads(path.read_text())["daily"]
    rows = ",\n    ".join(f"('LOKOJA', DATE '{t}', {v})" for t, v in zip(daily["time"], daily[field]) if v is not None)
    return f"""
DROP TABLE IF EXISTS {table};
CREATE TABLE {table} (
    river_point varchar(16) NOT NULL,
    obs_date    date        NOT NULL,
    {column}    double precision NOT NULL,
    data_label  varchar(32) NOT NULL DEFAULT 'Open-Meteo',
    PRIMARY KEY (river_point, obs_date)
);
INSERT INTO {table} (river_point, obs_date, {column}) VALUES
    {rows};
"""


def main():
    cfg = read_env(ROOT / ".env")
    for key in ("STOCKSENSE_PG_HOST", "STOCKSENSE_PG_PASSWORD"):
        if not cfg.get(key):
            sys.exit(f"{key} is empty in .env")
    env = dict(os.environ, PGHOST=cfg["STOCKSENSE_PG_HOST"], PGPORT=cfg.get("STOCKSENSE_PG_PORT") or "5432",
               PGDATABASE=cfg.get("STOCKSENSE_PG_DB") or "stocksense", PGUSER=cfg.get("STOCKSENSE_PG_USER") or "postgres",
               PGPASSWORD=cfg["STOCKSENSE_PG_PASSWORD"], PGSSLMODE="require", PGCONNECT_TIMEOUT="15")

    stock = ",\n    ".join(f"('{c}', DATE '2022-08-08', 'ACT', {s}, {m} / 30.0)" for c, s, m in AUGUST)
    sql = f"""
BEGIN;
DELETE FROM stock WHERE as_of = DATE '2022-08-08';
INSERT INTO stock (clinic_id, as_of, item, stock_courses, daily_use_rainy) VALUES
    {stock};
{series_sql("river_daily", "discharge_m3s", ROOT / "eval" / "glofas_lokoja_2022.json", "river_discharge")}
{series_sql("rain_daily", "precipitation_mm", ROOT / "eval" / "rain_lokoja_2022.json", "precipitation_sum")}
GRANT SELECT ON river_daily, rain_daily TO {RO_ROLE};
COMMIT;
SELECT (SELECT string_agg(as_of || ':' || n, ', ' ORDER BY as_of) FROM (SELECT as_of, count(*) n FROM stock GROUP BY as_of) s)
    || ' | river ' || (SELECT count(*) || ' days ' || min(obs_date) || '..' || max(obs_date) FROM river_daily)
    || ' | rain ' || (SELECT count(*) || ' days' FROM rain_daily);
"""
    r = subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-q", "-At"], input=sql, env=env,
                       text=True, capture_output=True, check=False)
    if r.returncode:
        sys.exit(f"seed failed: {r.stderr.strip()}")
    print(f"ok: {r.stdout.strip()}")


if __name__ == "__main__":
    main()
