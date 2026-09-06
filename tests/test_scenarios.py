from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import (
    Scenario,
    ScenarioError,
    ScenarioEvent,
    ScenarioKind,
    ScenarioRunner,
    compare_scenarios,
    sweep_scenarios,
)
from agri_twin.domain import CropGrowthState, SoilState
from agri_twin.domain.calibration import DatasetRole
from agri_twin.domain.models import WeatherState


T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def weather(**changes):
    values = dict(temperature_c=24, relative_humidity_pct=70, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def scenario(events=(), mode="outdoor", vwc=0.25, nutrient=200):
    crop = CropGrowthState(T0, "tomato", "RAF", "establishment", leaf_area_index=1, nutrient_reserve_kg_ha=200, nutrient_available_kg_ha=nutrient)
    return Scenario("test", "synthetic", "controlled synthetic scenario", "tomato", "RAF", T0, T0 + timedelta(days=3), 86400, ScenarioKind.SYNTHETIC, crop, SoilState(vwc, 20, 0.32, 0.10, 20, 0), weather(), mode, tuple(events), labels=("SYNTHETIC SCENARIO", "NOT SCIENTIFIC VALIDATION"))


def event(event_type, start=0, days=1, intensity=0, **parameters):
    return ScenarioEvent(event_type, event_type, T0 + timedelta(days=start), T0 + timedelta(days=start + days), intensity, parameters)


def run(value):
    return ScenarioRunner().run(value)


def test_scenario_creation_and_kind():
    assert scenario().kind == ScenarioKind.SYNTHETIC


def test_scenario_requires_positive_resolution():
    with pytest.raises(ScenarioError):
        Scenario("bad", "bad", "bad", "tomato", None, T0, T0 + timedelta(days=1), 0, ScenarioKind.SYNTHETIC, scenario().initial_crop, scenario().initial_soil, weather())


def test_scenario_crop_matches_initial_state():
    with pytest.raises(ScenarioError):
        Scenario("bad", "bad", "bad", "pepper", None, T0, T0 + timedelta(days=1), 86400, ScenarioKind.SYNTHETIC, scenario().initial_crop, scenario().initial_soil, weather())


def test_event_must_be_inside_period():
    with pytest.raises(ScenarioError):
        scenario((ScenarioEvent("late", "heat", T0 + timedelta(days=5), T0 + timedelta(days=6)),))


def test_configuration_hash_is_stable():
    assert scenario().config_hash() == scenario().config_hash()


def test_event_changes_hash():
    assert scenario().config_hash() != scenario((event("heat_wave", intensity=5),)).config_hash()


def test_baseline_runs_successfully():
    result = run(scenario())

    assert result.status == "SUCCESS"
    assert len(result.snapshots) == 3


def test_baseline_is_reproducible():
    assert run(scenario()) == run(scenario())


def test_hourly_resolution_runs_expected_steps():
    hourly = scenario()
    hourly = __import__("dataclasses").replace(hourly, resolution_seconds=3600, end=T0 + timedelta(days=1))

    assert len(run(hourly).snapshots) == 24


def test_warm_event_changes_temperature_path():
    baseline = run(scenario())
    warm = run(scenario((event("warm", intensity=8),)))

    assert warm.snapshots[0].weather.temperature_c > baseline.snapshots[0].weather.temperature_c


def test_heatwave_accumulates_heat_damage():
    result = run(scenario((event("heat_wave", intensity=12, days=3),)))

    assert result.snapshots[-1].crop.heat_damage > 0


def test_cold_and_frost_events_are_visible():
    cold = run(scenario((event("cold", intensity=5),)))
    frost = run(scenario((event("frost", intensity=-5),)))

    assert cold.snapshots[0].crop.cold_stress > 0
    assert frost.snapshots[0].crop.frost_damage > 0


def test_dry_event_removes_rain():
    wet_base = __import__("dataclasses").replace(scenario(), base_weather=weather(rain_rate_mm_h=10))
    dry = run(__import__("dataclasses").replace(wet_base, events=(event("dry"),)))

    assert dry.snapshots[0].weather.rain_rate_mm_h == 0


def test_wet_event_adds_rain():
    result = run(scenario((event("wet", intensity=10),)))

    assert result.snapshots[0].weather.rain_rate_mm_h == 10


def test_high_vpd_event_changes_humidity():
    result = run(scenario((event("high_vpd", intensity=20, relative_humidity_pct=20),)))

    assert result.snapshots[0].weather.relative_humidity_pct == 20


def test_low_and_high_radiation_events_are_applied():
    low = run(scenario((event("low_radiation", intensity=0.2, radiation_multiplier=0.2),)))
    high = run(scenario((event("high_radiation", intensity=1.5, radiation_multiplier=1.5),)))

    assert low.snapshots[0].weather.solar_radiation_w_m2 < 500
    assert high.snapshots[0].weather.solar_radiation_w_m2 > 500


def test_irrigation_event_changes_soil():
    dry = run(scenario(vwc=0.12, events=(event("irrigation", intensity=100, amount_mm=100),)))

    assert dry.snapshots[0].soil.vwc_m3_m3 > 0.12


def test_fertilization_event_changes_nutrients():
    result = run(scenario(nutrient=0, events=(event("fertilization", intensity=100, amount_kg_ha=100),)))

    assert result.snapshots[0].crop.nutrient_status > 0


def test_recovery_scenario_preserves_event_history():
    result = run(scenario((event("heat_wave", intensity=12), event("warm", start=1, intensity=0))))

    assert len(result.events) == 2


def test_combined_heat_drought_scenario_runs():
    result = run(scenario((event("heat_wave", intensity=12), event("dry"))))

    assert result.status == "SUCCESS"


def test_greenhouse_mode_is_supported():
    result = run(scenario(mode="passive_greenhouse"))

    assert result.snapshots[0].microclimate.indoor_state.radiation_w_m2 < 500


def test_shade_actuator_event_changes_greenhouse_radiation():
    result = run(scenario(mode="actuated_greenhouse", events=(event("shade", intensity=0.5, value=0.5),)))

    assert result.snapshots[0].microclimate.indoor_state.radiation_w_m2 < 500


def test_cooling_actuator_event_changes_greenhouse_temperature():
    hot = __import__("dataclasses").replace(scenario(mode="actuated_greenhouse"), base_weather=weather(temperature_c=38), events=(event("cooling", intensity=5, value=5, maximum=5, capacity=5),))

    assert run(hot).snapshots[0].microclimate.indoor_state.temperature_c < 38


def test_result_exports_validation_dataset():
    dataset = run(scenario()).observation_dataset()

    assert dataset.role == DatasetRole.TEST
    assert dataset.observations


def test_result_contains_config_hash_and_events():
    scenario_value = scenario((event("heat_wave", intensity=10),))
    result = run(scenario_value)

    assert result.config_hash == scenario_value.config_hash() and result.events


def test_comparison_produces_deltas():
    comparison = compare_scenarios([run(scenario()), run(scenario((event("heat_wave", intensity=12),)))])

    assert comparison.scenario_ids == ("test", "test")
    assert "biomass" in comparison.deltas["test"]


def test_comparison_requires_two_results():
    with pytest.raises(ScenarioError):
        compare_scenarios([run(scenario())])


def test_sweep_returns_one_result_per_value():
    result = sweep_scenarios(scenario(), "irrigation", (0, 20, 40))

    assert result.values == (0, 20, 40) and len(result.results) == 3


def test_sweep_is_reproducible():
    assert sweep_scenarios(scenario(), "temperature", (0, 5)) == sweep_scenarios(scenario(), "temperature", (0, 5))


def test_sweep_rejects_empty_or_nonfinite_values():
    with pytest.raises(ScenarioError):
        sweep_scenarios(scenario(), "x", ())
    with pytest.raises(ScenarioError):
        sweep_scenarios(scenario(), "x", (float("nan"),))


def test_simulation_times_are_clock_driven():
    result = run(scenario())

    assert result.snapshots[-1].simulation_time == T0 + timedelta(days=3)


def test_events_have_explicit_duration_and_intensity():
    heat = event("heat_wave", intensity=10, days=2)

    assert heat.end - heat.start == timedelta(days=2) and heat.intensity == 10


def test_labels_identify_synthetic_non_scientific_status():
    assert "SYNTHETIC SCENARIO" in scenario().labels and "NOT SCIENTIFIC VALIDATION" in scenario().labels


def test_normal_radiation_is_unmodified():
    assert run(scenario()).snapshots[0].weather.solar_radiation_w_m2 == 500


def test_stress_result_keeps_persistent_crop_state():
    result = run(scenario((event("frost", intensity=-5),)))

    assert result.snapshots[0].crop.frost_damage > 0
    assert result.snapshots[-1].crop.frost_damage >= 0


def test_scenario_supports_all_kinds():
    for kind in ScenarioKind:
        assert __import__("dataclasses").replace(scenario(), kind=kind).kind == kind


def test_validation_dataset_contains_timestamps():
    dataset = run(scenario()).observation_dataset(("biomass",))

    assert all(observation.timestamp.tzinfo is not None for observation in dataset.observations)