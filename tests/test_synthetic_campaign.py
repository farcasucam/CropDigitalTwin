from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import (
    AcquisitionFaults,
    AcquisitionSourceType,
    CampaignConfiguration,
    CampaignCropSpec,
    IdentifiabilityStatus,
    SyntheticCampaignError,
    SyntheticObservationCampaign,
    TemporalAlignment,
    campaigns_are_deterministic,
    default_campaign_crops,
)
from agri_twin.domain import AlignmentPolicy, ObservationSourceType, ParameterRegistry, QualityFlag

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def _configuration(**overrides) -> CampaignConfiguration:
    base = dict(
        campaign_id="phase5-18-test",
        root=ROOT,
        start=START,
        end=START + timedelta(hours=2),
        interval_seconds=3600,
        seed=518,
    )
    base.update(overrides)
    return CampaignConfiguration(**base)


# --- Core -------------------------------------------------------------


def test_campaign_construction_and_defaults():
    cfg = _configuration()
    assert cfg.crops == default_campaign_crops()
    assert len(cfg.crops) == 8


def test_invalid_configuration_rejected():
    for kwargs in (
        dict(campaign_id=""),
        dict(end=START - timedelta(hours=1)),
        dict(interval_seconds=0),
        dict(crops=()),
    ):
        try:
            _configuration(**kwargs)
        except SyntheticCampaignError:
            continue
        raise AssertionError(f"expected SyntheticCampaignError for {kwargs}")


def test_duplicate_plot_cycle_pair_rejected():
    crops = (
        CampaignCropSpec("tomato", "RAF", "GREENHOUSE", "P-X", "C-1", "annual", "vegetative_growth"),
        CampaignCropSpec("tomato", "RAF", "GREENHOUSE", "P-X", "C-1", "annual", "vegetative_growth"),
    )
    try:
        _configuration(crops=crops)
    except SyntheticCampaignError:
        return
    raise AssertionError("expected duplicate plot/cycle rejection")


def test_deterministic_configuration_hash():
    cfg_a = _configuration()
    cfg_b = _configuration()
    assert cfg_a.config_hash() == cfg_b.config_hash()


def test_deterministic_execution():
    cfg = _configuration()
    result_a = SyntheticObservationCampaign(cfg).run()
    result_b = SyntheticObservationCampaign(cfg).run()
    assert campaigns_are_deterministic(result_a, result_b)


def test_campaign_report_is_json_serializable():
    import json

    result = SyntheticObservationCampaign(_configuration()).run()
    encoded = json.dumps(result.report.to_dict())
    assert encoded


# --- Crops and varieties ------------------------------------------------


def test_all_seven_crops_covered():
    cfg = _configuration()
    crops = {item.crop for item in cfg.crops}
    assert crops == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}


def test_known_varieties_preserved():
    cfg = _configuration()
    varieties = {(item.crop, item.variety) for item in cfg.crops}
    assert ("tomato", "RAF") in varieties
    assert ("pepper", "Lamuyo") in varieties
    assert ("grape", "Monastrell") in varieties
    assert ("plum", "Suplum 26") in varieties
    # crops without a locally known variety stay at species/generic scope
    assert ("lettuce", None) in varieties
    assert ("peach", None) in varieties
    assert ("apple", None) in varieties


# --- Temporal -------------------------------------------------------------


def test_annual_and_perennial_cycle_types_present():
    cfg = _configuration()
    types = {item.cycle_type for item in cfg.crops}
    assert types == {"annual", "perennial"}


def test_lettuce_multiple_cycles_isolated():
    result = SyntheticObservationCampaign(_configuration()).run()
    history_1 = result.twin_repository.history("P-LETTUCE-1", "cycle_1")
    history_2 = result.twin_repository.history("P-LETTUCE-2", "cycle_2")
    assert history_1 and history_2
    assert all(state.cycle_id == "cycle_1" for state in history_1)
    assert all(state.cycle_id == "cycle_2" for state in history_2)
    # no state leaked from one cycle's plot/cycle key into the other
    assert {state.key for state in history_1}.isdisjoint({state.key for state in history_2})


def test_simulation_clock_is_sole_time_authority():
    result = SyntheticObservationCampaign(_configuration()).run()
    for record in result.acquisition_records:
        assert record.clock_source == "SimulationClock"


# --- Environment ------------------------------------------------------


def test_outdoor_and_greenhouse_environments_covered():
    cfg = _configuration()
    environments = {item.environment for item in cfg.crops}
    assert environments == {"OUTDOOR", "GREENHOUSE"}


# --- Acquisition --------------------------------------------------------


def test_simulated_backend_provenance():
    result = SyntheticObservationCampaign(_configuration()).run()
    assert all(record.source_type is AcquisitionSourceType.SYNTHETIC for record in result.acquisition_records)
    assert result.report.backend_substitution_status == "SIMULATED_ACQUISITION_ONLY"
    assert result.ingestion.source_type is ObservationSourceType.SYNTHETIC_TEST


def test_future_real_adapter_backend_substitution():
    cfg = _configuration(use_future_real_adapter=True, end=START + timedelta(hours=1))
    result = SyntheticObservationCampaign(cfg).run()
    assert result.report.backend_substitution_status.startswith("FUTURE_REAL_ADAPTER_SUBSTITUTED")
    assert any(record.source_type is AcquisitionSourceType.MEASURED for record in result.acquisition_records)
    assert result.ingestion.dataset is not None
    assert result.report.pipeline_status == "SUCCESS"


