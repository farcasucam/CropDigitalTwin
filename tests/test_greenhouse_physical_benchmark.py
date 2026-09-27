"""Phase 5.31 analytical physical benchmarks of the greenhouse-crop model."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from agri_twin.application.greenhouse_physical_benchmark import (
    BenchmarkLayer,
    BenchmarkStatus,
    GreenhousePhysicalBenchmarkSuite,
    closed_box,
    crop_state,
    indoor,
    outdoor,
)
from agri_twin.domain import CropGreenhouseFeedbackLoop, GreenhouseActuatorState, GreenhouseConfiguration, SimplifiedGreenhouseModel

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report():
    return GreenhousePhysicalBenchmarkSuite(ROOT).build_report()


@pytest.fixture(scope="module")
def cases(report):
    return {case.case_id: case for case in report.cases}


def passed(cases, case_id):
    case = cases[case_id]
    assert case.status is BenchmarkStatus.PASS, f"{case_id}: {case.actual_relation}"
    return case.outputs


# --- energy (A, B) ------------------------------------------------------------------


def test_identical_ambient_has_no_drift(cases):
    outputs = passed(cases, "energy.identical_ambient_no_drift")
    assert outputs["temperature_drift_c"] == 0.0 and abs(outputs["vapour_drift_kg_m3"]) < 1e-15


def test_sealed_air_stores_exactly_the_transmitted_solar_energy(cases):
    outputs = passed(cases, "energy.radiation_energy_closure")
    assert outputs["stored_heat_j"] == pytest.approx(outputs["absorbed_solar_j"], rel=1e-9)


def test_heat_exchange_sign_follows_the_indoor_outdoor_difference(cases):
    outputs = passed(cases, "energy.exchange_sign")
    assert outputs["indoor_warmer_dT"] < 0 < outputs["indoor_colder_dT"]


def test_heat_exchange_is_linear_in_the_temperature_difference(cases):
    changes = passed(cases, "energy.exchange_scales_with_difference")["temperature_change_c"]
    assert changes[1] == pytest.approx(2 * changes[0]) and changes[2] == pytest.approx(2 * changes[1])


def test_no_hidden_reference_temperature(cases):
    changes = passed(cases, "energy.no_hidden_reference_temperature")["temperature_change_c"]
    assert max(changes) - min(changes) < 1e-9


def test_thermal_time_constant_halves_the_difference(cases):
    assert passed(cases, "energy.thermal_time_constant")["indoor_after_half_life_c"] == pytest.approx(25.0)


def test_higher_outdoor_temperature_warms_the_interior(cases):
    indoor_c = passed(cases, "monotonicity.outdoor_temperature")["indoor_c"]
    assert indoor_c == sorted(indoor_c) and len(set(indoor_c)) == len(indoor_c)


# --- ventilation (C) -------------------------------------------------------------------


def test_exchanged_fraction_follows_first_order_air_exchange(cases):
    fractions = passed(cases, "ventilation.exchanged_fraction")["exchanged_fraction"]
    assert fractions[0] == 0.0 and fractions[-1] < 1.0
    assert fractions[2] == pytest.approx(1.0 - math.exp(-3.0))


@pytest.mark.parametrize("quantity", ["temperature", "vapour", "co2"])
def test_ventilation_moves_each_balance_toward_outdoor(cases, quantity):
    gaps = passed(cases, f"ventilation.{quantity}_toward_outdoor")[f"{quantity}_gap_to_outdoor"]
    assert all(later < earlier for earlier, later in zip(gaps, gaps[1:]))


def test_configured_and_actuator_ventilation_add(cases):
    outputs = passed(cases, "ventilation.configuration_plus_actuator")
    assert outputs["split"] == outputs["joined"]


def test_ventilation_has_no_direct_path_to_biomass(cases):
    outputs = passed(cases, "ventilation.no_direct_biomass_path")
    assert outputs["microclimate_identical"] and outputs["crop_identical"]


# --- humidity / VPD ---------------------------------------------------------------------


def test_rh_and_vpd_stay_physically_bounded(cases):
    assert passed(cases, "humidity.rh_vpd_bounds")["violations"] == []


def test_sealed_air_conserves_transpired_water(cases):
    outputs = passed(cases, "humidity.closed_box_vapour_conservation")
    assert outputs["vapour_added_kg"] == pytest.approx(outputs["water_transpired_kg"], rel=1e-6)


def test_cooling_humid_air_condenses_at_saturation(cases):
    outputs = passed(cases, "humidity.condensation_bound")
    assert outputs["rh_pct"] == pytest.approx(100.0) and outputs["vpd_kpa"] < 1e-9


def test_phase_5_29_closed_saturated_greenhouse_has_no_latent_flux(cases):
    outputs = passed(cases, "humidity.closed_saturated_greenhouse_no_latent_regression")
    assert outputs["latent_flux_at_saturation_steps"] == 0 and outputs["max_rh_pct"] <= 100.0


def test_vpd_is_corrected_only_once(cases):
    outputs = passed(cases, "humidity.no_double_vpd_correction")
    first, second = outputs["transpiration_mm_h"]
    assert first == pytest.approx(second)
    assert outputs["crop_vpd_stress"] == pytest.approx(outputs["single_ramp_vpd_stress"])


def test_vpd_units_are_kpa(cases):
    assert passed(cases, "units.vpd_kpa")["vpd_kpa"] == pytest.approx(1.584, abs=1e-3)


# --- latent -------------------------------------------------------------------------------


def test_no_canopy_means_no_latent_flux(cases):
    outputs = passed(cases, "latent.no_crop_no_flux")
    assert outputs["latent_w_m2"] == 0.0


def test_canopy_without_radiative_demand_has_no_latent_flux(cases):
    assert passed(cases, "latent.crop_without_transpiration")["latent_w_m2"] == 0.0


def test_latent_cooling_is_applied_once_with_the_correct_sign(cases):
    outputs = passed(cases, "latent.dry_air_cooling_applied_once")
    assert outputs["latent_w_m2"] > 0 and outputs["temperature_change_c"] < 0
    assert outputs["temperature_change_c"] == pytest.approx(outputs["expected_change_c"])


def test_saturated_air_produces_no_latent_cooling(cases):
    outputs = passed(cases, "latent.saturated_air_no_cooling")
    assert outputs["transpiration_mm_h"] == 0.0 and outputs["latent_w_m2"] == 0.0


def test_latent_flux_grows_with_evaporative_capacity(cases):
    fluxes = passed(cases, "monotonicity.transpiration_capacity")["latent_w_m2"]
    assert fluxes == sorted(fluxes) and fluxes[0] < fluxes[-1]


# --- radiation ------------------------------------------------------------------------------


def test_cover_transmission_scales_indoor_radiation(cases):
    assert passed(cases, "radiation.cover_transmission")["indoor_w_m2"] == pytest.approx([400.0, 624.0, 800.0])


def test_shading_reduces_indoor_radiation(cases):
    indoor_w_m2 = passed(cases, "radiation.shading")["indoor_w_m2"]
    assert indoor_w_m2[0] > indoor_w_m2[1] > indoor_w_m2[2]


def test_zero_radiation_gives_no_potential_growth(cases):
    outputs = passed(cases, "radiation.zero")
    assert outputs["indoor_w_m2"] == 0.0 and outputs["potential_growth_g_m2"] == 0.0


def test_crop_receives_indoor_radiation_exactly_once(cases):
    outputs = passed(cases, "radiation.single_path_to_crop")
    assert outputs["potential_growth_g_m2"] == pytest.approx(outputs["single_indoor_path_g_m2"])
    assert outputs["potential_growth_g_m2"] < outputs["outdoor_path_g_m2"]


# --- CO2 --------------------------------------------------------------------------------------


def test_sealed_air_co2_bookkeeping(cases):
    outputs = passed(cases, "co2.closed_box_bookkeeping")
    assert outputs["supplied_ppm"] == pytest.approx(540.0) and outputs["uptaken_ppm"] == pytest.approx(475.0)


def test_ventilated_co2_reaches_its_analytic_equilibrium(cases):
    outputs = passed(cases, "co2.ventilated_equilibrium")
    assert outputs["co2_ppm"] == pytest.approx(outputs["analytic_equilibrium_ppm"])


def test_more_co2_supply_raises_indoor_co2(cases):
    concentrations = passed(cases, "monotonicity.co2_supply")["co2_ppm"]
    assert concentrations[0] < concentrations[1] < concentrations[2]


def test_crop_uptake_lowers_indoor_co2(cases):
    outputs = passed(cases, "co2.crop_uptake_reduces_co2")
    assert outputs["with_crop_ppm"] < outputs["without_crop_ppm"] and outputs["uptake_ppm_step"] > 0


def test_co2_follows_a_single_path_and_double_application_is_rejected(cases):
    outputs = passed(cases, "co2.single_path_to_growth")
    assert outputs["double_application_rejected"] is True
    growth = outputs["actual_growth_g_m2"]
    assert growth[210.0] == pytest.approx(0.5 * growth[420.0]) and growth[840.0] == pytest.approx(growth[420.0])


# --- crop consumes the microclimate ----------------------------------------------------------------


def test_outdoor_crop_temperature_is_the_outdoor_temperature(cases):
    assert passed(cases, "crop_microclimate.outdoor_temperature")["crop_environment_equals_weather"] is True


def test_greenhouse_crop_temperature_is_the_indoor_temperature(cases):
    outputs = passed(cases, "crop_microclimate.greenhouse_temperature")
    assert outputs["crop_c"] == outputs["indoor_c"] != outputs["outdoor_c"]


def test_greenhouse_crop_receives_indoor_rh_vpd_radiation_co2_and_no_rain(cases):
    outputs = passed(cases, "crop_microclimate.greenhouse_rh_vpd_radiation_co2")
    assert outputs["crop_environment"]["rain"] == 0.0


# --- feedback ---------------------------------------------------------------------------------------


def test_loop_without_exchanges_reproduces_the_greenhouse_step(cases):
    assert passed(cases, "feedback.none")["all_exchanges_zero"] is True


@pytest.mark.parametrize("name", ["thermal", "latent", "co2"])
def test_each_feedback_term_changes_only_its_own_balance(cases, name):
    passed(cases, f"feedback.{name}_isolated")


def test_relaxation_is_applied_once_per_iteration(cases):
    outputs = passed(cases, "feedback.relaxation_applied_once")
    assert outputs["loop_temperature_c"] == pytest.approx(outputs["reconstructed_c"], rel=1e-12)


def test_only_the_converged_state_persists_in_loop_and_backend(cases):
    outputs = passed(cases, "feedback.only_converged_state_persists")
    assert outputs["backend_state_equals_converged"] and outputs["input_crop_unchanged"]


def test_backend_commit_regression():
    backend = SimplifiedGreenhouseModel()
    loop = CropGreenhouseFeedbackLoop(backend)
    result = loop.step(crop_state(), outdoor(26.0, 55.0, 700.0), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600.0, prior=indoor(25.0, 55.0))
    assert backend.state() is result.microclimate


def test_combined_feedback_converges_and_replays(cases):
    runs = passed(cases, "feedback.combined_convergence_determinism")["runs"]
    assert all(run["converged"] == run["steps"] and run["replay_identical"] and run["reversals_over_1c"] == 0 for run in runs.values())


# --- determinism, units, mutation -----------------------------------------------------------------


def test_scenario_replay_is_identical(cases):
    outputs = passed(cases, "determinism.scenario_replay")
    assert outputs["first_hash"] == outputs["second_hash"]


def test_benchmark_report_is_deterministic(report):
    assert report.to_json() == GreenhousePhysicalBenchmarkSuite(ROOT).build_report().to_json()


def test_heating_units_kw_to_joules(cases):
    outputs = passed(cases, "units.heating_kw_to_joules")
    assert outputs["temperature_change_c"] == pytest.approx(3.6e6 / 2.5e6)


def test_misting_units_mm_to_kg(cases):
    outputs = passed(cases, "units.misting_mm_h_to_kg")
    assert outputs["vapour_added_kg"] == pytest.approx(0.36, rel=1e-6) and outputs["temperature_change_c"] < 0


def test_benchmark_does_not_mutate_parameters_configuration_or_state(cases):
    assert passed(cases, "mutation.no_parameter_configuration_or_state_mutation")["unchanged"] is True


def test_closed_box_fixture_is_adiabatic_and_sealed():
    box = closed_box()
    assert box.ventilation_ach == 0.0 and box.heat_loss_w_k == 0.0


# --- report-level ------------------------------------------------------------------------------------


def test_every_mandatory_benchmark_passes_and_report_is_qualified(report):
    assert report.counts == {"PASS": len(report.cases), "WARN": 0, "FAIL": 0}
    assert report.qualified is True
    assert len(report.cases) >= 30
    assert report.test_count is not None and report.test_count >= 30
    assert {case.layer for case in report.cases} == {BenchmarkLayer.SOFTWARE_CORRECTNESS, BenchmarkLayer.PHYSICAL_CONSISTENCY}


def test_invariants_hold_for_every_evaluated_state(report):
    invariants = report.invariants
    assert invariants["status"] == "PASS" and invariants["failures"] == []
    assert invariants["microclimate_states_checked"] > 100 and invariants["crop_states_checked"] > 50


def test_every_benchmark_parameter_is_traceable_and_not_calibrated(report):
    traceability = report.traceability
    assert traceability["status"] == "PASS" and traceability["gaps"] == []
    assert all(row["registered"] and row["source_type"] != "calibrated" for row in traceability["parameters"])
    assert {row["parameter_id"] for row in traceability["parameters"]} >= {"greenhouse.volume", "greenhouse.ventilation_ach", "greenhouse.heat_loss_conductance", "greenhouse.thermal_mass", "greenhouse.co2_baseline"}


def test_static_audit_finds_a_single_psychrometric_definition(report):
    audit = report.static_audit
    assert audit["status"] == "PASS"
    assert audit["saturation_vapour_pressure_definitions"] == ["agri_twin/domain/greenhouse.py:29"]
    assert audit["phase5_29_static_audit"]["duplicate_core_classes"] == {}


def test_energyplus_is_optional_and_never_ground_truth(report):
    assert report.energyplus["availability"] in {"AVAILABLE", "UNAVAILABLE", "INCOMPATIBLE", "MISCONFIGURED"}
    assert "never ground truth" in report.energyplus["role"]


def test_report_keeps_the_scientific_stance(report, tmp_path):
    payload = report.to_dict()
    status = payload["scientific_status"]
    assert status["REAL_AGRICULTURAL_DATA_VERIFIED"] is False and status["CALIBRATION_PERFORMED"] is False
    assert status["BIOLOGICAL_VALIDITY_CLAIMED"] is False and status["EXPERIMENTAL_VALIDATION"] == "DEFERRED_TO_FINAL_VALIDATION_STAGE"
    report_path, readme_path = GreenhousePhysicalBenchmarkSuite(ROOT).write_report(report, tmp_path)
    assert json.loads(report_path.read_text(encoding="utf-8"))["report_hash"] == payload["report_hash"]
    assert "not validation against a real greenhouse" in readme_path.read_text(encoding="utf-8")
