"""Offline delivery verification for Phase 5.28: Transferability, Robustness and Generalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application.transferability_robustness import (
    OverfitDiagnosticStatus,
    RobustnessDimension,
    TransferabilityCase,
    TransferabilityDimension,
    TransferabilityExecutionStatus,
    TransferabilityLevel,
    TransferabilityRobustnessSuite,
    TransferabilityStatus,
    TransferContext,
)
from agri_twin.domain.calibration import (
    CalibrationParameter,
    DatasetRole,
    Observation,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
)

ROOT = Path(__file__).resolve().parent
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture(name: str, role: DatasetRole, timestamp: datetime, value: float = 1.0) -> ObservationDataset:
    observation = Observation(
        timestamp,
        "biomass",
        value,
        "g_m-2",
        source="SYNTHETIC_SOFTWARE_TEST",
        source_type="synthetic_test_data",
        dataset_id=name,
        crop="tomato",
        variety="RAF",
        plot_id="plot_12010",
        cycle_id=name,
        environment="GREENHOUSE",
    )
    return ObservationDataset(name, role, (observation,), source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data")


def main() -> None:
    suite = TransferabilityRobustnessSuite(ROOT)

    # 1. Audit sources and check Phase 5.26 / 5.27 reports
    sources = suite.audit_sources()
    real_verified = any(source.classification.value == "REAL_VERIFIED" for source in sources)
    cal_report = suite.calibration_report()
    post_val_report = suite.post_calibration_report()

    assert not real_verified, "No REAL_VERIFIED sources should exist currently"
    assert cal_report.get("calibration_performed") is False
    assert post_val_report.get("validation_performed") is False

    # 2. Readiness check
    readiness = suite.readiness()
    assert readiness is TransferabilityStatus.INSUFFICIENT_DATA

    # 3. Scientific transferability blocks without real data
    src_ds = fixture("src_cal", DatasetRole.CALIBRATION, START)
    tgt_ds = fixture("tgt_trans", DatasetRole.TEST, START + timedelta(days=1))
    case = TransferabilityCase(
        "case_e2e",
        TransferabilityDimension.TEMPORAL_CYCLE,
        TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE,
        TransferContext("tomato", "RAF", "plot_12010", "cycle_1", "GREENHOUSE"),
        TransferContext("tomato", "RAF", "plot_12010", "cycle_2", "GREENHOUSE"),
        "real_substitute",
    )

    def dummy_runner(ds, _p):
        return (SimulationPoint(ds.observations[0].timestamp, {"biomass": 1.0}, {"biomass": "g_m-2"}),)

    dummy_params = ParameterSet((CalibrationParameter("test.param", 1.0, 1.0, 0.0, 2.0, 0.1, "", "eng", "cand", True),), "params")

    res_scientific = suite.evaluate_scientific_transferability(
        case,
        source_dataset=src_ds,
        target_dataset=tgt_ds,
        baseline_parameters=dummy_params,
        calibrated_parameters=dummy_params,
        baseline_runner=dummy_runner,
        calibrated_runner=dummy_runner,
    )
    assert res_scientific.execution_status is TransferabilityExecutionStatus.NOT_PERFORMED
    assert res_scientific.status is TransferabilityStatus.INSUFFICIENT_DATA

    # 4. Synthetic transferability qualification
    res_synthetic = suite.software_fixture_transfer(
        case,
        source_dataset=src_ds,
        target_dataset=tgt_ds,
        baseline_parameters=dummy_params,
        calibrated_parameters=dummy_params,
        baseline_runner=dummy_runner,
        calibrated_runner=dummy_runner,
    )
    assert res_synthetic.execution_status is TransferabilityExecutionStatus.SOFTWARE_TEST_ONLY
    assert res_synthetic.status is TransferabilityStatus.QUALIFIED_SYNTHETIC

    # 5. Robustness stress suite
    robustness_results = suite.evaluate_robustness_suite()
    assert len(robustness_results) == 12
    assert all(r.passed for r in robustness_results)

    # 6. Leakage detection
    leaked_indep = suite.post_calibration.independence(src_ds, src_ds)
    leaked_case = TransferabilityCase(
        "leak_case",
        TransferabilityDimension.TEMPORAL_CYCLE,
        TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE,
        TransferContext("tomato"),
        TransferContext("tomato"),
        "synth",
        independence=leaked_indep,
    )
    res_leaked = suite.software_fixture_transfer(
        leaked_case,
        source_dataset=src_ds,
        target_dataset=src_ds,
        baseline_parameters=dummy_params,
        calibrated_parameters=dummy_params,
        baseline_runner=dummy_runner,
        calibrated_runner=dummy_runner,
    )
    assert res_leaked.status is TransferabilityStatus.DATA_LEAKAGE

    # 7. Immutability
    before_records = tuple(r.to_dict() for r in suite.registry.records)
    suite.run_synthetic_qualification()
    assert tuple(r.to_dict() for r in suite.registry.records) == before_records

    # 8. Report build and write
    report = suite.build_report()
    repeated_report = suite.build_report()
    assert report.to_json() == repeated_report.to_json()
    assert report.configuration_hash == repeated_report.configuration_hash

    report_path, readme_path = suite.write_report(report)
    assert report_path.exists()
    assert readme_path.exists()

    print("=" * 80)
    print("PHASE 5.28 COMPLETE")
    print("TRANSFERABILITY PIPELINE READY")
    print("ROBUSTNESS PIPELINE READY")
    print("GENERALIZATION PIPELINE READY")
    print("SCIENTIFIC TRANSFERABILITY NOT ASSESSED — INSUFFICIENT REAL DATA")
    print("SYNTHETIC TRANSFERABILITY TESTS QUALIFIED AS SOFTWARE TESTS ONLY")
    print("REAL AGRICULTURAL DATA NOT VERIFIED")
    print("BIOLOGICAL ROBUSTNESS NOT CLAIMED")
    print("EXPERIMENTAL GENERALIZATION NOT CLAIMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("independence=PASS leakage_detection=PASS determinism=PASS immutability=PASS")
    print("PASS")
    print("=" * 80)


if __name__ == "__main__":
    main()

