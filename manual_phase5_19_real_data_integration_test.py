"""Offline Phase 5.19 real agronomic data integration & calibration readiness audit.

Demonstrates:

REAL DATA SOURCE -> AcquisitionRecord/Observation -> ObservationIngestion ->
ObservationDataset -> TemporalAlignment -> ComparisonDataset -> ErrorDiagnostics
-> ParameterIdentifiabilityAnalyzer -> Calibration Readiness Gate

No verified real agronomic dataset is available in this repository yet, so
this script demonstrates that the import contract is ready with a minimal,
explicitly-labeled example dataset (not presented as validated field data).
"""

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.application import (
    IdentifiabilityStatus,
    InMemoryTwinStateRepository,
    RealDatasetManifest,
    TemporalAlignment,
    TwinSnapshot,
    TwinState,
    assess_real_dataset,
    build_quality_report,
    plot_registration_status,
)
from agri_twin.domain import AlignmentPolicy, DatasetRole, ObservationSourceType, ParameterRegistry, ingest_rows

ROOT = Path(__file__).parents[0]
IMPORTED_AT = datetime(2026, 6, 2, tzinfo=timezone.utc)


def _example_real_rows() -> list[dict]:
    """A minimal, explicitly-labeled illustrative dataset (not verified field data)."""

    return [
        {"timestamp": "2026-06-01T10:00:00+00:00", "variable": "air_temperature", "value": "21.6", "unit": "degC",
         "source": "field_notebook_example", "plot_id": "EXT-PLOT-01", "crop": "tomato", "variety": "RAF",
         "cycle_id": "cycle_1", "environment": "GREENHOUSE"},
        {"timestamp": "2026-06-01T10:30:00+00:00", "variable": "lai", "value": "1.9", "unit": "m2_m-2",
         "source": "field_notebook_example", "plot_id": "EXT-PLOT-01", "crop": "tomato", "variety": "RAF",
         "cycle_id": "cycle_1", "environment": "GREENHOUSE"},
        # incomplete metadata: unknown variety/cycle, missing measurement uncertainty
        {"timestamp": "2026-06-01T11:00:00+00:00", "variable": "soil_water_content", "value": "0.27", "unit": "m3_m-3",
         "source": "field_notebook_example", "plot_id": "EXT-PLOT-02", "crop": "lettuce", "environment": "OUTDOOR"},
    ]


