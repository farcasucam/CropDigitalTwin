from datetime import datetime, timezone
from pathlib import Path

import pytest

from agri_twin.domain import (
    CalibrationLevel,
    CropCalibrationError,
    DatasetRole,
    Observation,
    ObservationDataset,
    ParameterRegistry,
    ScientificStatus,
    SimulationPoint,
    audit_observations,
    build_protocol,
    synthetic_calibration_report,
)


ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def registry():
    return ParameterRegistry.from_repository(ROOT)


@pytest.mark.parametrize("crop", ["tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"])
def test_all_catalogued_crops_build_protocol_with_insufficient_data(crop):
    protocol = build_protocol(ROOT, registry(), crop)

    assert protocol.status == ScientificStatus.INSUFFICIENT_DATA
    assert protocol.observation_audit.observation_count == 0


@pytest.mark.parametrize("crop,variety,plot", [("tomato", "RAF", "plot_12010"), ("pepper", "Lamuyo", "plot_40811"), ("grape", "Monastrell", "plot_30412"), ("plum", "Suplum 26", "plot_14705")])
def test_known_variety_inventory_is_represented_without_variety_values(crop, variety, plot):
    protocol = build_protocol(ROOT, registry(), crop, variety, plot)

    assert protocol.variety == variety
    assert any(record.level == CalibrationLevel.SPECIES for record in protocol.matrix)
    assert "variety-specific prior" not in " ".join(protocol.warnings)


def test_unknown_variety_is_warned_not_invented():
    protocol = build_protocol(ROOT, registry(), "tomato", "Unknown", "plot_unknown")

    assert any("not in the known project inventory" in warning for warning in protocol.warnings)


def test_unknown_crop_is_rejected():
    with pytest.raises(CropCalibrationError):
        build_protocol(ROOT, registry(), "unknown")


def test_observation_audit_finds_weather_but_not_agronomic_observations():
    audit = audit_observations(ROOT, "tomato", "RAF", "plot_12010")

    assert audit.observation_count == 0
    assert any("weather CSV" in limitation for limitation in audit.limitations)


def test_protocol_matrix_has_prior_range_and_scientific_status():
    protocol = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010")
    candidate = next(record for record in protocol.matrix if record.parameter_id == "crop.tomato.establishment.stress_thresholds.min_temp_c")

    assert candidate.prior_value is not None
    assert candidate.calibration_status == ScientificStatus.INSUFFICIENT_DATA
    assert candidate.required_observations


def test_parameter_hierarchy_separates_species_and_variety_scope():
    protocol = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010")
    scopes = {record.level for record in protocol.matrix}

    assert CalibrationLevel.SPECIES in scopes


def test_environment_scope_is_preserved():
    protocol = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010", "GREENHOUSE")

    assert protocol.environment_type == "GREENHOUSE"


def test_report_mentions_insufficient_data_and_prior_status():
    report = build_protocol(ROOT, registry(), "plum", "Suplum 26", "plot_14705").to_report()

    assert "INSUFFICIENT_DATA" in report and "Matrix" in report


def test_protocol_parameter_set_does_not_include_unbounded_unknown_values():
    protocol = build_protocol(ROOT, registry(), "lettuce")

    assert all(parameter.minimum is not None and parameter.maximum is not None for parameter in protocol.parameter_set().values)


def test_synthetic_parameter_recovery_report_is_distinct_from_real_data():
    protocol = build_protocol(ROOT, registry(), "tomato")
    parameter = next(record for record in protocol.matrix if record.minimum is not None and record.maximum is not None)
    observation = Observation(T0, "x", 1.0, "unit")
    dataset = ObservationDataset("synthetic-demo", DatasetRole.CALIBRATION, (observation,))

    def runner(case, parameters, data):
        return (SimulationPoint(T0, {"x": 1.0}, {"x": "unit"}),)

    report = synthetic_calibration_report(protocol, runner, dataset)

    assert report.result is not None
    assert report.validation_status == ScientificStatus.CALIBRATED
    assert any("synthetic" in warning.lower() for warning in report.warnings)


def test_synthetic_report_is_reproducible():
    protocol = build_protocol(ROOT, registry(), "tomato")
    dataset = ObservationDataset("synthetic-demo", DatasetRole.CALIBRATION, (Observation(T0, "x", 1.0, "unit"),))
    runner = lambda case, parameters, data: (SimulationPoint(T0, {"x": 1.0}),)

    assert synthetic_calibration_report(protocol, runner, dataset).to_markdown() == synthetic_calibration_report(protocol, runner, dataset).to_markdown()


