"""Offline delivery audit for Phase 4.7.7 climate stress."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import ClimateStressEngine, CropGrowthState, WeatherState


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def state(**changes):
    values = dict(simulation_time=T0, crop_key="tomato", variety="unspecified", current_stage="vegetative_growth", leaf_area_index=2.0, biomass_total=100, biomass_leaf=100)
    values.update(changes)
    return CropGrowthState(**values)


def weather(**changes):
    values = dict(temperature_c=25, relative_humidity_pct=70, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def main() -> int:
    checks = []

    def run(name, function):
        try:
            checks.append((name, "PASS", function()))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def extremes():
        engine = ClimateStressEngine()
        frost = engine.advance(state(), weather(temperature_c=-8), 12 * 3600)
        heat = engine.advance(state(), weather(temperature_c=35), 3 * 86400)
        require(frost.frost_damage > 0 and frost.state.frost_exposure_hours > 0, "frost exposure was not accumulated")
        require(heat.heat_damage > 0 and heat.state.heat_exposure_hours > 0, "heat wave was not accumulated")
        return "frost and consecutive heat exposure accumulate continuously"

    def factors():
        engine = ClimateStressEngine()
        result = engine.advance(state(water_stress=0.2, nutrient_status=0.8), weather(relative_humidity_pct=10, solar_radiation_w_m2=1000), 3600)
        require(all(0 <= value <= 1 for value in (result.temperature_factor, result.vpd_factor, result.water_factor, result.radiation_factor, result.nutrient_factor)), "factor outside [0,1]")
        require(ClimateStressEngine.combine_growth(100, result) <= 100, "growth factors were not applied")
        return "independent temperature, VPD, radiation, water and nutrient factors validate"

    def recovery_and_separation():
        engine = ClimateStressEngine()
        stressed = engine.advance(state(), weather(temperature_c=-8), 12 * 3600)
        recovered = engine.advance(stressed.state, weather(), 10 * 86400)
        require(recovered.frost_damage < stressed.frost_damage, "recoverable frost damage did not recover")
        require(recovered.irreversible_damage >= stressed.irreversible_damage, "irreversible damage decreased")
        source = (ROOT / "src" / "agri_twin" / "domain" / "climate_stress.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source, "stress engine reads real time")
        return "recovery is bounded and no parallel clock was introduced"

    run("Extreme-event accumulation", extremes)
    run("Continuous growth factors", factors)
    run("Recovery and separation", recovery_and_separation)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.7 CLIMATE STRESS")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.7 STATUS: " + ("CLIMATE CORE READY - CALIBRATION PENDING" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())