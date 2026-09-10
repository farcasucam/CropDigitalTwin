from datetime import datetime, timezone
from pathlib import Path

from agri_twin.application import (
    CalibrationReadinessGate,
    IdentifiabilityStatus,
    InMemoryTwinStateRepository,
    ParameterIdentifiabilityAnalyzer,
    RealDataIntegrationError,
    RealDatasetManifest,
    TemporalAlignment,
    TwinSnapshot,
    TwinState,
    assess_calibration_readiness,
    assess_real_dataset,
    build_quality_report,
    plot_registration_status,
)
from agri_twin.domain import (
    AlignmentPolicy,
    DatasetRole,
    ObservationSourceType,
    ParameterReadinessStatus,
    ParameterRegistry,
    QualityFlag,
    ingest_rows,
)

ROOT = Path(__file__).resolve().parents[1]
IMPORTED_AT = datetime(2026, 6, 2, tzinfo=timezone.utc)


def _row(**overrides) -> dict:
    base = dict(
        timestamp="2026-06-01T10:00:00+00:00", variable="air_temperature", value="22.4", unit="degC",
        source="field_notebook", plot_id="EXT-PLOT-01", crop="tomato", variety="RAF", cycle_id="cycle_1",
        environment="GREENHOUSE",
    )
    base.update(overrides)
    return base


def _ingest(rows, **kwargs):
    return ingest_rows(rows, dataset_id="real-test", role=DatasetRole.CALIBRATION, source="field_notebook", source_type=ObservationSourceType.MEASURED, **kwargs)


# --- Dataset / manifest ----------------------------------------------------


def test_manifest_provenance_and_coverage():
    ingestion = _ingest([_row()])
    manifest = RealDatasetManifest.from_ingestion(
        ROOT, ingestion, dataset_id="first-real", source="field_notebook",
        collection_method="manual_field_record", imported_at=IMPORTED_AT,
    )
    assert manifest.provenance == "REAL_IMPORTED"
    assert manifest.source_type == "measured_data"
    assert manifest.crop_coverage == ("tomato",)
    assert manifest.variety_coverage == ("RAF",)
    assert manifest.cycle_coverage == ("cycle_1",)
    assert manifest.environment_coverage == ("GREENHOUSE",)
    assert manifest.units["air_temperature"] == "degC"


def test_manifest_requires_timezone_aware_imported_at():
    ingestion = _ingest([_row()])
    try:
        RealDatasetManifest.from_ingestion(
            ROOT, ingestion, dataset_id="bad", source="field_notebook",
            collection_method="manual_field_record", imported_at=datetime(2026, 6, 2),
        )
    except RealDataIntegrationError:
        return
    raise AssertionError("expected RealDataIntegrationError for naive imported_at")


def test_incomplete_metadata_preserved_as_unknown_not_invented():
    rows = [_row(variety="", cycle_id="")]
    del rows[0]["environment"]
    ingestion = _ingest(rows)
    observation = ingestion.dataset.observations[0]
    assert observation.variety is None
    assert observation.cycle_id is None
    assert observation.environment == "UNKNOWN"
    manifest = RealDatasetManifest.from_ingestion(
        ROOT, ingestion, dataset_id="incomplete", source="field_notebook",
        collection_method="manual_field_record", imported_at=IMPORTED_AT,
    )
    assert manifest.variety_coverage == ()
    assert manifest.cycle_coverage == ()


def test_unknown_plot_is_external_unregistered_and_not_blocked():
    assert plot_registration_status(ROOT, "EXT-PLOT-999") == "EXTERNAL_UNREGISTERED"
    assert plot_registration_status(ROOT, "plot_12010") == "REGISTERED"
    ingestion = _ingest([_row(plot_id="EXT-PLOT-999")])
    assert ingestion.dataset is not None  # ingestion never blocked by unregistered plot


# --- Units ------------------------------------------------------------------


def test_valid_unit_conversion_preserves_original_unit():
    ingestion = _ingest([_row(value="72.32", unit="degF")])
    observation = ingestion.dataset.observations[0]
    assert observation.unit == "degC"
    assert observation.unit_original == "degF"
    assert abs(observation.value - 22.4) < 0.01


def test_ambiguous_unit_is_flagged_unit_error_not_guessed():
    ingestion = _ingest([_row(unit="furlongs_per_fortnight")])
    assert ingestion.dataset is None
    assert any(issue.quality is QualityFlag.UNIT_ERROR for issue in ingestion.qc)


