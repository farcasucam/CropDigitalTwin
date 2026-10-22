"""Regression tests for what each intervention does to the outputs (see docs/auditoria_modelos_prediccion.md).

The first group holds invariants that already hold and must keep holding. The second group states what a correct model would do for each audited defect as a STRICT xfail: while
the defect exists the test fails (expected); the day the defect is fixed the test passes, strict xfail turns that into an error, and the marker (and the audit note) must be removed.
"""

from __future__ import annotations

import statistics
from functools import lru_cache

import pytest

from agri_twin.application.interactive_simulation import InteractiveSimulationService, SimulationApiError
from agri_twin.application.scenarios import ScenarioEvent
from agri_twin.domain.crop_growth import CropGrowthEngine
from agri_twin.domain.water_balance import IRRIGATION_EFFICIENCY
from agri_twin.infrastructure.energyplus_timeline import find_energyplus

START = "2026-02-27T00:00:00+00:00"
HOURS = 72
BASE = {"crop": "tomato", "end_time": "2026-03-12T00:00:00+00:00", "scenario": "BASE_SEASON", "options": {"include_trajectory": True, "compute_trajectory_hash": False}}
MODES = {"outdoor": {"environment": "outdoor"}, "gh": {"environment": "greenhouse"}, "ep": {"environment": "greenhouse", "greenhouse": {"backend": "ENERGYPLUS"}}}
service = InteractiveSimulationService()
needs_energyplus = pytest.mark.skipif(find_energyplus() is None, reason="EnergyPlus is not installed")


def event(kind: str, intensity: float | None = None) -> dict:
    document = {"event_type": kind, "start_simulation_time": START, "duration_hours": HOURS}
    if intensity is not None:
        document["intensity"] = intensity
    return document


@lru_cache(maxsize=None)
def baseline(mode: str) -> dict:
    return service.run_simulation({**BASE, **MODES[mode]}).result.trajectory


@lru_cache(maxsize=None)
def with_event(mode: str, kind: str, intensity: float | None = None) -> dict:
    return service.run_simulation({**BASE, **MODES[mode], "runtime_events": [event(kind, intensity)]}).result.trajectory


def start_index(trajectory: dict) -> int:
    return next(i for i, stamp in enumerate(trajectory["time"]) if stamp >= START)


def delta(mode: str, kind: str, intensity: float | None, name: str) -> list[float]:
    return [b - a for a, b in zip(baseline(mode)[name], with_event(mode, kind, intensity)[name])]


def window(values: list[float]) -> list[float]:
    base = start_index(baseline("outdoor")) + 1  # the step labelled START is the hour BEFORE the event; the event acts on the HOURS steps after it
    return values[base:base + HOURS]


# ---- invariants that hold today ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["outdoor", "gh"])
@pytest.mark.parametrize("kind, intensity", [("HEAT_WAVE", 8), ("COLD_WAVE", 8), ("HIGH_RADIATION", 1.5), ("LOW_RADIATION", 0.5), ("RAIN", 5), ("WIND", 3), ("IRRIGATION", 2)])
def test_an_event_never_changes_anything_before_it_starts(mode, kind, intensity):
    base, changed = baseline(mode), with_event(mode, kind, intensity)
    first = start_index(base)
    for name, series in changed.items():
        if name == "crop_stage":
            continue
        assert series[:first] == base[name][:first], f"{name} changed before the event started"


def test_a_heat_wave_adds_exactly_its_offset_to_the_outdoor_temperature_and_only_inside_its_window():
    changes = delta("outdoor", "HEAT_WAVE", 8, "temperature_c")
    first = start_index(baseline("outdoor")) + 1
    assert all(abs(value - 8.0) < 1e-9 for value in changes[first:first + HOURS])
    assert all(value == 0.0 for value in changes[:first]) and all(value == 0.0 for value in changes[first + HOURS:])


def test_a_cold_wave_lowers_the_temperature_and_raises_cold_stress_and_frost_damage():
    assert all(abs(value + 8.0) < 1e-9 for value in window(delta("outdoor", "COLD_WAVE", 8, "temperature_c")))
    assert max(delta("outdoor", "COLD_WAVE", 8, "cold_stress")) > 0.3 and max(delta("outdoor", "COLD_WAVE", 8, "frost_damage")) > 0.1