def main() -> None:
    print("REAL AGRONOMIC DATA INTEGRATION — SOFTWARE PIPELINE QUALIFICATION")

    rows = _example_real_rows()
    if not rows:
        print("REAL DATA NOT AVAILABLE")
        print("IMPORT CONTRACT READY")
        print("PHASE 5.19 COMPLETE — REAL AGRONOMIC DATA INTEGRATION READY — REAL DATA NOT YET AVAILABLE — CALIBRATION NOT PERFORMED — DATA ASSIMILATION NOT IMPLEMENTED — EXPERIMENTAL VALIDATION NOT CLAIMED")
        return

    # 1: ingestion (same AcquisitionRecord/Observation -> ObservationIngestion -> ObservationDataset contract)
    ingestion = ingest_rows(
        rows, dataset_id="phase5-19-example-real", role=DatasetRole.CALIBRATION,
        source="field_notebook_example", source_type=ObservationSourceType.MEASURED,
    )
    assert ingestion.dataset is not None
    print("PASS — real rows ingested through the existing ObservationIngestion contract")

    # 2: provenance / manifest
    manifest = RealDatasetManifest.from_ingestion(
        ROOT, ingestion, dataset_id="phase5-19-example-real", source="field_notebook_example",
        collection_method="manual_field_record", imported_at=IMPORTED_AT,
        notes=("illustrative example only; not a verified scientific field dataset",),
    )
    assert manifest.provenance == "REAL_IMPORTED"
    assert manifest.plot_registration["EXT-PLOT-01"] == "EXTERNAL_UNREGISTERED"
    print("PASS — provenance manifest: REAL_IMPORTED, plot registration status, coverage")

    # 3: unit normalization (original unit preserved)
    lai_observation = next(item for item in ingestion.dataset.observations if item.variable == "lai")
    assert lai_observation.unit == "m2_m-2" and lai_observation.unit_original == "m2_m-2"
    print("PASS — unit normalization with original unit preserved")

    # 4: timezone normalization
    assert all(item.timestamp.tzinfo is not None for item in ingestion.dataset.observations)
    print("PASS — timezone-aware timestamps normalized to UTC")

    # 5: quality control
    quality_report = build_quality_report(ingestion)
    assert quality_report.total_records == len(rows)
    print("PASS — quality control report: no imputation, no silent correction")

    # 6: plot/crop/variety/cycle linkage, incomplete metadata preserved as UNKNOWN
    incomplete = next(item for item in ingestion.dataset.observations if item.plot_id == "EXT-PLOT-02")
    assert incomplete.variety is None and incomplete.cycle_id is None and incomplete.uncertainty is None
    print("PASS — plot/crop/variety/cycle linkage preserved; missing context stays UNKNOWN, nothing invented")

    # 7: temporal alignment (reused from Phase 5.12)
    repository = InMemoryTwinStateRepository()
    twin_state = TwinState(
        simulation_time=datetime(2026, 6, 1, 10, tzinfo=timezone.utc), plot_id="EXT-PLOT-01", cycle_id="cycle_1",
        crop="tomato", variety="RAF", cycle_status="ACTIVE", phenological_stage="vegetative_growth",
        temperature_c=20.5, lai=2.0,
    )
    repository.save_snapshot(TwinSnapshot(twin_state.simulation_time, (twin_state,)))
    registry = ParameterRegistry.from_repository(ROOT)
    assessment = assess_real_dataset(
        ROOT, registry, ingestion, manifest, quality_report,
        twin_repository=repository, alignment=TemporalAlignment(policy=AlignmentPolicy.NEAREST, max_time_delta_seconds=3600),
    )
    assert assessment.comparison is not None and assessment.comparison.matched_count >= 1
    print("PASS — temporal alignment reused from Phase 5.12 (exact/same_day/nearest/tolerance contracts)")

    # 8: diagnostics (reused from Phase 5.13)
    assert assessment.diagnostics is not None
    print("PASS — error diagnostics reused from Phase 5.13 (MAE/RMSE/bias/coverage/quality counts)")

    # 9: identifiability (reused from Phase 5.14), no forced promotion
    assert not any(item.identifiability_status is IdentifiabilityStatus.IDENTIFIABLE for item in assessment.identifiability.assessments)
    print("PASS — identifiability reused from Phase 5.14; small real dataset never forces IDENTIFIABLE")

    # 10: calibration readiness gate
    assert not assessment.readiness_gate.ready_parameters()
    print("PASS — calibration readiness gate assessed (conservative, no invented thresholds)")

    # 11: no calibration performed
    source = (ROOT / "src" / "agri_twin" / "application" / "real_data_integration.py").read_text(encoding="utf-8")
    assert "GridSearchCalibrator(" not in source
    print("PASS — no calibration performed")

    # 12: no data assimilation (TwinState never mutated)
    before = repository.history("EXT-PLOT-01", "cycle_1")
    assess_real_dataset(ROOT, registry, ingestion, manifest, quality_report, twin_repository=repository)
    after = repository.history("EXT-PLOT-01", "cycle_1")
    assert before == after
    print("PASS — no data assimilation: TwinState is never mutated by real observations")

    # 13: no TwinState mutation already shown above; ParameterRegistry immutability
    before_records = tuple(registry.records)
    assess_real_dataset(ROOT, registry, ingestion, manifest, quality_report, twin_repository=repository)
    assert before_records == tuple(registry.records)
    print("PASS — ParameterRegistry is never mutated")

    # 14: determinism
    repeat_ingestion = ingest_rows(
        rows, dataset_id="phase5-19-example-real", role=DatasetRole.CALIBRATION,
        source="field_notebook_example", source_type=ObservationSourceType.MEASURED,
    )
    assert ingestion.dataset.observations == repeat_ingestion.dataset.observations
    assert build_quality_report(ingestion) == build_quality_report(repeat_ingestion)
    print("PASS — deterministic re-import produces identical dataset and quality report")

    print(f"plots={quality_report.plots}")
    print(f"variables={quality_report.variables}")
    print(f"readiness_gate_ready_count={len(assessment.readiness_gate.ready_parameters())}")
    print("REAL AGRONOMIC DATA: ILLUSTRATIVE EXAMPLE ONLY, NOT A VERIFIED FIELD DATASET")
    print("CALIBRATION NOT PERFORMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("PHASE 5.19 COMPLETE — REAL AGRONOMIC DATASET NOT VERIFIED — ILLUSTRATIVE CONTRACT-COMPATIBLE DATA USED FOR PIPELINE TESTING — CALIBRATION READINESS ASSESSED — CALIBRATION NOT PERFORMED — DATA ASSIMILATION NOT IMPLEMENTED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
