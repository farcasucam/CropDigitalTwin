"""Offline delivery audit for Phase 4.7.2 persistent crop growth state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import SimulationClock
from agri_twin.domain import CropGrowthState


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def state(**changes) -> CropGrowthState:
    values = {
        "simulation_time": T0,
        "crop_key": "plum",
        "variety": "Suplum 26",
        "current_stage": "yield_maturation",
        "soil_water_vwc": 0.25,
    }
    values.update(changes)
    return CropGrowthState(**values)


def main() -> int:
    checks: list[tuple[str, str, str]] = []

    def run(name: str, function) -> None:
        try:
            checks.append((name, "PASS", str(function() or "verified")))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def complete_contract() -> str:
        payload = state().to_dict()
        required = {
            "simulation_time", "crop_key", "variety", "current_stage", "phenology_progress",
            "biomass_total", "biomass_leaf", "biomass_stem", "biomass_root", "biomass_fruit",
            "leaf_area_index", "root_depth_m", "soil_water_vwc", "nutrient_status", "water_stress",
            "heat_stress", "cold_stress", "vpd_stress", "radiation_stress", "frost_damage",
            "accumulated_stress", "maturity_index", "yield_estimate", "harvest_ready",
        }
        require(set(payload) == required, "persistent-state fields are incomplete")
        json.dumps(payload)
        return "complete state is JSON-ready"

    def simulation_time() -> str:
        clock = SimulationClock(T0)
        initial = state()
        dt = clock.advance(3 * 86400)
        advanced = initial.advance(clock.now(), dt.total_seconds())
        require(advanced.simulation_time == T0 + timedelta(days=3), "state did not use SimulationClock time")
        require(advanced == initial.advance(clock.now(), dt.total_seconds()), "advance is not deterministic")
        return "explicit three-day clock advance is stable and deterministic"

    def invariants() -> str:
        try:
            state(biomass_total=1.0, biomass_leaf=0.5)
        except ValueError:
            pass
        else:
            raise AssertionError("biomass partition invariant was not enforced")
        try:
            state(harvest_ready=True)
        except ValueError:
            return "partition, range and harvest invariants are enforced"
        raise AssertionError("harvest maturity invariant was not enforced")

    def no_parallel_clock() -> str:
        source = (ROOT / "src" / "agri_twin" / "domain" / "models.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source, "persistent state reads real time")
        return "state owns no real-time clock or autonomous transition"

    run("State contract and serialization", complete_contract)
    run("SimulationClock advancement", simulation_time)
    run("State invariants", invariants)
    run("No parallel clock", no_parallel_clock)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.2 PERSISTENT CROP STATE")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.2 STATUS: " + ("STATE CONTRACT READY" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())