"""Offline delivery scenarios for the integrated Phase 4.7 digital twin."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.application import CropDigitalTwinOrchestrator, SimulationClock, WeatherEngine
from agri_twin.domain import ActuatorControl, CropGrowthState, FertilizationRequest, IrrigationRequest, SoilState, WeatherState
from agri_twin.domain.weather import WeatherConfiguration


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


class FixedProvider:
    def __init__(self, state):
        self.state = state

    def get(self, timestamp):
        return self.state


def build(weather, mode="outdoor", available_n=200.0, vwc=0.25):
    clock = SimulationClock(T0)
    engine = WeatherEngine(WeatherConfiguration(), provider=FixedProvider(weather))
    crop = CropGrowthState(T0, "tomato", "RAF", "establishment", leaf_area_index=1.0, nutrient_reserve_kg_ha=200, nutrient_available_kg_ha=available_n)
    return CropDigitalTwinOrchestrator(clock, engine, crop, SoilState(vwc, 20, 0.32, 0.10, 20, 0), mode)


def weather(**changes):
    values = dict(temperature_c=24, relative_humidity_pct=70, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    checks = []

    def run(name, function):
        try:
            checks.append((name, "PASS", function()))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def normal():
        result = build(weather()).step(30 * 86400)
        require(result.crop.biomass_total > 0 and 0 <= result.crop.maturity_index <= 1, "normal lifecycle state invalid")
        return "normal exterior growth is reproducible and bounded"

    def water_and_nutrients():
        twin = build(weather(), available_n=0, vwc=0.12)
        deficit = twin.step(7 * 86400)
        recovered = twin.step(86400, irrigation=IrrigationRequest("manual", 100), fertilization=FertilizationRequest(200, 1, "manual"))
        require(recovered.crop.water_stress < deficit.crop.water_stress, "irrigation did not recover water stress")
        require(recovered.crop.nutrient_status > deficit.crop.nutrient_status, "fertilization did not recover nutrients")
        return "drought, irrigation, nutrient deficit and fertilization scenarios pass"

    def extremes():
        hot = build(weather(temperature_c=38, relative_humidity_pct=20)).step(3 * 86400)
        frost = build(weather(temperature_c=-5)).step(12 * 3600)
        require(hot.crop.heat_damage > 0 and frost.crop.frost_damage > 0, "extreme-event damage was not accumulated")
        return "heatwave and frost damage are visible in persistent state"

    def greenhouse_controls():
        outdoor = build(weather(temperature_c=38, solar_radiation_w_m2=1000)).step(86400)
        controlled = build(weather(temperature_c=38, solar_radiation_w_m2=1000), "actuated_greenhouse").step(86400, actuators={"cooling": ActuatorControl(5, maximum=5, capacity=5), "shade": ActuatorControl(0.5)})
        require(controlled.microclimate.indoor_state.temperature_c < outdoor.microclimate.indoor_state.temperature_c, "HVAC did not moderate temperature")
        require(controlled.microclimate.indoor_state.radiation_w_m2 < outdoor.microclimate.indoor_state.radiation_w_m2, "shade did not reduce radiation")
        return "greenhouse, HVAC and shade scenarios pass"

    def clock_and_determinism():
        first = build(weather())
        second = build(weather())
        a = first.step(3600)
        b = second.step(3600)
        require(a == b and a.simulation_time == first.clock.now(), "clock or determinism contract failed")
        source = (ROOT / "src" / "agri_twin" / "application" / "orchestrator.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source and "sleep(" not in source, "real-time dependency introduced")
        return "hour, day and long-step execution share one deterministic SimulationClock"

    run("Exterior normal lifecycle", normal)
    run("Water and nutrient scenarios", water_and_nutrients)
    run("Extreme climate scenarios", extremes)
    run("Greenhouse/HVAC/shade scenarios", greenhouse_controls)
    run("Clock and determinism", clock_and_determinism)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.9 INTEGRATION")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.9 STATUS: " + ("INTEGRATION READY - CALIBRATION PENDING" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())