def test_the_simplified_greenhouse_answers_a_temperature_wave_like_a_greenhouse_with_a_thermostat():
    # it is the same greenhouse as the EnergyPlus one: the default heater holds its minimum, so the interior follows the outdoor change only in part and the heating energy moves
    assert statistics.mean(window(delta("gh", "HEAT_WAVE", 8, "outdoor_temperature_c"))) == pytest.approx(8.0, abs=1e-9)
    assert 1.0 < statistics.mean(window(delta("gh", "HEAT_WAVE", 8, "temperature_c"))) < 8.0
    assert statistics.mean(window(delta("gh", "HEAT_WAVE", 8, "greenhouse_heating_kw"))) < -3.0
    assert statistics.mean(window(delta("gh", "COLD_WAVE", 8, "greenhouse_heating_kw"))) > 3.0


@pytest.mark.parametrize("mode", ["outdoor", "gh"])
def test_radiation_events_scale_the_radiation_exactly_and_move_et0_and_biomass_the_same_way(mode):
    base = window(baseline(mode)["radiation_w_m2"])
    up, down = window(with_event(mode, "HIGH_RADIATION", 1.5)["radiation_w_m2"]), window(with_event(mode, "LOW_RADIATION", 0.5)["radiation_w_m2"])
    assert all(abs(u - 1.5 * b) < 1e-6 and abs(d - 0.5 * b) < 1e-6 for u, d, b in zip(up, down, base))
    assert sum(window(delta(mode, "HIGH_RADIATION", 1.5, "et0_mm"))) > 0 > sum(window(delta(mode, "LOW_RADIATION", 0.5, "et0_mm")))
    assert delta(mode, "HIGH_RADIATION", 1.5, "biomass_total_g_m2")[-1] > 0 > delta(mode, "LOW_RADIATION", 0.5, "biomass_total_g_m2")[-1]


def test_shading_removes_exactly_its_share_of_the_indoor_radiation_and_reports_the_actuator():
    base, shaded = window(baseline("gh")["radiation_w_m2"]), window(with_event("gh", "SHADING", 0.6)["radiation_w_m2"])
    assert all(abs(s - 0.4 * b) < 1e-6 for s, b in zip(shaded, base))
    assert statistics.mean(window(with_event("gh", "SHADING", 0.6)["greenhouse_shading_fraction"])) > 0.55


def test_rain_is_the_forcing_rate_outdoors_and_never_reaches_an_indoor_crop():
    assert all(abs(value - 5.0) < 1e-9 for value in window(with_event("outdoor", "RAIN", 5)["precipitation_mm"]))
    assert max(with_event("gh", "RAIN", 5)["precipitation_mm"]) == 0.0


def test_actuator_events_are_refused_outdoors_and_co2_is_refused_by_energyplus():
    with pytest.raises(SimulationApiError):
        service.run_simulation({**BASE, **MODES["outdoor"], "runtime_events": [event("SHADING", 0.5)]})
    if find_energyplus() is not None:
        with pytest.raises(SimulationApiError):
            service.run_simulation({**BASE, **MODES["ep"], "runtime_events": [event("CO2", 0.8)]})


# ---- the audited irrigation defect, fixed ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["outdoor", "gh"])
def test_a_user_irrigation_replaces_the_scheduled_one_for_its_window_only(mode):
    base, changed = baseline(mode)["irrigation_mm"], with_event(mode, "IRRIGATION", 2)["irrigation_mm"]
    first = start_index(baseline(mode)) + 1  # the step that STARTS at the event start is labelled one hour later, like the first forced step
    applied = 2.0 * IRRIGATION_EFFICIENCY["drip"]
    assert all(abs(value - applied) < 1e-9 for value in changed[first:first + HOURS])
    assert changed[:first] == base[:first] and changed[first + HOURS:] == base[first + HOURS:]
    assert sum(changed) > sum(base)


def test_the_last_active_irrigation_event_wins_and_a_lone_event_is_unchanged():
    from datetime import datetime, timezone
    from agri_twin.application.scenarios import ScenarioRunner

    t0, t1 = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc)
    scheduled, user = ScenarioEvent("a", "irrigation", t0, t1, 0.4, {"amount_mm": 0.4}), ScenarioEvent("b", "irrigation", t0, t1, 2.0, {"amount_mm": 2.0})
    assert ScenarioRunner._irrigation([scheduled, user]).amount_mm == 2.0
    assert ScenarioRunner._irrigation([user, scheduled]).amount_mm == 0.4  # order is the rule: later events override earlier ones
    assert ScenarioRunner._irrigation([scheduled]).amount_mm == 0.4 and ScenarioRunner._irrigation([]) is None


