"""Phase 5.41: EnergyPlus as a selectable greenhouse backend (request, timeline engine, service, what-if)."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

import pytest

import agri_twin.application.greenhouse_backend as backend_module
from agri_twin.application.greenhouse_backend import GreenhouseBackendError, parse_greenhouse_backend
from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import (
    ErrorCode,
    InteractiveSimulationService,
    SimulationApiError,
    canonicalize_request,
)
from agri_twin.domain.greenhouse import GreenhouseModelError
from agri_twin.domain.models import WeatherState
from agri_twin.infrastructure.energyplus_timeline import (
    EnergyPlusMicroclimateEngine,
    EnergyPlusTimeline,
    EnergyPlusTimelineError,
    TimelineValue,
    find_energyplus,
)

INSTALL = find_energyplus()
needs_energyplus = pytest.mark.skipif(INSTALL is None or not INSTALL.version.startswith("26.1"), reason="EnergyPlus 26.1 not installed (external dependency)")
BASE = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-02-20T00:00:00+00:00"}
ENERGYPLUS = {"backend": "ENERGYPLUS"}


@pytest.fixture
def energyplus_present(monkeypatch):
    """Pretend EnergyPlus exists so request validation can be tested without running it."""
    monkeypatch.setattr(backend_module, "require_energyplus", lambda: object())


# -- request validation (no EnergyPlus needed) ------------------------------------------------------------
def test_the_default_backend_is_the_lumped_greenhouse_of_the_default_layout():
    plain = canonicalize_request(BASE)
    assert plain.backend == "SIMPLIFIED" and plain.greenhouse is not None  # the simplified model has a geometry now: the same greenhouse EnergyPlus simulates
    assert plain.to_dict()["greenhouse"] == {"backend": "SIMPLIFIED", "layout": {"typology": "MULTITUNEL_CAPILLA"}}
    explicit = canonicalize_request({**BASE, "greenhouse": {"backend": "SIMPLIFIED"}})
    assert explicit.request_hash == plain.request_hash and explicit.resume_hash == plain.resume_hash
    other = canonicalize_request({**BASE, "greenhouse": {"backend": "SIMPLIFIED", "layout": {"typology": "TUNEL"}}})
    assert other.resume_hash != plain.resume_hash  # a checkpoint never resumes under another layout
    assert "greenhouse" not in canonicalize_request({**BASE, "environment": "outdoor"}).to_dict()  # open-field requests are unchanged


def test_energyplus_selection_changes_hashes_and_is_part_of_the_resume_identity(energyplus_present):
    plain = canonicalize_request(BASE)
    selected = canonicalize_request({**BASE, "greenhouse": ENERGYPLUS})
    assert selected.backend == "ENERGYPLUS" and selected.to_dict()["greenhouse"]["layout"] == {"typology": "MULTITUNEL_CAPILLA"}
    assert selected.request_hash != plain.request_hash and selected.resume_hash != plain.resume_hash
    other = canonicalize_request({**BASE, "greenhouse": {**ENERGYPLUS, "layout": {"typology": "TUNEL"}}})
    assert other.resume_hash != selected.resume_hash  # a checkpoint never resumes under another layout


@pytest.mark.parametrize(("document", "path"), [
    ({"backend": "ENERGYPLUS", "layout": {"typology": "PYRAMID"}}, "greenhouse.layout.typology"),
    ({"backend": "ENERGYPLUS", "layout": {"span_m": 9.0, "ridge_rise_m": 99.0}}, "greenhouse.layout"),
    ({"backend": "ENERGYPLUS", "layout": {"colour": "red"}}, "greenhouse.layout.colour"),
    ({"backend": "ENERGYPLUS", "layout": {"n_spans": "three"}}, "greenhouse.layout.n_spans"),
    ({"backend": "SIMPLIFIED", "layout": {"typology": "PYRAMID"}}, "greenhouse.layout.typology"),
    ({"backend": "MAGIC"}, "greenhouse.backend"),
    ({"backend": "ENERGYPLUS", "extra": 1}, "greenhouse.extra"),
])
def test_invalid_backend_requests_are_rejected_with_a_path(energyplus_present, document, path):
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({**BASE, "greenhouse": document})
    assert caught.value.errors[0].path == path


def test_open_field_runs_never_use_energyplus(energyplus_present):
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({"crop": "tomato", "environment": "outdoor", "greenhouse": ENERGYPLUS})
    assert caught.value.errors[0].code is ErrorCode.UNSUPPORTED_ENVIRONMENT


def test_missing_energyplus_is_a_structured_not_ready_error(monkeypatch):
    monkeypatch.setattr(backend_module, "require_energyplus", lambda: (_ for _ in ()).throw(EnergyPlusTimelineError("EnergyPlus was not found")))
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({**BASE, "greenhouse": ENERGYPLUS})
    assert caught.value.errors[0].code is ErrorCode.MODEL_NOT_READY and "not found" in caught.value.errors[0].message


def test_events_the_backend_cannot_model_are_rejected(energyplus_present):
    document = {**BASE, "greenhouse": ENERGYPLUS, "runtime_events": [
        {"event_type": "CO2", "start_simulation_time": "2026-02-18T00:00:00+00:00", "duration_hours": 6, "intensity": 0.5}]}
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({**document, "checkpoint": None})
    assert "CO2" in caught.value.errors[0].message


def test_parse_defaults_to_the_lumped_greenhouse_indoors_and_nothing_outdoors():
    assert parse_greenhouse_backend(None, "greenhouse").backend == "SIMPLIFIED"
    assert parse_greenhouse_backend(None, "outdoor") is None
    with pytest.raises(GreenhouseBackendError):
        parse_greenhouse_backend({"backend": "SIMPLIFIED", "layout": {"typology": "TUNEL"}}, "outdoor")
    with pytest.raises(GreenhouseBackendError):
        parse_greenhouse_backend("ENERGYPLUS", "greenhouse")


# -- timeline engine (no EnergyPlus needed) ----------------------------------------------------------------
def _timeline(label: datetime) -> EnergyPlusTimeline:
    return EnergyPlusTimeline({label: TimelineValue(21.0, 60.0, 250.0, 0.4, 3.0, 0.0)}, {"timeline_hash": "x"})


def test_engine_serves_the_timeline_and_never_invents_co2():
    label = datetime(2026, 2, 16, 12, tzinfo=timezone.utc)
    result = EnergyPlusMicroclimateEngine(_timeline(label)).advance(WeatherState(10, 70, 300, 2, 90, 0, 1000), None, 3600.0, "passive_greenhouse", None, None, simulation_time=label)
    state = result.indoor_state
    assert (state.temperature_c, state.relative_humidity_pct, state.solar_radiation_w_m2, state.ventilation_fraction, state.heating_kw) == (21.0, 60.0, 250.0, 0.4, 3.0)
    assert state.pressure_hpa == 1000 and state.co2_ppm == 420.0  # co2 stays at the baseline; the API reports the variable as NOT_SUPPORTED


def test_engine_requires_the_step_time_and_a_known_label():
    label = datetime(2026, 2, 16, 12, tzinfo=timezone.utc)
    engine = EnergyPlusMicroclimateEngine(_timeline(label))
    weather = WeatherState(10, 70, 300, 2, 90, 0, 1000)
    with pytest.raises(GreenhouseModelError):
        engine.advance(weather, None, 3600.0)
    with pytest.raises(GreenhouseModelError):
        engine.advance(weather, None, 3600.0, simulation_time=label + timedelta(hours=1))


# -- end to end (needs EnergyPlus 26.1) -----------------------------------------------------------------------
@needs_energyplus
def test_service_runs_energyplus_deterministically_and_reports_its_provenance():
    service = InteractiveSimulationService()
    first = service.run_simulation({**BASE, "greenhouse": ENERGYPLUS})
    second = service.run_simulation({**BASE, "greenhouse": ENERGYPLUS})
    assert first.execution_status.value == "COMPLETED" and not first.errors
    assert first.hashes["trajectory_hash"] == second.hashes["trajectory_hash"] and first.hashes["configuration_hash"] == second.hashes["configuration_hash"]
    simplified = service.run_simulation(BASE)
    assert first.hashes["trajectory_hash"] != simplified.hashes["trajectory_hash"]
    assert first.diagnostics["greenhouse_backend"]["backend"] == "ENERGYPLUS" and first.diagnostics["greenhouse_backend"]["energyplus_version"].startswith("26.1")
    assert simplified.diagnostics["greenhouse_backend"] == "SIMPLIFIED"
    co2 = next(item for item in first.result.to_dict()["variables"] if item["name"] == "co2_ppm")
    assert co2["availability"] == "NOT_SUPPORTED" and "co2_ppm" not in first.result.trajectory
    assert min(first.result.trajectory["temperature_c"]) >= 11.9  # the ideal-loads heater holds its setpoint


@needs_energyplus
def test_layout_changes_the_result_and_the_configuration_hash():
    service = InteractiveSimulationService()
    capilla = service.run_simulation({**BASE, "greenhouse": ENERGYPLUS})
    tunnel = service.run_simulation({**BASE, "greenhouse": {**ENERGYPLUS, "layout": {"typology": "TUNEL"}}})
    assert capilla.hashes["configuration_hash"] != tunnel.hashes["configuration_hash"]
    assert capilla.result.trajectory["temperature_c"] != tunnel.result.trajectory["temperature_c"]


@needs_energyplus
def test_resuming_from_a_checkpoint_reproduces_the_continuous_run_exactly():
    runtime = InteractiveRuntimeService(InteractiveSimulationService())
    request = {**BASE, "end_time": "2026-02-22T00:00:00+00:00", "greenhouse": ENERGYPLUS}
    out = runtime.what_if({"request": request, "checkpoint_time": "2026-02-17T00:00:00+00:00", "events": [
        {"event_type": "HEAT_WAVE", "start_simulation_time": "2026-02-19T00:00:00+00:00", "duration_hours": 12, "intensity": 6}]})
    continuous = InteractiveSimulationService().run_simulation(request).result.trajectory
    baseline = out["branches"]["baseline"]["response"]["result"]["trajectory"]
    prefix = out["prefix"]["result"]["trajectory"]
    for name in ("temperature_c", "relative_humidity_pct", "radiation_w_m2", "greenhouse_ventilation_fraction", "biomass_total_g_m2"):
        assert prefix[name] + baseline[name] == continuous[name], name


@needs_energyplus
def test_commanded_ventilation_and_a_heat_wave_act_through_energyplus():
    runtime = InteractiveRuntimeService(InteractiveSimulationService())
    request = {**BASE, "end_time": "2026-02-22T00:00:00+00:00", "greenhouse": ENERGYPLUS}
    out = runtime.what_if({"request": request, "checkpoint_time": "2026-02-17T00:00:00+00:00", "events": [
        {"event_type": "VENTILATION", "start_simulation_time": "2026-02-18T00:00:00+00:00", "duration_hours": 36, "intensity": 1.0},
        {"event_type": "HEAT_WAVE", "start_simulation_time": "2026-02-19T00:00:00+00:00", "duration_hours": 24, "intensity": 8}]})
    baseline = out["branches"]["baseline"]["response"]["result"]["trajectory"]
    intervention = out["branches"]["intervention"]["response"]["result"]["trajectory"]
    assert out["comparison"]["unchanged_before_first_event"] is True
    assert max(intervention["greenhouse_ventilation_fraction"]) == pytest.approx(1.0)
    assert statistics.mean(intervention["greenhouse_ventilation_fraction"]) > statistics.mean(baseline["greenhouse_ventilation_fraction"])
    assert max(intervention["temperature_c"]) > max(baseline["temperature_c"])  # the heat wave reaches the interior
