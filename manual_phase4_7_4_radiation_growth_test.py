"""Offline delivery audit for Phase 4.7.4 radiation, LAI and biomass growth."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import CropGrowthState, RadiationGrowthEngine, WeatherState


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def state(stage: str = "vegetative_growth") -> CropGrowthState:
    return CropGrowthState(
        T0, "tomato", "unspecified", stage, biomass_total=50.0,
        biomass_leaf=50.0, leaf_area_index=1.0,
    )


def weather(radiation_w_m2: float) -> WeatherState:
    return WeatherState(25, 60, radiation_w_m2, 1, 180, 0, 1012)


def main() -> int:
    checks: list[tuple[str, str, str]] = []

    def run(name: str, function) -> None:
        try:
            checks.append((name, "PASS", str(function() or "verified")))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def radiation_and_growth() -> str:
        engine = RadiationGrowthEngine()
        initial = state()
        dark = engine.advance(initial, weather(0), 86400)
        lit = engine.advance(initial, weather(500), 86400)
        require(engine.par_mj_m2(500, 3600) == 0.864, "PAR interval conversion is invalid")
        require(dark.biomass_total == initial.biomass_total, "zero radiation must not grow biomass")
        require(lit.biomass_total > initial.biomass_total, "intercepted PAR must grow biomass")
        return "PAR conversion and radiation-dependent growth validate"

    def physical_bounds() -> str:
        engine = RadiationGrowthEngine()
        grown = engine.advance(state(), weather(900), 30 * 86400)
        total = grown.biomass_leaf + grown.biomass_stem + grown.biomass_root + grown.biomass_fruit
        require(grown.biomass_total == total, "partitioned biomass does not equal total")
        require(0 <= grown.leaf_area_index <= engine.profile_for("tomato").maximum_lai, "LAI bound is invalid")
        return "partition conservation and LAI bound validate for a large step"

    def senescence() -> str:
        engine = RadiationGrowthEngine()
        initial = state("post_harvest_dormancy")
        final = engine.advance(initial, weather(900), 86400)
        require(final.leaf_area_index < initial.leaf_area_index, "dormant canopy did not senesce")
        require(final.biomass_total == initial.biomass_total, "senescence must retain accounted biomass")
        return "post-harvest senescence is bounded and mass-accounted"

    def separation() -> str:
        source = (ROOT / "src" / "agri_twin" / "domain" / "radiation_growth.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source, "growth engine reads real time")
        require("SoilState" not in source and "ActuatorState" not in source, "growth engine owns another subsystem")
        return "no clock, soil, actuator or HVAC model was introduced"

    run("PAR conversion and growth", radiation_and_growth)
    run("Physical bounds and partition", physical_bounds)
    run("Senescence", senescence)
    run("Responsibility separation", separation)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.4 RADIATION GROWTH")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.4 STATUS: " + ("CORE READY - CALIBRATION PENDING" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())