@needs_energyplus
def test_energyplus_responds_physically_to_shading_and_to_open_vents_with_the_heater_compensating():
    shade, vents = with_event("ep", "SHADING", 0.6), with_event("ep", "VENTILATION", 1.0)
    base = baseline("ep")
    assert statistics.mean(window([b - a for a, b in zip(base["temperature_c"], shade["temperature_c"])])) < -1.0
    assert statistics.mean(window([b - a for a, b in zip(base["temperature_c"], vents["temperature_c"])])) < -1.0
    assert statistics.mean(window([b - a for a, b in zip(base["greenhouse_heating_kw"], vents["greenhouse_heating_kw"])])) > 5.0


# ---- the simplified greenhouse is the same greenhouse as the EnergyPlus one (audit findings 2 and 3, fixed) -------------------------------------------------
def test_the_simplified_greenhouse_is_warmer_than_outside_at_midday_like_a_greenhouse():
    tr = baseline("gh")
    hours = [int(stamp[11:13]) for stamp in tr["time"]]
    midday = statistics.mean(i - o for i, o, h in zip(tr["temperature_c"], tr["outdoor_temperature_c"], hours) if 10 <= h <= 16)
    assert 3.0 < midday < 10.0  # the historical 1 m2 model gave -0.02 K; EnergyPlus gives about +6.5 K in this window
    assert min(tr["temperature_c"]) >= 11.9  # the default thermostat (12 degC) holds the minimum, as in EnergyPlus


def test_in_the_simplified_greenhouse_radiation_shading_and_open_vents_move_the_interior_the_way_they_do_in_reality():
    # (more radiation changes the winter MEAN very little here: the heater backs off and the vents open earlier; EnergyPlus +0.8 K, this model -0.1 K, see the audit)
    assert statistics.mean(window(delta("gh", "LOW_RADIATION", 0.5, "temperature_c"))) < -0.3
    assert statistics.mean(window(delta("gh", "HIGH_RADIATION", 1.5, "greenhouse_heating_kw"))) < 0.0
    assert statistics.mean(window(delta("gh", "SHADING", 0.6, "temperature_c"))) < -0.5  # the historical model: -0.05 K
    assert statistics.mean(window(delta("gh", "VENTILATION", 1.0, "temperature_c"))) < -1.0  # historical: -0.02 K
    assert statistics.mean(window(delta("gh", "VENTILATION", 1.0, "greenhouse_heating_kw"))) > 5.0  # open vents in winter: the heater compensates
    assert statistics.mean(window(with_event("gh", "VENTILATION", 1.0)["greenhouse_ventilation_fraction"])) > 0.9


def test_a_full_ventilation_command_is_the_whole_vent_capacity_in_both_greenhouse_models():
    from agri_twin.application.greenhouse_backend import parse_greenhouse_backend, simplified_configuration

    configuration = simplified_configuration(parse_greenhouse_backend(None, "greenhouse"))[0]
    assert configuration.vent_command_fraction and configuration.passive_vent_ach == 30.0  # the capacity EnergyPlus uses for the same command


@needs_energyplus
def test_the_two_greenhouse_models_agree_on_the_standard_window_within_stated_tolerances():
    lumped, detailed = baseline("gh"), baseline("ep")
    hours = [int(stamp[11:13]) for stamp in lumped["time"]]
    rmse = statistics.mean((a - b) ** 2 for a, b in zip(lumped["temperature_c"], detailed["temperature_c"])) ** 0.5
    midday = lambda tr: statistics.mean(i - o for i, o, h in zip(tr["temperature_c"], tr["outdoor_temperature_c"], hours) if 10 <= h <= 16)
    assert rmse < 3.0 and abs(midday(lumped) - midday(detailed)) < 2.5
    assert abs(statistics.mean(lumped["radiation_w_m2"]) / statistics.mean(detailed["radiation_w_m2"]) - 1.0) < 0.08
    assert abs(sum(lumped["greenhouse_heating_kw"]) / sum(detailed["greenhouse_heating_kw"]) - 1.0) < 0.35
    change = lambda mode, kind, intensity: statistics.mean(window(delta(mode, kind, intensity, "temperature_c")))
    for event_kind, intensity in (("SHADING", 0.6), ("VENTILATION", 1.0), ("LOW_RADIATION", 0.5)):
        assert change("gh", event_kind, intensity) * change("ep", event_kind, intensity) > 0, event_kind  # both models move the interior the same way
        assert abs(change("gh", event_kind, intensity) - change("ep", event_kind, intensity)) < 1.5, event_kind  # and by a similar amount
    assert abs(change("gh", "HIGH_RADIATION", 1.5) - change("ep", "HIGH_RADIATION", 1.5)) < 1.5