# --- Observation pipeline ------------------------------------------------


def test_acquisition_to_ingestion_to_dataset_to_comparison_to_diagnostics():
    result = SyntheticObservationCampaign(_configuration()).run()
    assert result.acquisition_records
    assert result.ingestion.dataset is not None
    assert result.comparison.results
    assert result.diagnostics.global_summary().n >= 0


# --- Defects --------------------------------------------------------------


def test_missing_observation_defect_is_not_imputed():
    cfg = _configuration(faults=AcquisitionFaults(missing_every=5), end=START + timedelta(hours=6))
    result = SyntheticObservationCampaign(cfg).run()
    assert result.report.quality_counts["missing"] > 0
    assert result.ingestion.qc


def test_duplicate_defect_detected_by_existing_ingestion_rules():
    cfg = _configuration(faults=AcquisitionFaults(duplicate_every=5), end=START + timedelta(hours=6))
    result = SyntheticObservationCampaign(cfg).run()
    assert result.report.quality_counts["duplicate"] > 0


def test_invalid_value_defect_detected():
    cfg = _configuration(faults=AcquisitionFaults(invalid_every=5), end=START + timedelta(hours=6))
    result = SyntheticObservationCampaign(cfg).run()
    assert result.report.quality_counts["invalid"] > 0


def test_unit_mismatch_detected_as_unit_error():
    cfg = _configuration(faults=AcquisitionFaults(unit_error_every=5), end=START + timedelta(hours=6))
    result = SyntheticObservationCampaign(cfg).run()
    assert result.report.quality_counts["unit_error"] > 0
    assert any(issue.quality is QualityFlag.UNIT_ERROR for issue in result.ingestion.qc)


def test_temporal_mismatch_behaves_per_alignment_contract():
    cfg = _configuration(
        temporal_shift_variable="co2",
        temporal_shift_seconds=7200,
        end=START + timedelta(hours=4),
        alignment=TemporalAlignment(policy=AlignmentPolicy.EXACT),
    )
    exact_result = SyntheticObservationCampaign(cfg).run()
    co2_exact = [item for item in exact_result.comparison.results if item.variable == "co2"]
    assert any(item.alignment.status.value != "MATCHED" for item in co2_exact)

    nearest_cfg = _configuration(
        temporal_shift_variable="co2",
        temporal_shift_seconds=7200,
        end=START + timedelta(hours=4),
        alignment=TemporalAlignment(policy=AlignmentPolicy.NEAREST, max_time_delta_seconds=10800),
    )
    nearest_result = SyntheticObservationCampaign(nearest_cfg).run()
    co2_nearest = [item for item in nearest_result.comparison.results if item.variable == "co2"]
    assert any(item.alignment.status.value == "MATCHED" for item in co2_nearest)


def test_known_synthetic_bias_detected_by_error_diagnostics():
    cfg = _configuration(known_bias_variable="air_temperature", known_bias_offset=1.5, bias_threshold=0.1)
    result = SyntheticObservationCampaign(cfg).run()
    variable_summaries = {item.variable: item for item in result.diagnostics.by_variable()}
    summary = variable_summaries["air_temperature"]
    assert summary.bias is not None and abs(summary.bias) == 1.5
    assert summary.mae == 1.5
    from agri_twin.application import diagnose

    temperature_only = type(result.comparison)(
        tuple(item for item in result.comparison.results if item.variable == "air_temperature"),
        summary.matched_count, summary.unmatched_count, summary.ambiguous_count, summary.invalid_count,
    )
    scoped_diagnostics = diagnose(temperature_only, bias_threshold=0.1)
    assert "BIAS_ABOVE_CONFIGURED_THRESHOLD" in scoped_diagnostics.bias_warnings()


# --- Identifiability -----------------------------------------------------


def test_identifiability_recomputation_does_not_force_favorable_status():
    result = SyntheticObservationCampaign(_configuration()).run()
    # synthetic_test_data can never establish scientific identifiability by policy
    assert result.identifiability_after.synthetic_data_only
    assert not any(
        assessment.identifiability_status is IdentifiabilityStatus.IDENTIFIABLE
        for assessment in result.identifiability_after.assessments
    )


def test_identifiability_before_and_after_are_consistent_analyzer_runs():
    result = SyntheticObservationCampaign(_configuration()).run()
    assert len(result.identifiability_before.assessments) == len(result.identifiability_after.assessments)


# --- Scientific safeguards ------------------------------------------------


def test_no_calibration_performed():
    import agri_twin.application.synthetic_campaign as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("GridSearchCalibrator(", "CalibrationObjective(", ".optimize(", "import GridSearchCalibrator"):
        assert forbidden not in source


def test_no_twin_state_mutation_from_observations():
    result = SyntheticObservationCampaign(_configuration()).run()
    truth_state = result.twin_repository.latest("P-TOMATO", "C-TOMATO-1")
    assert truth_state is not None
    assert truth_state.state_provenance == "SIMULATION"
    # comparison never writes back into the repository
    before = result.twin_repository.history("P-TOMATO", "C-TOMATO-1")
    from agri_twin.application.twin_alignment import compare_dataset

    compare_dataset(result.twin_repository, result.ingestion.dataset)
    after = result.twin_repository.history("P-TOMATO", "C-TOMATO-1")
    assert before == after


def test_parameter_registry_not_mutated():
    registry = ParameterRegistry.from_repository(ROOT)
    before = tuple(registry.records)
    SyntheticObservationCampaign(_configuration()).run()
    after = tuple(registry.records)
    assert before == after
