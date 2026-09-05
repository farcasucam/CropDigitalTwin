"""Offline delivery audit for Phase 4.7.5 root-zone water balance."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import CropGrowthState, IrrigationRequest, SoilState, WaterBalanceEngine, WeatherState


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def weather(**changes) -> WeatherState:
    values = dict(temperature_c=25, relative_humidity_pct=50, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def crop(**changes) -> CropGrowthState:
    values = dict(simulation_time=T0, crop_key="tomato", variety="unspecified", current_stage="vegetative_growth", leaf_area_index=2.0, root_depth_m=0.5, soil_water_vwc=0.25)
    values.update(changes)
    return CropGrowthState(**values)


def soil(vwc: float = 0.25) -> SoilState:
    return SoilState(vwc, 20, 0.35, 0.10, 20, 0)


def main() -> int:
    checks: list[tuple[str, str, str]] = []

    def run(name: str, function) -> None:
        try:
            checks.append((name, "PASS", str(function() or "verified")))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def rainfall_and_drought() -> str:
        engine = WaterBalanceEngine()
        dry = engine.advance(soil(0.20), weather(), 3600, crop())
        wet = engine.advance(soil(0.20), weather(rain_rate_mm_h=20), 3600, crop())
        require(wet.soil.vwc_m3_m3 > dry.soil.vwc_m3_m3 and dry.water_stress > 0, "rainfall/drought causality failed")
        return "rainfall increases storage and dry soil produces stress"

    def irrigation_and_drainage() -> str:
        engine = WaterBalanceEngine()
        irrigated = engine.advance(soil(), weather(), 3600, crop(), IrrigationRequest("manual", 20, irrigation_type="overhead"))
        saturated = engine.advance(soil(0.34), weather(), 3600, crop(), IrrigationRequest("scheduled", 100))
        require(irrigated.irrigation_applied_mm == 15, "irrigation efficiency was not applied")
        require(saturated.drainage_mm > 0 and saturated.soil.vwc_m3_m3 <= 0.35, "over-irrigation did not drain safely")
        return "manual/scheduled irrigation, efficiency and drainage validate"

    def crop_coupling_and_determinism() -> str:
        engine = WaterBalanceEngine()
        first = engine.advance(soil(0.15), weather(rain_rate_mm_h=2), 30 * 86400, crop())
        second = engine.advance(soil(0.15), weather(rain_rate_mm_h=2), 30 * 86400, crop())
        require(first == second and 0.10 <= first.soil.vwc_m3_m3 <= 0.35, "large timestep is not deterministic/bounded")
        require(first.transpiration_mm > 0 and first.storage_mm >= 0, "crop coupling/storage output missing")
        return "LAI, root depth, phase, ET and accelerated timestep are deterministic"

    def separation() -> str:
        source = (ROOT / "src" / "agri_twin" / "domain" / "water_balance.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source, "water balance reads real time")
        require("WeatherEngine" not in source and "SimulationClock" not in source, "water balance owns another subsystem")
        return "weather acquisition and clock remain external"

    run("Rainfall and drought", rainfall_and_drought)
    run("Irrigation and drainage", irrigation_and_drainage)
    run("Crop coupling and determinism", crop_coupling_and_determinism)
    run("Responsibility separation", separation)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.5 WATER BALANCE")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.5 STATUS: " + ("WATER CORE READY - CALIBRATION PENDING" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())