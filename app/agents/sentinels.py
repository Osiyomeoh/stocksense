"""Sentinels: one per clinic. Each raises flags; none decides anything."""

from __future__ import annotations

from app.agents.forecaster import RoadForecast
from app.data import Clinic


def watch(clinic: Clinic, road: RoadForecast, safety_days: int) -> list[str]:
    flags = []
    if clinic.stock is None:
        flags.append("missing_reading")
    elif clinic.days_of_stock < safety_days:
        flags.append("below_safety")
    if road.closes_in_days is not None:
        flags.append("road_closing")
    return flags


def run_all(clinics: list[Clinic], roads: dict[str, RoadForecast], safety_days: int) -> dict[str, list[str]]:
    return {c.clinic_id: watch(c, roads[c.clinic_id], safety_days) for c in clinics}
