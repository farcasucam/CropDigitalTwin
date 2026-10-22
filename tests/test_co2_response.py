"""Optional growth response to CO2 that lets enrichment raise growth: a cited value, opt-in, never a silent change of the historical response."""

from __future__ import annotations

import json
import math

import pytest

from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import InteractiveSimulationService, canonicalize_request
from agri_twin.application.model_options import CO2_FILE, ModelOptionsError, co2_constants, parse_model_options
from agri_twin.domain.co2_response import Co2ResponseError, LogarithmicCo2Response
from agri_twin.domain.crop_growth import CropGrowthEngine
from agri_twin.domain.models import CropGrowthState
from agri_twin.domain.radiation_growth import RadiationGrowthEngine, RadiationGrowthError

service = InteractiveSimulationService()
LOG = {"co2_response": "LOG_RELATIVE_GAIN"}
BASE = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-04-12T00:00:00+00:00", "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
ENRICH = [{"event_type": "CO2", "intensity": 1.0, "start_simulation_time": "2026-03-01T00:00:00+00:00", "duration_hours": 600}]
ENRICH_LATER = [{"event_type": "CO2", "intensity": 1.0, "start_simulation_time": "2026-03-20T00:00:00+00:00", "duration_hours": 300}]


def run(**extra):
    response = service.run_simulation({**BASE, **extra})
    assert response.execution_status.value == "COMPLETED", response.errors
    return response


# ---- the function and its parameter ------------------------------------------------------------------------------------------------------------
def test_the_response_is_one_at_the_reference_and_gains_the_cited_share_when_the_concentration_doubles():
    response = LogarithmicCo2Response(0.33)
    assert response(420.0) == 1.0 and response(840.0) == pytest.approx(1.33) and response(0.0) == 0.0
    assert response(300.0) < 1.0 < response(600.0) < response(1000.0) and response(1e-9) == 0.0
    assert response(210.0) == pytest.approx(1.0 - 0.33)  # symmetric in the logarithm


@pytest.mark.parametrize("gain", [-0.1, 1.5, math.nan])
def test_an_invalid_gain_is_rejected(gain):
    with pytest.raises(Co2ResponseError):
        LogarithmicCo2Response(gain)


def test_the_parameter_file_carries_its_citation_status_and_assumptions():
    constants = json.loads(CO2_FILE.read_text(encoding="utf-8"))
    assert constants["status"] == "LITERATURE_GENERIC_C3_NOT_CROP_SPECIFIC" and constants["source"]["doi"] == "10.2134/agronj1983.00021962007500050014x"
    low, high = constants["confidence_interval_99_9"]
    assert low <= constants["relative_gain_per_doubling"] <= high and "Kimball" in constants["source"]["citation"] and constants["assumptions_not_in_the_source"]
    assert co2_constants()["reference_co2_ppm"] == CropGrowthEngine.CO2_REFERENCE_PPM  # one reference for both responses


def test_the_radiation_engine_accepts_an_enhancement_but_never_a_limitation_above_one():
    engine = RadiationGrowthEngine()
    with pytest.raises(RadiationGrowthError):
        engine.advance(CropGrowthState.__new__(CropGrowthState), None, 3600.0, 1.2)  # rejected before anything is read
    with pytest.raises(RadiationGrowthError):
        engine.advance(CropGrowthState.__new__(CropGrowthState), None, 3600.0, 1.0, -0.1)


# ---- the option --------------------------------------------------------------------------------------------------------------------------------
def test_the_default_is_unchanged_and_carries_no_block():
    assert "model_options" not in canonicalize_request(BASE).to_dict()
    assert parse_model_options({"co2_response": "HISTORICAL_CAPPED"}, "greenhouse") is None
    assert run().result.trajectory_hash == run(model_options={"co2_response": "HISTORICAL_CAPPED"}).result.trajectory_hash


@pytest.mark.parametrize("document, path", [({"co2_response": "MAGIC"}, "model_options.co2_response"), ({"co2_gain_per_doubling": 0.2}, "model_options.co2_gain_per_doubling"),
                                            ({**LOG, "co2_gain_per_doubling": 2}, "model_options.co2_gain_per_doubling"), ({**LOG, "co2_gain_per_doubling": True}, "model_options.co2_gain_per_doubling")])
def test_invalid_co2_options_are_rejected_with_a_path(document, path):
    with pytest.raises(ModelOptionsError) as caught:
        parse_model_options(document, "greenhouse")
    assert caught.value.path == path


def test_enrichment_raises_growth_only_when_the_response_is_chosen():
    default_plain, default_rich = run().result.trajectory, run(runtime_events=ENRICH).result.trajectory
    log_plain, log_rich = run(model_options=LOG).result.trajectory, run(model_options=LOG, runtime_events=ENRICH).result.trajectory
    assert default_rich["co2_ppm"] != default_plain["co2_ppm"] and default_rich["biomass_total_g_m2"] == default_plain["biomass_total_g_m2"]  # CO2 rises, growth does not
    assert max(log_rich["co2_ppm"]) > 500.0 and log_rich["biomass_total_g_m2"][-1] > log_plain["biomass_total_g_m2"][-1]
    assert log_plain["biomass_total_g_m2"][-1] == pytest.approx(default_plain["biomass_total_g_m2"][-1], rel=0.2)


def test_a_larger_user_gain_gives_more_growth_and_the_gain_is_part_of_the_identity():
    low = run(model_options={**LOG, "co2_gain_per_doubling": 0.1}, runtime_events=ENRICH)
    high = run(model_options={**LOG, "co2_gain_per_doubling": 0.5}, runtime_events=ENRICH)
    assert high.result.trajectory["biomass_total_g_m2"][-1] > low.result.trajectory["biomass_total_g_m2"][-1]
    assert low.hashes["request_hash"] != high.hashes["request_hash"] and run(model_options=LOG).hashes["request_hash"] != run().hashes["request_hash"]
    assert low.result.trajectory_hash == run(model_options={**LOG, "co2_gain_per_doubling": 0.1}, runtime_events=ENRICH).result.trajectory_hash


def test_the_response_reaches_the_crop_feedback_growth_proxy_too():
    greenhouse = {"backend": "SIMPLIFIED", "crop_exchange": True}
    plain = run(greenhouse=greenhouse, runtime_events=ENRICH).result.trajectory
    gained = run(greenhouse=greenhouse, model_options=LOG, runtime_events=ENRICH).result.trajectory
    assert gained["biomass_total_g_m2"][-1] > plain["biomass_total_g_m2"][-1] and gained["co2_ppm"] != plain["co2_ppm"]


def test_what_if_equals_the_continuous_run_with_the_logarithmic_response():
    plain = run(model_options=LOG)
    request = {**{k: v for k, v in BASE.items() if k != "options"}, "model_options": LOG}
    result = InteractiveRuntimeService().what_if({"request": request, "checkpoint_time": "2026-03-15T00:00:00+00:00", "events": ENRICH_LATER})
    prefix, baseline = result["prefix"]["result"]["trajectory"], result["branches"]["baseline"]["response"]["result"]["trajectory"]
    keep = [index for index, time in enumerate(baseline["time"]) if time > prefix["time"][-1]]
    for name in ("co2_ppm", "biomass_total_g_m2", "leaf_area_index"):
        assert prefix[name] + [baseline[name][index] for index in keep] == plain.result.trajectory[name], name
    intervention = result["branches"]["intervention"]["response"]["result"]["trajectory"]
    assert intervention["biomass_total_g_m2"][-1] > baseline["biomass_total_g_m2"][-1]  # the enrichment branch grows more
