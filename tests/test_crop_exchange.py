"""Crop -> greenhouse exchange in the simplified greenhouse (transpiration, latent/sensible heat, CO2 uptake): optional, deterministic, a function of carried state only."""

from __future__ import annotations

import statistics

import pytest

from agri_twin.application.greenhouse_backend import GreenhouseBackendError, describe, parse_greenhouse_backend
from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import InteractiveSimulationService

service = InteractiveSimulationService()
WINDOW = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-04-12T00:00:00+00:00", "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
ON = {"backend": "SIMPLIFIED", "crop_exchange": True}


def run(greenhouse=None, **extra):
    document = {**WINDOW, **extra}
    if greenhouse is not None:
        document["greenhouse"] = greenhouse
    response = service.run_simulation(document)
    assert response.execution_status.value == "COMPLETED", response.errors
    return response


def test_the_exchange_is_off_by_default_and_absent_from_requests_that_do_not_use_it():
    assert "crop_exchange" not in parse_greenhouse_backend(None, "greenhouse").to_dict()
    assert "crop_exchange" not in parse_greenhouse_backend({"backend": "SIMPLIFIED"}, "greenhouse").to_dict()
    assert parse_greenhouse_backend(ON, "greenhouse").to_dict()["crop_exchange"] is True
    assert run().result.trajectory_hash == run({"backend": "SIMPLIFIED", "crop_exchange": False}).result.trajectory_hash


@pytest.mark.parametrize("greenhouse, environment, path", [({"backend": "SIMPLIFIED", "crop_exchange": "yes"}, "greenhouse", "greenhouse.crop_exchange"),
                                                            ({"backend": "SIMPLIFIED", "crop_exchange": True}, "outdoor", "greenhouse.crop_exchange")])
def test_invalid_exchange_requests_are_rejected_with_a_path(greenhouse, environment, path):
    with pytest.raises(GreenhouseBackendError) as caught:
        parse_greenhouse_backend(greenhouse, environment)
    assert caught.value.path == path


def test_energyplus_cannot_carry_the_exchange(monkeypatch):
    import agri_twin.application.greenhouse_backend as module
    monkeypatch.setattr(module, "require_energyplus", lambda: object())
    with pytest.raises(GreenhouseBackendError) as caught:
        parse_greenhouse_backend({"backend": "ENERGYPLUS", "crop_exchange": True}, "greenhouse")
    assert caught.value.path == "greenhouse.crop_exchange" and "precomputed" in caught.value.message


def test_the_description_states_what_is_and_is_not_modelled():
    text = " ".join(describe(parse_greenhouse_backend(ON, "greenhouse"))["limits"])
    assert "respiration" in text and "none is assumed" in text and "not calibrated" in text and "forecast" in text
    assert "no crop feedback" not in text
    assert "no crop feedback" in " ".join(describe(parse_greenhouse_backend({"backend": "SIMPLIFIED"}, "greenhouse"))["limits"])


def test_the_crop_humidifies_the_air_and_draws_down_the_co2_it_grows_on():
    without, with_crop = run().result.trajectory, run(ON).result.trajectory
    assert min(without["co2_ppm"]) == pytest.approx(420.0) and min(with_crop["co2_ppm"]) < 400.0  # uptake, no enrichment and no respiration modelled
    assert statistics.mean(with_crop["relative_humidity_pct"]) > statistics.mean(without["relative_humidity_pct"]) + 1.0
    assert all(0.0 <= value <= 100.0 for value in with_crop["relative_humidity_pct"]) and all(value >= 0.0 for value in with_crop["co2_ppm"])
    assert with_crop["temperature_c"] != without["temperature_c"]  # latent heat of transpiration cools, leaf sensible heat warms


def test_the_exchange_is_deterministic_and_part_of_the_request_identity():
    first, second, plain = run(ON), run(ON), run()
    assert first.result.trajectory_hash == second.result.trajectory_hash != plain.result.trajectory_hash
    assert first.hashes["configuration_hash"] != plain.hashes["configuration_hash"] and first.hashes["request_hash"] != plain.hashes["request_hash"]


def test_what_if_equals_the_continuous_run_with_the_exchange_on():
    plain = run(ON)
    event = {"event_type": "SHADING", "start_simulation_time": "2026-04-05T00:00:00+00:00", "duration_hours": 24, "intensity": 0.5}
    request = {**{k: v for k, v in WINDOW.items() if k != "options"}, "greenhouse": ON}
    result = InteractiveRuntimeService().what_if({"request": request, "checkpoint_time": "2026-04-02T00:00:00+00:00", "events": [event]})
    prefix, baseline = result["prefix"]["result"]["trajectory"], result["branches"]["baseline"]["response"]["result"]["trajectory"]
    keep = [index for index, time in enumerate(baseline["time"]) if time > prefix["time"][-1]]
    for name in ("temperature_c", "relative_humidity_pct", "co2_ppm", "biomass_total_g_m2", "soil_water_vwc_m3_m3"):
        assert prefix[name] + [baseline[name][index] for index in keep] == plain.result.trajectory[name], name
