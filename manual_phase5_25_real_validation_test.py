"""Offline delivery verification for Phase 5.25."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.application.real_validation import (
    DataSourceClassification,
    RealValidationSuite,
    ValidationReadiness,
    ValidationScope,
)
from agri_twin.domain.calibration import ParameterSet, SimulationPoint
from agri_twin.domain.validation import AlignmentPolicy, ValidationCase

ROOT = Path(__file__).resolve().parent
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def main() -> None:
    suite = RealValidationSuite(ROOT)
    sources = suite.audit_sources()
    assert suite.assess_readiness(sources) is ValidationReadiness.INSUFFICIENT_REAL_DATA
    assert not any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources)

    rows = [{
        "timestamp": "2026-01-01T12:00:00+00:00",
        "variable": "lai",
        "value": "1.0",
        "unit": "m2_m-2",
        "source": "synthetic_validation_fixture",
        "plot_id": "plot_12010",
        "crop": "tomato",
        "variety": "RAF",
        "cycle_id": "cycle_1",
        "environment": "GREENHOUSE",
    }]
    ingestion = suite.ingest_fixture(rows)
    case = ValidationCase("tomato", "RAF", "plot_12010", START, END, ingestion.dataset, ParameterSet((), "fixture"), alignment=AlignmentPolicy.EXACT)

    def runner(_case):
        return (SimulationPoint(datetime(2026, 1, 1, 12, tzinfo=timezone.utc), {"lai": 1.1}, {"lai": "m2_m-2"}),)

    result = suite.evaluate(case, source_status=DataSourceClassification.SYNTHETIC, scope=ValidationScope.OUT_OF_SAMPLE, runner=runner)
    assert result.readiness is ValidationReadiness.INSUFFICIENT_REAL_DATA
    report = suite.build_report(result)
    repeated_suite = RealValidationSuite(ROOT)
    repeated_ingestion = repeated_suite.ingest_fixture(rows)
    repeated_case = ValidationCase("tomato", "RAF", "plot_12010", START, END, repeated_ingestion.dataset, ParameterSet((), "fixture"), alignment=AlignmentPolicy.EXACT)
    repeated_result = repeated_suite.evaluate(repeated_case, source_status=DataSourceClassification.SYNTHETIC, scope=ValidationScope.OUT_OF_SAMPLE, runner=runner)
    repeated = repeated_suite.build_report(repeated_result)
    assert report.real_data_verified is False
    assert report.experimental_validation_status == "NOT_CLAIMED"
    assert report.configuration_hash == repeated.configuration_hash
    paths = suite.write_report(report)
    assert all(path.exists() for path in paths)

    print("=" * 80)
    print("PHASE 5.25 COMPLETE")
    print("REAL VALIDATION FRAMEWORK READY")
    print("VALIDATION PIPELINE QUALIFIED ON SYNTHETIC FIXTURES")
    print("REAL AGRONOMIC DATA NOT VERIFIED")
    print("INSUFFICIENT REAL DATA FOR SCIENTIFIC VALIDATION")
    print("CALIBRATION NOT PERFORMED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print(f"sources={len(sources)} synthetic_fixture_status={report.synthetic_fixture_status}")
    print(f"configuration_hash={report.configuration_hash[:16]}...")
    print("=" * 80)


if __name__ == "__main__":
    main()