# --- Time -------------------------------------------------------------------


def test_missing_timezone_is_rejected_not_silently_assumed():
    ingestion = _ingest([_row(timestamp="2026-06-01T10:00:00")])
    assert ingestion.dataset is None
    assert ingestion.qc


def test_utc_normalization_of_explicit_offset():
    ingestion = _ingest([_row(timestamp="2026-06-01T12:00:00+02:00")])
    observation = ingestion.dataset.observations[0]
    assert observation.timestamp == datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


# --- Quality ------------------------------------------------------------


def test_quality_report_counts_missing_invalid_duplicate_out_of_range():
    rows = [
        _row(),
        _row(value=""),  # missing
        _row(variable="lai", value="-1", unit="m2_m-2"),  # out of range
        _row(variable="temperature_x", value="1", unit="degC"),  # invalid (unknown variable)
    ]
    ingestion = _ingest(rows)
    report = build_quality_report(ingestion)
    assert report.total_records == len(rows)
    assert report.missing_records >= 1 or report.invalid_records >= 1
    assert report.out_of_range_records >= 1


def test_duplicate_still_detected_without_cycle_id():
    ingestion = _ingest([_row(cycle_id=""), _row(cycle_id="")])
    report = build_quality_report(ingestion)
    assert report.duplicate_records == 1


# --- Deduplication respects cycle_id (Phase 5.18 audit finding) ------------


def test_deduplication_respects_cycle_id():
    rows = [_row(cycle_id="cycle_1"), _row(cycle_id="cycle_2")]
    ingestion = _ingest(rows)
    assert ingestion.dataset is not None
    assert len(ingestion.dataset.observations) == 2
    assert not ingestion.qc


# --- Context: crops, varieties, environments -------------------------------


def test_seven_crops_supported():
    for crop in ("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"):
        ingestion = _ingest([_row(crop=crop, variety=None, plot_id=f"EXT-{crop}")])
        assert ingestion.dataset is not None
        assert ingestion.dataset.observations[0].crop == crop


def test_known_varieties_preserved_no_invention():
    for crop, variety in (("tomato", "RAF"), ("pepper", "Lamuyo"), ("grape", "Monastrell"), ("plum", "Suplum 26")):
        ingestion = _ingest([_row(crop=crop, variety=variety, plot_id=f"EXT-{crop}")])
        assert ingestion.dataset.observations[0].variety == variety


def test_outdoor_and_greenhouse_environment_preserved():
    outdoor = _ingest([_row(environment="OUTDOOR")])
    greenhouse = _ingest([_row(environment="GREENHOUSE")])
    assert outdoor.dataset.observations[0].environment == "OUTDOOR"
    assert greenhouse.dataset.observations[0].environment == "GREENHOUSE"


# --- Alignment ---------------------------------------------------------


def _twin_repository() -> InMemoryTwinStateRepository:
    repository = InMemoryTwinStateRepository()
    state = TwinState(
        simulation_time=datetime(2026, 6, 1, 10, tzinfo=timezone.utc), plot_id="EXT-PLOT-01", cycle_id="cycle_1",
        crop="tomato", variety="RAF", cycle_status="ACTIVE", phenological_stage="vegetative_growth",
        temperature_c=21.0,
    )
    repository.save_snapshot(TwinSnapshot(state.simulation_time, (state,)))
    return repository


def test_temporal_alignment_exact_and_nearest():
    ingestion = _ingest([_row(timestamp="2026-06-01T10:30:00+00:00")])
    repository = _twin_repository()
    exact = assess_real_dataset(
        ROOT, ParameterRegistry.from_repository(ROOT), ingestion,
        RealDatasetManifest.from_ingestion(ROOT, ingestion, dataset_id="x", source="s", collection_method="manual_field_record", imported_at=IMPORTED_AT),
        build_quality_report(ingestion), twin_repository=repository, alignment=TemporalAlignment(policy=AlignmentPolicy.EXACT),
    )
    assert exact.comparison.matched_count == 0

    nearest = assess_real_dataset(
        ROOT, ParameterRegistry.from_repository(ROOT), ingestion,
        RealDatasetManifest.from_ingestion(ROOT, ingestion, dataset_id="x", source="s", collection_method="manual_field_record", imported_at=IMPORTED_AT),
        build_quality_report(ingestion), twin_repository=repository,
        alignment=TemporalAlignment(policy=AlignmentPolicy.NEAREST, max_time_delta_seconds=3600),
    )
    assert nearest.comparison.matched_count == 1


