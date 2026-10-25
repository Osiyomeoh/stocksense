"""Every Zetaris query the agents make. Values arrive as strings; cast here."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from app import config
from app.adapters import zetaris

SCENARIO = json.loads((config.ROOT / "config" / "kafin.json").read_text(encoding="utf-8"))

RIVER_TABLE = "k2_src.glofas_lokoja_2022"


class NoSnapshot(ValueError):
    pass


@dataclass(frozen=True)
class Clinic:
    clinic_id: str
    name: str
    as_of: str
    stock: int | None  # None = the clinic did not report
    daily_use: float
    road_id: str | None
    road_surface: str | None
    closes_above_m3s: float | None
    capacity: int
    km_to_store: float

    @property
    def days_of_stock(self) -> float | None:
        return None if self.stock is None else self.stock / self.daily_use


def _num(value: Any, cast=float):
    return None if value is None else cast(float(value))


def clinic_sql(clinic_ids: list[str] | None = None) -> str:
    where = ""
    if clinic_ids:
        where = " WHERE clinic_id IN (" + ", ".join(f"'{c}'" for c in sorted(clinic_ids)) + ")"
    return f"SELECT * FROM {config.CLINIC_RISK_TABLE}{where} ORDER BY clinic_id"


def load_clinics(as_of: str, clinic_ids: list[str] | None = None) -> list[Clinic]:
    rows = zetaris.query(clinic_sql(clinic_ids))
    snapshots = {r["as_of"] for r in rows}
    if as_of not in snapshots:
        raise NoSnapshot(f"no stock snapshot for {as_of} in Zetaris (have: {', '.join(sorted(snapshots)) or 'none'})")
    clinics = []
    for r in rows:
        if r["as_of"] != as_of:
            continue
        extra = SCENARIO["clinics"][r["clinic_id"]]
        clinics.append(Clinic(
            clinic_id=r["clinic_id"],
            name=r["clinic_name"],
            as_of=r["as_of"],
            stock=_num(r["stock_courses"], int),
            daily_use=_num(r["daily_use_rainy"]),
            road_id=r["road_id"],
            road_surface=r["road_surface"],
            closes_above_m3s=_num(r["closes_above_m3s"]),
            capacity=extra["capacity"],
            km_to_store=extra["km_to_store"],
        ))
    return clinics


def river_sql(as_of: str, table: str = RIVER_TABLE) -> str:
    """Daily GloFAS discharge up to and including as_of: no later data."""
    date.fromisoformat(as_of)  # as_of is validated before it reaches SQL
    return (
        "SELECT CAST(t AS DATE) AS obs_date, CAST(g.daily.river_discharge[i] AS DOUBLE) AS discharge_m3s "
        f"FROM {table} g LATERAL VIEW posexplode(g.daily.time) p AS i, t "
        f"WHERE CAST(t AS DATE) <= DATE '{as_of}' ORDER BY obs_date"
    )


def river_on_sql(as_of: str, table: str = RIVER_TABLE) -> str:
    """The single as_of reading, for the Evaluator's re-check."""
    return river_sql(as_of, table).replace("<= DATE", "= DATE")


def load_river_on(as_of: str, table: str = RIVER_TABLE) -> float | None:
    rows = zetaris.query(river_on_sql(as_of, table))
    return float(rows[-1]["discharge_m3s"]) if rows and rows[-1]["discharge_m3s"] is not None else None


def load_river(as_of: str, table: str = RIVER_TABLE) -> list[tuple[str, float]]:
    rows = zetaris.query(river_sql(as_of, table))
    return [(r["obs_date"], float(r["discharge_m3s"])) for r in rows if r["discharge_m3s"] is not None]
