"""FAO-56 Penman-Monteith reference evapotranspiration, checked against the paper's own worked examples, and its opt-in use in the interactive simulation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import InteractiveSimulationService, SimulationApiError, canonicalize_request
from agri_twin.application.model_options import ModelOptionsError, parse_model_options
from agri_twin.domain.evapotranspiration import (
    Et0Site,
    PenmanMonteithEt0,
    elevation_from_pressure_m,
    extraterrestrial_radiation_mj_m2,
    penman_monteith_hourly_mm,
    saturation_vapour_pressure_kpa,
    wind_at_2_m,
)
from agri_twin.domain.models import WeatherState

service = InteractiveSimulationService()
BASE = {"crop": "tomato", "environment": "outdoor", "end_time": "2026-03-20T00:00:00+00:00", "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
PM = {"et0_method": "PENMAN_MONTEITH_FAO56"}


def run(**extra):
    response = service.run_simulation({**BASE, **extra})
    assert response.execution_status.value == "COMPLETED", response.errors
    return response


# ---- the equation against the paper ---------------------------------------------------------------------------------------------------------
def test_the_hourly_equation_reproduces_fao56_example_19():
    # FAO-56 example 19: T 38 C, RH 52 %, u2 3.3 m/s, Rn 1.759 and G 0.176 MJ m-2 h-1, P 101.3 kPa -> ET0 = 0.63 mm/h
    assert penman_monteith_hourly_mm(38.0, 0.52 * saturation_vapour_pressure_kpa(38.0), 3.3, 1.759, 0.176, 101.3) == pytest.approx(0.63, abs=0.005)


def test_the_hourly_extraterrestrial_radiation_adds_up_to_the_daily_value_of_fao56_example_8():
    site = Et0Site(-20.0, 0.0)  # 3 September at 20 S: Ra = 32.2 MJ m-2 day-1
    day = sum(extraterrestrial_radiation_mj_m2(site, datetime(2026, 9, 3, hour, 30, tzinfo=timezone.utc)) for hour in range(24))
    assert day == pytest.approx(32.2, abs=0.3)
    assert extraterrestrial_radiation_mj_m2(site, datetime(2026, 9, 3, 0, 30, tzinfo=timezone.utc)) == 0.0  # the sun is down
    assert extraterrestrial_radiation_mj_m2(Et0Site(80.0, 0.0), datetime(2026, 12, 21, 12, 30, tzinfo=timezone.utc)) == 0.0  # polar night


def test_wind_is_converted_to_two_metres_and_the_elevation_follows_the_pressure():
    assert wind_at_2_m(10.0, 10.0) == pytest.approx(7.48, abs=0.01) and wind_at_2_m(3.0, 2.0) == 3.0
    assert elevation_from_pressure_m(101.3) == pytest.approx(0.0, abs=1e-9)
    assert elevation_from_pressure_m(101.3 * ((293.0 - 0.0065 * 1800.0) / 293.0) ** 5.26) == pytest.approx(1800.0, abs=1e-6)  # inverse of FAO-56 eq. 7


def test_wind_and_dryness_raise_the_evaporative_demand_and_the_result_is_never_negative():
    site, when = Et0Site(37.0, -1.0), datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
    et0 = PenmanMonteithEt0(site, 2.0, lambda label: 800.0)

    def weather(wind, humidity):
        return WeatherState(30.0, humidity, 800.0, wind, 0.0, 0.0, 1013.0)

    calm, windy, dry = et0.mm(weather(0.5, 50.0), when, 3600.0), et0.mm(weather(5.0, 50.0), when, 3600.0), et0.mm(weather(5.0, 20.0), when, 3600.0)
    assert 0.0 < calm < windy < dry and 0.2 < windy < 1.2  # mm per hour at midday in summer
    assert et0.mm(WeatherState(-5.0, 100.0, 0.0, 0.0, 0.0, 0.0, 1013.0), when.replace(hour=2), 3600.0) >= 0.0


def test_at_night_the_sky_clearness_comes_from_two_hours_before_the_last_sunlit_hour():
    asked = []
    et0 = PenmanMonteithEt0(Et0Site(37.0, -1.0), 2.0, lambda label: asked.append(label) or 400.0)
    ratio = et0.cloudiness(datetime(2026, 7, 2, 3, tzinfo=timezone.utc), 0.0, 1.0)
    assert 0.3 <= ratio <= 1.0 and asked and max(asked) < datetime(2026, 7, 1, 22, tzinfo=timezone.utc) and min(asked) > datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


# ---- the option ------------------------------------------------------------------------------------------------------------------------------
def test_the_default_request_has_no_block_and_the_default_method_is_unchanged():
    assert "model_options" not in canonicalize_request(BASE).to_dict()
    assert parse_model_options({"et0_method": "HARGREAVES_HISTORICAL"}, "outdoor") is None
    assert run().result.trajectory_hash == run(model_options={"et0_method": "HARGREAVES_HISTORICAL"}).result.trajectory_hash


@pytest.mark.parametrize("document, path", [({"et0_method": "THORNTHWAITE"}, "model_options.et0_method"), ({"x": 1}, "model_options.x"), ({"indoor_wind_m_s": -1}, "model_options.indoor_wind_m_s"),
                                            ({"et0_method": "PENMAN_MONTEITH_FAO56", "indoor_wind_m_s": 0.3}, "model_options.indoor_wind_m_s"), ("pm", "model_options")])
def test_invalid_options_are_rejected_with_a_path(document, path):
    with pytest.raises(ModelOptionsError) as caught:
        parse_model_options(document, "outdoor")
    assert caught.value.path == path


def test_a_plot_without_coordinates_cannot_use_penman_monteith_without_the_weather_archive(monkeypatch, tmp_path):
    import json

    import agri_twin.application.model_options as options_module

    document = json.loads(options_module.FARM_CONFIG.read_text(encoding="utf-8"))
    document["plots"] = [plot for plot in document["plots"] if plot["crop_key"] != "lettuce"]
    farm = tmp_path / "farm.json"
    farm.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(options_module, "FARM_CONFIG", farm)
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({"crop": "lettuce", "model_options": PM})
    assert "coordinates" in caught.value.errors[0].message and caught.value.errors[0].path == "model_options.et0_method"
    assert canonicalize_request({"crop": "tomato", "model_options": PM}).model_options is not None


def test_the_typical_plots_give_every_crop_a_site_for_penman_monteith():
    for crop in ("lettuce", "peach", "apple", "tomato", "pepper", "grape", "plum"):
        assert canonicalize_request({"crop": crop, "model_options": PM}).model_options is not None


def test_penman_monteith_changes_the_evapotranspiration_and_is_part_of_the_identity():
    historical, fao = run(), run(model_options=PM)
    assert sum(fao.result.trajectory["et0_mm"]) < sum(historical.result.trajectory["et0_mm"]) and fao.result.trajectory["et0_mm"] != historical.result.trajectory["et0_mm"]
    assert fao.hashes["request_hash"] != historical.hashes["request_hash"] and fao.result.trajectory_hash == run(model_options=PM).result.trajectory_hash


def test_with_penman_monteith_wind_changes_the_evapotranspiration_and_the_default_does_not():
    event = [{"event_type": "WIND", "intensity": 3, "start_simulation_time": "2026-03-01T00:00:00+00:00", "duration_hours": 48}]
    base, windy = run(model_options=PM).result.trajectory["et0_mm"], run(model_options=PM, runtime_events=event).result.trajectory["et0_mm"]
    assert any(abs(a - b) > 1e-9 for a, b in zip(base, windy))
    assert run().result.trajectory["et0_mm"] == run(runtime_events=event).result.trajectory["et0_mm"]


def test_inside_a_greenhouse_the_air_speed_is_the_users_and_still_air_by_default():
    greenhouse = {"environment": "greenhouse"}
    still = sum(run(**greenhouse, model_options=PM).result.trajectory["et0_mm"])
    moving = sum(run(**greenhouse, model_options={**PM, "indoor_wind_m_s": 0.5}).result.trajectory["et0_mm"])
    assert moving > still > 0.0


def test_what_if_equals_the_continuous_run_with_penman_monteith():
    plain = run(model_options=PM)
    event = {"event_type": "HEAT_WAVE", "start_simulation_time": "2026-03-10T00:00:00+00:00", "duration_hours": 24, "intensity": 5}
    request = {**{k: v for k, v in BASE.items() if k != "options"}, "model_options": PM}
    result = InteractiveRuntimeService().what_if({"request": request, "checkpoint_time": "2026-03-05T00:00:00+00:00", "events": [event]})
    prefix, baseline = result["prefix"]["result"]["trajectory"], result["branches"]["baseline"]["response"]["result"]["trajectory"]
    keep = [index for index, time in enumerate(baseline["time"]) if time > prefix["time"][-1]]
    for name in ("et0_mm", "soil_water_vwc_m3_m3", "transpiration_mm", "biomass_total_g_m2"):
        assert prefix[name] + [baseline[name][index] for index in keep] == plain.result.trajectory[name], name