# --- Diagnostics ---------------------------------------------------------


def test_diagnostics_reused_from_phase_5_13():
    ingestion = _ingest([_row(timestamp="2026-06-01T10:00:00+00:00")])
    repository = _twin_repository()
    result = assess_real_dataset(
        ROOT, ParameterRegistry.from_repository(ROOT), ingestion,
        RealDatasetManifest.from_ingestion(ROOT, ingestion, dataset_id="x", source="s", collection_method="manual_field_record", imported_at=IMPORTED_AT),
        build_quality_report(ingestion), twin_repository=repository,
    )
    assert result.diagnostics is not None
    assert result.diagnostics.global_summary().matched_count == 1


def test_insufficient_data_is_a_valid_outcome():
    ingestion = _ingest([_row()])
    result = assess_real_dataset(
        ROOT, ParameterRegistry.from_repository(ROOT), ingestion,
        RealDatasetManifest.from_ingestion(ROOT, ingestion, dataset_id="x", source="s", collection_method="manual_field_record", imported_at=IMPORTED_AT),
        build_quality_report(ingestion),
    )
    assert result.comparison is None
    assert result.diagnostics is None
    assert result.pipeline_status == "REAL_DATA_INGESTION_VERIFIED"


# --- Identifiability -----------------------------------------------------


def test_identifiability_never_promotes_from_small_real_dataset():
    ingestion = _ingest([_row()])
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterIdentifiabilityAnalyzer(registry, repository_root=ROOT)
    report = analyzer.analyze_all(ingestion.dataset)
    assert not any(item.identifiability_status is IdentifiabilityStatus.IDENTIFIABLE for item in report.assessments)


def test_confounders_preserved_in_readiness_gate():
    ingestion = _ingest([_row()])
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterIdentifiabilityAnalyzer(registry, repository_root=ROOT)
    report = analyzer.analyze_all(ingestion.dataset)
    gate = assess_calibration_readiness(registry, ingestion.dataset, report)
    confounded = [item for item in report.assessments if item.confounders]
    if confounded:
        gate_by_id = {item.parameter_id: item for item in gate.records}
        assert gate_by_id[confounded[0].parameter_id].gate_status is ParameterReadinessStatus.NOT_READY


def test_calibration_readiness_gate_is_conservative_with_no_thresholds_invented():
    ingestion = _ingest([_row()])
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterIdentifiabilityAnalyzer(registry, repository_root=ROOT)
    report = analyzer.analyze_all(ingestion.dataset)
    gate = assess_calibration_readiness(registry, ingestion.dataset, report)
    assert isinstance(gate, CalibrationReadinessGate)
    assert gate.threshold_policy == "TO_BE_DEFINED"
    # a handful of real observations must never be enough to be ready for calibration
    assert not gate.ready_parameters()


# --- Scientific safeguards ------------------------------------------------


def test_no_calibration_performed():
    import agri_twin.application.real_data_integration as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("GridSearchCalibrator(", "CalibrationObjective(", ".optimize("):
        assert forbidden not in source


def test_parameter_registry_not_mutated():
    registry = ParameterRegistry.from_repository(ROOT)
    before = tuple(registry.records)
    ingestion = _ingest([_row()])
    assess_real_dataset(
        ROOT, registry, ingestion,
        RealDatasetManifest.from_ingestion(ROOT, ingestion, dataset_id="x", source="s", collection_method="manual_field_record", imported_at=IMPORTED_AT),
        build_quality_report(ingestion),
    )
    assert before == tuple(registry.records)


def test_twin_state_not_mutated_by_comparison():
    ingestion = _ingest([_row()])
    repository = _twin_repository()
    before = repository.history("EXT-PLOT-01", "cycle_1")
    assess_real_dataset(
        ROOT, ParameterRegistry.from_repository(ROOT), ingestion,
        RealDatasetManifest.from_ingestion(ROOT, ingestion, dataset_id="x", source="s", collection_method="manual_field_record", imported_at=IMPORTED_AT),
        build_quality_report(ingestion), twin_repository=repository,
    )
    after = repository.history("EXT-PLOT-01", "cycle_1")
    assert before == after


def test_reproducible_import_produces_identical_results():
    rows = [_row(), _row(cycle_id="cycle_2")]
    first = _ingest(rows)
    second = _ingest(rows)
    assert first.dataset.observations == second.dataset.observations
    assert build_quality_report(first) == build_quality_report(second)