# ---- audited defects still open, stated as what a correct model would do (strict xfail) -------------------------------------------------------------
def test_a_heat_wave_does_not_raise_the_vapour_pressure_of_the_outdoor_air():
    assert statistics.mean(window(delta("outdoor", "HEAT_WAVE", 8, "relative_humidity_pct"))) < -10.0  # keeping the dew point makes the air drier (audit finding 4, fixed)


def test_a_cold_wave_keeps_the_dew_point_so_the_air_gets_more_humid_in_relative_terms():
    assert statistics.mean(window(delta("outdoor", "COLD_WAVE", 8, "relative_humidity_pct"))) > 5.0


@pytest.mark.xfail(strict=True, reason="audit finding 5, documented not fixed: ET0 is Hargreaves-Samani with a fixed temperature range, so it has no wind or VPD term; the WIND event declares that only EnergyPlus uses wind")
def test_wind_changes_the_reference_evapotranspiration():
    assert any(abs(value) > 1e-9 for value in delta("outdoor", "WIND", 3, "et0_mm"))


def test_the_wind_event_says_it_only_acts_through_energyplus():
    from agri_twin.application.runtime_events import SPEC_INDEX
    spec = SPEC_INDEX["WIND"]
    assert spec.affected_variables == ("temperature_c",) and "only the EnergyPlus backend uses wind" in spec.summary


@pytest.mark.xfail(strict=True, reason="audit finding 6: the CO2 response is min(1, CO2/420), so enrichment cannot increase growth")
def test_co2_enrichment_can_raise_the_growth_response():
    assert CropGrowthEngine.co2_response(800.0) > CropGrowthEngine.co2_response(420.0)


def test_an_event_acts_for_exactly_its_duration():
    affected = [d for d in delta("outdoor", "HEAT_WAVE", 8, "temperature_c") if abs(d) > 1e-9]
    assert len(affected) == HOURS  # audit finding 10, fixed


def test_forcing_and_actuator_events_cover_the_same_steps():
    def steps(mode, kind, value, variable):
        return [i for i, d in enumerate(delta(mode, kind, value, variable)) if abs(d) > 1e-9]
    forcing, actuator = steps("gh", "HEAT_WAVE", 8, "outdoor_temperature_c"), steps("gh", "SHADING", 0.6, "greenhouse_shading_fraction")
    assert len(forcing) == len(actuator) == HOURS and forcing[0] == actuator[0]


def test_the_co2_event_declares_that_enrichment_does_not_raise_growth():
    from agri_twin.application.runtime_events import SPEC_INDEX
    assert "does not raise growth" in SPEC_INDEX["CO2"].summary


def test_temperature_waves_keep_the_vapour_pressure_only_for_runtime_events():
    from datetime import datetime, timezone
    from agri_twin.application.scenarios import HALF_OPEN_INTERVAL, HOLD_DEW_POINT, ScenarioEvent, _ScenarioWeatherProvider
    from agri_twin.domain.greenhouse import saturation_vapour_pressure_kpa
    from agri_twin.domain.models import WeatherState

    t0, t1, now = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 3, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)
    base = WeatherState(10.0, 70.0, 200.0, 2.0, 0.0, 0.0, 1013.0)

    class Fixed:
        def get(self, timestamp):
            return base

    def humidity(parameters):
        scenario = type("S", (), {"events": (ScenarioEvent("w", "heat_wave", t0, t1, 8.0, parameters),), "base_weather": base})()
        return _ScenarioWeatherProvider(scenario, Fixed()).get(now)

    historical, runtime = humidity({"temperature_offset_c": 8.0}), humidity({"temperature_offset_c": 8.0, HALF_OPEN_INTERVAL: 1.0, HOLD_DEW_POINT: 1.0})
    assert historical.relative_humidity_pct == 70.0 and historical.temperature_c == runtime.temperature_c == 18.0
    kept = runtime.relative_humidity_pct / 100.0 * saturation_vapour_pressure_kpa(18.0)
    assert kept == pytest.approx(0.7 * saturation_vapour_pressure_kpa(10.0)) and runtime.relative_humidity_pct < 70.0
