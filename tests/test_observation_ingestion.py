from datetime import datetime, timezone

import pytest

from agri_twin.domain import (
    CalibrationCase,
    CalibrationParameter,
    DatasetRole,
    ObservationIngestionError,
    ObservationSourceType,
    ParameterRegistry,
    ParameterReadinessStatus,
    QualityFlag,
    ReadinessStatus,
    ingest_rows,
    parameter_readiness,
    plot_readiness,
    ValidationCase,
)


T0 = "2026-07-01T10:00:00+00:00"


def row(**changes):
    value = dict(timestamp=T0, variable="LAI", value="2.0", unit="m2 m-2", source="sensor-1", plot_id="plot-1", crop="tomato", variety="RAF", environment="GREENHOUSE", measurement_method="sensor")
    value.update(changes)
    return value


def test_valid_observation_has_provenance_linkage_and_normalized_unit():
    result = ingest_rows([row()], dataset_id="obs-1", role=DatasetRole.VALIDATION, source="field-sensor-export", imported_at=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert result.readiness.status is ReadinessStatus.READY
    observation = result.dataset.observations[0]
    assert observation.variable == "lai"
    assert observation.unit == "m2_m-2"
    assert observation.unit_original == "m2 m-2"
    assert observation.source == "sensor-1"
    assert observation.plot_id == "plot-1"
    assert result.dataset.source == "field-sensor-export"
    assert result.dataset.imported_at == datetime(2026, 9, 8, tzinfo=timezone.utc)


def test_missing_invalid_and_unknown_values_are_explicit():
    result = ingest_rows([row(value="NA"), row(variable="not_supported"), row(value="-1")], dataset_id="bad", role=DatasetRole.VALIDATION, source="export")
    assert result.dataset is None
    assert result.readiness.status in {ReadinessStatus.INVALID, ReadinessStatus.INSUFFICIENT_DATA}
    assert {issue.quality for issue in result.qc} >= {QualityFlag.MISSING, QualityFlag.INVALID}


def test_duplicate_is_not_overwritten():
    result = ingest_rows([row(), row()], dataset_id="duplicates", role=DatasetRole.VALIDATION, source="export")
    assert result.readiness.n_valid == 1
    assert result.readiness.n_duplicates == 1
    assert any(issue.quality is QualityFlag.DUPLICATE for issue in result.qc)


def test_unit_conversion_is_explicit_and_incompatible_units_fail():
    converted = ingest_rows([row(variable="air_temperature", value="68", unit="degF")], dataset_id="units", role=DatasetRole.VALIDATION, source="export")
    assert converted.dataset.observations[0].value == pytest.approx(20)
    assert converted.dataset.observations[0].unit == "degC"
    invalid = ingest_rows([row(variable="lai", unit="degC")], dataset_id="bad-units", role=DatasetRole.VALIDATION, source="export")
    assert invalid.readiness.n_invalid == 1
    assert invalid.qc[0].quality is QualityFlag.UNIT_ERROR


def test_timezone_is_required_and_forcing_cannot_be_observation_dataset():
    invalid = ingest_rows([row(timestamp="2026-07-01T10:00:00")], dataset_id="time", role=DatasetRole.VALIDATION, source="export")
    assert invalid.qc[0].quality is QualityFlag.INVALID
    with pytest.raises(ObservationIngestionError):
        ingest_rows([row()], dataset_id="forcing", role=DatasetRole.TEST, source="weather.csv", source_type=ObservationSourceType.FORCING)


def test_quality_estimated_is_not_measured_and_resolution_is_preserved():
    result = ingest_rows([row(quality="ESTIMATED", resolution="daily")], dataset_id="quality", role=DatasetRole.VALIDATION, source="export")
    observation = result.dataset.observations[0]
    assert observation.quality == QualityFlag.ESTIMATED.value
    assert observation.resolution.value == "daily"
    assert observation.source_type == ObservationSourceType.MEASURED.value


def test_parameter_readiness_reuses_existing_registry():
    result = ingest_rows([
        row(variable="biomass", value="10", unit="g/m2"),
        row(variable="solar_radiation", value="400", unit="W/m2", timestamp="2026-07-01T11:00:00+00:00"),
    ], dataset_id="readiness", role=DatasetRole.CALIBRATION, source="field")
    readiness = parameter_readiness(ParameterRegistry.from_repository(__import__("pathlib").Path(__file__).parents[1]), result.dataset)
    rue = next(item for item in readiness if item.parameter_id == "radiation.rue")
    assert rue.status is ParameterReadinessStatus.READY_FOR_CALIBRATION
    assert rue.identifiability.startswith("screening")


def test_same_input_is_deterministic():
    first = ingest_rows([row()], dataset_id="same", role=DatasetRole.VALIDATION, source="export")
    second = ingest_rows([row()], dataset_id="same", role=DatasetRole.VALIDATION, source="export")
    assert first == second


def test_plot_readiness_uses_explicit_linkage_only():
    result = ingest_rows([row()], dataset_id="plots", role=DatasetRole.VALIDATION, source="export")
    summary = plot_readiness(result.dataset)
    assert summary[0]["plot_id"] == "plot-1"
    assert summary[0]["variables"] == ("lai",)


def test_csv_json_compatible_datasets_feed_existing_cases(tmp_path):
    csv_path = tmp_path / "observations.csv"
    csv_path.write_text("timestamp,variable,value,unit,source,plot_id\n2026-07-01T10:00:00+00:00,lai,2,m2 m-2,sensor,plot-1\n", encoding="utf-8")
    from agri_twin.domain import ingest_csv, ingest_json
    csv_result = ingest_csv(csv_path, dataset_id="csv", role=DatasetRole.CALIBRATION, source="field")
    json_path = tmp_path / "observations.json"
    json_path.write_text("[{\"timestamp\":\"2026-07-01T10:00:00+00:00\",\"variable\":\"lai\",\"value\":2,\"unit\":\"m2 m-2\",\"source\":\"sensor\"}]", encoding="utf-8")
    json_result = ingest_json(json_path, dataset_id="json", role=DatasetRole.VALIDATION, source="field")
    parameters = __import__("agri_twin.domain", fromlist=["ParameterSet"]).ParameterSet((CalibrationParameter("p", 1, 1, 0, 2, 1, "u", "engineering_default", "candidate_for_calibration", True),))
    assert isinstance(csv_result.dataset, type(json_result.dataset))
    assert CalibrationCase("tomato", "RAF", "plot-1", datetime.fromisoformat(T0), datetime.fromisoformat("2026-07-01T11:00:00+00:00"), csv_result.dataset, parameters)
    assert ValidationCase("tomato", "RAF", "plot-1", datetime.fromisoformat(T0), datetime.fromisoformat("2026-07-01T11:00:00+00:00"), json_result.dataset, parameters)
