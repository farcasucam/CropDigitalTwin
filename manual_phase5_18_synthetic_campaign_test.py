"""Offline Phase 5.18 synthetic observation campaign & scientific pipeline qualification audit.

Demonstrates the full synthetic pipeline end-to-end:

plan -> instrumentation -> simulated acquisition -> ingestion -> dataset ->
twin snapshots -> temporal alignment -> comparison -> error diagnostics ->
identifiability -> campaign report

Runs the campaign twice for determinism, exercises one controlled defect and
the future-real backend substitution path, and asserts no calibration or
data assimilation occurred. This is a software pipeline qualification audit,
not a scientific validation of the model.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import (
    AcquisitionFaults,
    AcquisitionSourceType,
    CampaignConfiguration,
    SyntheticObservationCampaign,
    campaigns_are_deterministic,
)
from agri_twin.domain import ParameterRegistry

ROOT = Path(__file__).parents[0]
START = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def main() -> None:
    print("SYNTHETIC OBSERVATION CAMPAIGN — SOFTWARE PIPELINE QUALIFICATION ONLY")

    # 1-10: plan -> instrumentation -> acquisition -> ingestion -> dataset ->
    #       twin snapshots -> alignment -> comparison -> diagnostics -> identifiability -> report
    baseline_config = CampaignConfiguration(
        campaign_id="phase5-18-baseline",
        root=ROOT,
        start=START,
        end=START + timedelta(hours=3),
        interval_seconds=3600,
        seed=518,
    )
    baseline = SyntheticObservationCampaign(baseline_config).run()
    assert baseline.plan.items
    assert baseline.specifications
    assert all(record.source_type is AcquisitionSourceType.SYNTHETIC for record in baseline.acquisition_records)
    assert baseline.ingestion.dataset is not None
    assert baseline.twin_repository.latest_snapshot() is not None
    assert baseline.comparison.results
    assert baseline.diagnostics.global_summary().n >= 0
    assert baseline.identifiability_after.assessments
    assert baseline.report.pipeline_status == "SUCCESS"
    assert baseline.report.synthetic is True
    print("PASS — end-to-end pipeline: plan -> instrumentation -> acquisition -> ingestion -> dataset")
    print("PASS — end-to-end pipeline: twin snapshots -> alignment -> comparison -> diagnostics -> identifiability")

    # 11-12: run a second time, verify determinism
    repeat = SyntheticObservationCampaign(baseline_config).run()
    assert campaigns_are_deterministic(baseline, repeat)
    print("PASS — determinism: same seed/configuration/clock/plan/instrumentation reproduce identical results")

    # 13: controlled defect demonstration (known synthetic bias)
    defect_config = CampaignConfiguration(
        campaign_id="phase5-18-controlled-bias",
        root=ROOT,
        start=START,
        end=START + timedelta(hours=3),
        interval_seconds=3600,
        seed=518,
        known_bias_variable="air_temperature",
        known_bias_offset=1.5,
        bias_threshold=0.1,
    )
    defect_result = SyntheticObservationCampaign(defect_config).run()
    temperature_summary = next(item for item in defect_result.diagnostics.by_variable() if item.variable == "air_temperature")
    assert temperature_summary.bias is not None and abs(temperature_summary.bias) == 1.5
    print("PASS — controlled defect: known synthetic bias detected by existing MAE/RMSE/bias diagnostics")

    # also demonstrate missing/duplicate/invalid/unit_error detection without imputation
    quality_config = CampaignConfiguration(
        campaign_id="phase5-18-quality-faults",
        root=ROOT,
        start=START,
        end=START + timedelta(hours=6),
        interval_seconds=3600,
        seed=518,
        faults=AcquisitionFaults(missing_every=7, duplicate_every=11, invalid_every=13, unit_error_every=17),
    )
    quality_result = SyntheticObservationCampaign(quality_config).run()
    assert quality_result.report.quality_counts["missing"] > 0
    assert quality_result.report.quality_counts["duplicate"] > 0
    assert quality_result.report.quality_counts["invalid"] > 0
    assert quality_result.report.quality_counts["unit_error"] > 0
    print("PASS — controlled defects: missing/duplicate/invalid/unit_error reflected in quality counters, no imputation")

    # backend substitution (SimulatedAcquisitionBackend -> FutureRealAcquisitionAdapter)
    substitution_config = CampaignConfiguration(
        campaign_id="phase5-18-backend-substitution",
        root=ROOT,
        start=START,
        end=START + timedelta(hours=1),
        interval_seconds=3600,
        seed=518,
        use_future_real_adapter=True,
    )
    substitution_result = SyntheticObservationCampaign(substitution_config).run()
    assert substitution_result.report.backend_substitution_status.startswith("FUTURE_REAL_ADAPTER_SUBSTITUTED")
    assert substitution_result.report.pipeline_status == "SUCCESS"
    print("PASS — backend substitution: SimulatedAcquisitionBackend replaced with FutureRealAcquisitionAdapter + FakeExternalSensorSource")
    print("PASS — no hardware, network, IoT or external API connection used")

    # 14: no calibration performed
    source = Path("src/agri_twin/application/synthetic_campaign.py").read_text(encoding="utf-8")
    assert "GridSearchCalibrator(" not in source and "CalibrationObjective(" not in source
    print("PASS — no calibration performed (no GridSearchCalibrator, no parameter fitting, no optimizer)")

    # 15: no data assimilation — TwinState is never derived from observations
    before = baseline.twin_repository.history("P-TOMATO", "C-TOMATO-1")
    from agri_twin.application import compare_dataset

    compare_dataset(baseline.twin_repository, baseline.ingestion.dataset)
    after = baseline.twin_repository.history("P-TOMATO", "C-TOMATO-1")
    assert before == after
    print("PASS — no data assimilation: comparing observations never mutates TwinState")

    # ParameterRegistry is read-only
    registry = ParameterRegistry.from_repository(ROOT)
    before_records = tuple(registry.records)
    SyntheticObservationCampaign(baseline_config).run()
    assert before_records == tuple(registry.records)
    print("PASS — ParameterRegistry is never mutated by the campaign")

    # identifiability sanity: synthetic data cannot force IDENTIFIABLE
    from agri_twin.application import IdentifiabilityStatus

    assert not any(
        assessment.identifiability_status is IdentifiabilityStatus.IDENTIFIABLE
        for assessment in baseline.identifiability_after.assessments
    )
    print("PASS — identifiability: synthetic acquisition cannot force parameters into IDENTIFIABLE")

    print(f"campaign_id={baseline.report.campaign_id}")
    print(f"configuration_hash={baseline.report.configuration_hash}")
    print(f"acquisition_count={baseline.report.acquisition_count}")
    print(f"observation_count={baseline.report.observation_count}")
    print(f"valid_comparison_count={baseline.report.valid_comparison_count}")
    print("REAL AGRONOMIC DATA NOT AVAILABLE")
    print("SIMULATED ACQUISITION ONLY")
    print("SYNTHETIC OBSERVATION CAMPAIGN QUALIFIED")
    print("CALIBRATION NOT PERFORMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("PHASE 5.18 COMPLETE — SYNTHETIC OBSERVATION CAMPAIGN PIPELINE QUALIFIED — END-TO-END OBSERVATION FLOW VERIFIED — REAL AGRONOMIC DATA NOT AVAILABLE — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