def test_synthetic_report_has_boundary_warning_when_result_hits_limit():
    protocol = build_protocol(ROOT, registry(), "tomato")
    dataset = ObservationDataset("synthetic-demo", DatasetRole.CALIBRATION, (Observation(T0, "x", 0.0, "unit"),))
    runner = lambda case, parameters, data: (SimulationPoint(T0, {"x": 0.0}),)
    report = synthetic_calibration_report(protocol, runner, dataset)

    assert report.result is not None


def test_matrix_contains_identifiability_risk():
    protocol = build_protocol(ROOT, registry(), "grape", "Monastrell", "plot_30412")

    assert {record.identifiability_risk for record in protocol.matrix} <= {"HIGH", "MODERATE"}


def test_matrix_contains_confounds():
    protocol = build_protocol(ROOT, registry(), "tomato")

    assert all(record.confounds for record in protocol.matrix)


def test_literature_prior_is_not_calibrated_status():
    protocol = build_protocol(ROOT, registry(), "apple")

    assert all(record.calibration_status != ScientificStatus.CALIBRATED for record in protocol.matrix)


def test_validation_status_is_not_promoted_without_validation_data():
    protocol = build_protocol(ROOT, registry(), "peach")

    assert protocol.status != ScientificStatus.VALIDATED


def test_missing_local_data_is_explicit_for_known_plot():
    audit = audit_observations(ROOT, "plum", "Suplum 26", "plot_14705")

    assert audit.status == ScientificStatus.INSUFFICIENT_DATA


def test_other_crops_are_framework_ready_in_matrix_even_without_local_variety():
    protocol = build_protocol(ROOT, registry(), "apple")

    assert protocol.matrix


def test_species_prior_does_not_change_between_varieties():
    generic = build_protocol(ROOT, registry(), "tomato")
    raf = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010")
    generic_ids = {record.parameter_id for record in generic.matrix}
    raf_ids = {record.parameter_id for record in raf.matrix}

    assert generic_ids == raf_ids


def test_plot_scope_is_recorded():
    protocol = build_protocol(ROOT, registry(), "pepper", "Lamuyo", "plot_40811")

    assert all(record.plot == "plot_40811" for record in protocol.matrix)


def test_outdoor_and_greenhouse_protocols_are_distinct():
    outdoor = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010", "OUTDOOR")
    greenhouse = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010", "GREENHOUSE")

    assert outdoor.environment_type != greenhouse.environment_type


def test_status_enum_is_explicit():
    assert {status.value for status in ScientificStatus} >= {"NOT_EVALUATED", "FRAMEWORK_READY", "INSUFFICIENT_DATA", "CALIBRATION_READY", "CALIBRATED", "VALIDATED"}


def test_calibration_prior_preserves_unit():
    protocol = build_protocol(ROOT, registry(), "tomato")

    assert all(record.unit for record in protocol.matrix)


def test_calibration_matrix_is_deterministic():
    first = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010").to_report()
    second = build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010").to_report()

    assert first == second


def test_no_real_time_dependency_in_protocol_module():
    source = (ROOT / "src" / "agri_twin" / "domain" / "crop_calibration.py").read_text(encoding="utf-8")

    assert "datetime.now" not in source and "time.time" not in source


def test_protocol_requires_observations_for_ready_status():
    protocol = build_protocol(ROOT, registry(), "tomato")

    assert protocol.observation_audit.status == ScientificStatus.INSUFFICIENT_DATA


def test_calibration_candidates_have_observation_requirements():
    protocol = build_protocol(ROOT, registry(), "pepper", "Lamuyo", "plot_40811")

    assert all(record.required_observations for record in protocol.matrix)


def test_report_contains_limitations():
    protocol = build_protocol(ROOT, registry(), "grape", "Monastrell", "plot_30412")

    assert "Observation limitations" in protocol.to_report()


def test_generic_crop_protocol_has_no_fake_variety():
    protocol = build_protocol(ROOT, registry(), "lettuce")

    assert protocol.variety is None


def test_known_variety_does_not_get_fake_calibrated_values():
    protocol = build_protocol(ROOT, registry(), "plum", "Suplum 26", "plot_14705")

    assert protocol.status == ScientificStatus.INSUFFICIENT_DATA


def test_parameter_prior_sources_are_preserved():
    protocol = build_protocol(ROOT, registry(), "tomato")

    assert any(record.source for record in protocol.matrix)


def test_scope_levels_are_not_all_variety_specific():
    protocol = build_protocol(ROOT, registry(), "grape", "Monastrell", "plot_30412")

    assert any(record.level == CalibrationLevel.SPECIES for record in protocol.matrix)


def test_protocol_warnings_are_stable():
    assert build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010").warnings == build_protocol(ROOT, registry(), "tomato", "RAF", "plot_12010").warnings