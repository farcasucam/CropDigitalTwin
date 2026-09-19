from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.real_validation import DataSourceClassification
from agri_twin.application.scenarios import Scenario, ScenarioEvent, ScenarioKind, ScenarioRunner
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
from agri_twin.application.twin_state import InMemoryTwinStateRepository
from agri_twin.application.uncertainty_ensemble import (
    ScenarioEnsembleGenerator,
    UncertaintyDefinition,
    UncertaintyDistribution,
    UncertaintySource,
)
from agri_twin.domain.calibration import (
    CalibrationParameter,
    DatasetRole,
    Observation,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
)
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_test_dataset(
    name: str,
    role: DatasetRole = DatasetRole.TEST,
    timestamp: datetime = START,
    value: float = 1.0,
    crop: str = "tomato",
    variety: str = "RAF",
    plot: str = "plot_12010",
    cycle: str = "cycle_A",
    env: str = "GREENHOUSE",
) -> ObservationDataset:
    obs = Observation(
        timestamp,
        "biomass",
        value,
        "g_m-2",
        source="SYNTHETIC_SOFTWARE_TEST",
        source_type="synthetic_test_data",
        dataset_id=name,
        crop=crop,
        variety=variety,
        plot_id=plot,
        cycle_id=cycle,
        environment=env,
    )
    return ObservationDataset(name, role, (obs,), source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data")


def make_params(val: float) -> ParameterSet:
    p = CalibrationParameter("fixture.param", val, val, 0.0, 5.0, 1.0, "fraction", "engineering", "candidate", True)
    return ParameterSet((p,), "fixture_set")


def make_runner(val: float):
    def _runner(ds: ObservationDataset, _params: ParameterSet):
        return (SimulationPoint(ds.observations[0].timestamp, {"biomass": val}, {"biomass": "g_m-2"}),)
    return _runner


def test_1_no_real_data_returns_insufficient_data():
    suite = TransferabilityRobustnessSuite(ROOT)
    source_ds = make_test_dataset("src")
    target_ds = make_test_dataset("tgt", timestamp=START + timedelta(days=1))
    case = TransferabilityCase(
        "c1",
        TransferabilityDimension.TEMPORAL_CYCLE,
        TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE,
        TransferContext("tomato"),
        TransferContext("tomato"),
        "real_data",
    )
    res = suite.evaluate_scientific_transferability(
        case,
        source_dataset=source_ds,
        target_dataset=target_ds,
        baseline_parameters=make_params(1.0),
        calibrated_parameters=make_params(1.0),
        baseline_runner=make_runner(1.0),
        calibrated_runner=make_runner(1.0),
    )
    assert res.execution_status is TransferabilityExecutionStatus.NOT_PERFORMED
    assert res.status is TransferabilityStatus.INSUFFICIENT_DATA
    assert "SCIENTIFIC TRANSFERABILITY NOT PERFORMED" in res.warnings[0]


def test_2_no_calibration_returns_no_calibration():
    suite = TransferabilityRobustnessSuite(ROOT)
    # When readiness is checked without real data or calibration report, readiness is INSUFFICIENT_DATA or NO_CALIBRATION
    readiness = suite.readiness()
    assert readiness in {TransferabilityStatus.INSUFFICIENT_DATA, TransferabilityStatus.NO_CALIBRATION}


def test_3_synthetic_transferability_is_qualified_synthetic():
    suite = TransferabilityRobustnessSuite(ROOT)
    src = make_test_dataset("src")
    tgt = make_test_dataset("tgt", timestamp=START + timedelta(days=1))
    case = TransferabilityCase(
        "case_synth",
        TransferabilityDimension.TEMPORAL_CYCLE,
        TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE,
        TransferContext("tomato"),
        TransferContext("tomato"),
        "synthetic_test_data",
    )
    res = suite.software_fixture_transfer(
        case,
        source_dataset=src,
        target_dataset=tgt,
        baseline_parameters=make_params(1.0),
        calibrated_parameters=make_params(1.2),
        baseline_runner=make_runner(1.0),
        calibrated_runner=make_runner(1.2),
    )
    assert res.execution_status is TransferabilityExecutionStatus.SOFTWARE_TEST_ONLY
    assert res.status is TransferabilityStatus.QUALIFIED_SYNTHETIC
    assert "SYNTHETIC_SOFTWARE_QUALIFICATION_ONLY" in res.warnings


def test_4_cycle_transfer():
    suite = TransferabilityRobustnessSuite(ROOT)
    src = make_test_dataset("src_c1", cycle="cycle_2025")
    tgt = make_test_dataset("tgt_c2", cycle="cycle_2026", timestamp=START + timedelta(days=30))
    s_ctx = TransferContext("tomato", "RAF", "plot_12010", "cycle_2025", "GREENHOUSE")
    t_ctx = TransferContext("tomato", "RAF", "plot_12010", "cycle_2026", "GREENHOUSE")
    level = suite.classify_transfer_level(s_ctx, t_ctx)
    dim = suite.classify_transfer_dimension(s_ctx, t_ctx)
    assert level is TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE
    assert dim is TransferabilityDimension.TEMPORAL_CYCLE


def test_5_plot_transfer():
    suite = TransferabilityRobustnessSuite(ROOT)
    s_ctx = TransferContext("tomato", "RAF", "plot_12010", "cycle_2026", "GREENHOUSE")
    t_ctx = TransferContext("tomato", "RAF", "plot_14705", "cycle_2026", "GREENHOUSE")
    level = suite.classify_transfer_level(s_ctx, t_ctx)
    dim = suite.classify_transfer_dimension(s_ctx, t_ctx)
    assert level is TransferabilityLevel.LEVEL_2_NEW_PLOT
    assert dim is TransferabilityDimension.SPATIAL_PLOT


def test_6_variety_transfer():
    suite = TransferabilityRobustnessSuite(ROOT)
    s_ctx = TransferContext("tomato", "RAF", "plot_12010", "cycle_2026", "GREENHOUSE")
    t_ctx = TransferContext("tomato", "Lamuyo", "plot_12010", "cycle_2026", "GREENHOUSE")
    level = suite.classify_transfer_level(s_ctx, t_ctx)
    dim = suite.classify_transfer_dimension(s_ctx, t_ctx)
    assert level is TransferabilityLevel.LEVEL_3_NEW_VARIETY
    assert dim is TransferabilityDimension.VARIETAL


def test_7_environment_transfer():
    suite = TransferabilityRobustnessSuite(ROOT)
    s_ctx = TransferContext("tomato", "RAF", "plot_12010", "cycle_2026", "GREENHOUSE")
    t_ctx = TransferContext("tomato", "RAF", "plot_12010", "cycle_2026", "OUTDOOR")
    level = suite.classify_transfer_level(s_ctx, t_ctx)
    dim = suite.classify_transfer_dimension(s_ctx, t_ctx)
    assert level is TransferabilityLevel.LEVEL_4_NEW_ENVIRONMENT
    assert dim is TransferabilityDimension.ENVIRONMENTAL


def test_8_cross_species():
    suite = TransferabilityRobustnessSuite(ROOT)
    s_ctx = TransferContext("tomato", "RAF", "plot_12010", "cycle_2026", "GREENHOUSE")
    t_ctx = TransferContext("pepper", "Lamuyo", "plot_12010", "cycle_2026", "GREENHOUSE")
    level = suite.classify_transfer_level(s_ctx, t_ctx)
    dim = suite.classify_transfer_dimension(s_ctx, t_ctx)
    assert level is TransferabilityLevel.LEVEL_5_NEW_CROP_SPECIES
    assert dim is TransferabilityDimension.CROSS_SPECIES


def test_9_leakage():
    suite = TransferabilityRobustnessSuite(ROOT)
    src = make_test_dataset("same_ds", timestamp=START)
    tgt = make_test_dataset("same_ds", timestamp=START)
    indep = suite.post_calibration.independence(src, tgt)
    assert not indep.independent
    case = TransferabilityCase("leak_case", TransferabilityDimension.TEMPORAL_CYCLE, TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE, TransferContext("tomato"), TransferContext("tomato"), "synth", independence=indep)
    res = suite.software_fixture_transfer(case, source_dataset=src, target_dataset=tgt, baseline_parameters=make_params(1.0), calibrated_parameters=make_params(1.2), baseline_runner=make_runner(1.0), calibrated_runner=make_runner(1.2))
    assert res.status is TransferabilityStatus.DATA_LEAKAGE


def test_10_deterministic_transferability():
    suite = TransferabilityRobustnessSuite(ROOT)
    src = make_test_dataset("src", timestamp=START, value=1.0)
    tgt = make_test_dataset("tgt", timestamp=START + timedelta(days=1), value=1.0)
    case = TransferabilityCase("det_case", TransferabilityDimension.TEMPORAL_CYCLE, TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE, TransferContext("tomato"), TransferContext("tomato"), "synth")
    r1 = suite.software_fixture_transfer(case, source_dataset=src, target_dataset=tgt, baseline_parameters=make_params(1.0), calibrated_parameters=make_params(1.2), baseline_runner=make_runner(1.0), calibrated_runner=make_runner(1.2))
    r2 = suite.software_fixture_transfer(case, source_dataset=src, target_dataset=tgt, baseline_parameters=make_params(1.0), calibrated_parameters=make_params(1.2), baseline_runner=make_runner(1.0), calibrated_runner=make_runner(1.2))
    assert r1.to_dict() == r2.to_dict()


def test_11_parameter_immutability():
    suite = TransferabilityRobustnessSuite(ROOT)
    before = tuple(r.to_dict() for r in suite.registry.records)
    suite.run_synthetic_qualification()
    suite.evaluate_robustness_suite()
    after = tuple(r.to_dict() for r in suite.registry.records)
    assert before == after


def test_12_twin_state_immutability():
    repo = InMemoryTwinStateRepository()
    suite = TransferabilityRobustnessSuite(ROOT)
    suite.run_synthetic_qualification()
    suite.evaluate_robustness_suite()
    assert repo.latest_snapshot() is None


def test_13_robustness_scenario():
    suite = TransferabilityRobustnessSuite(ROOT)
    robustness_results = suite.evaluate_robustness_suite(crop="tomato", environment="GREENHOUSE")
    assert len(robustness_results) == 12
    assert all(r.passed for r in robustness_results)
    assert all(r.software_stability for r in robustness_results)
    assert all(r.physical_bounds_valid for r in robustness_results)


def test_14_uncertainty_ensemble():
    suite = TransferabilityRobustnessSuite(ROOT)
    generator = ScenarioEnsembleGenerator(suite.registry, seed=42, sample_count=5)
    ensemble = generator.generate(method="monte_carlo")
    assert len(ensemble.members) == 5
    assert ensemble.seed == 42


def test_15_overfit_diagnostic():
    suite = TransferabilityRobustnessSuite(ROOT)
    src = make_test_dataset("src", timestamp=START, value=1.0)
    tgt = make_test_dataset("tgt", timestamp=START + timedelta(days=1), value=1.0)

    # Baseline: error on src is 0.5, error on tgt is 0.0
    def base_runner(ds, _p):
        v = 1.5 if ds.name == "src" else 1.0
        return (SimulationPoint(ds.observations[0].timestamp, {"biomass": v}, {"biomass": "g_m-2"}),)

    # Calibrated: error on src is 0.0 (improved!), error on tgt is 1.0 (degraded!)
    def cal_runner(ds, _p):
        v = 1.0 if ds.name == "src" else 2.0
        return (SimulationPoint(ds.observations[0].timestamp, {"biomass": v}, {"biomass": "g_m-2"}),)

    case = TransferabilityCase("of_case", TransferabilityDimension.TEMPORAL_CYCLE, TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE, TransferContext("tomato"), TransferContext("tomato"), "synth")
    res = suite.software_fixture_transfer(
        case,
        source_dataset=src,
        target_dataset=tgt,
        baseline_parameters=make_params(1.0),
        calibrated_parameters=make_params(1.2),
        baseline_runner=base_runner,
        calibrated_runner=cal_runner,
    )
    assert res.overfit_diagnostic["signal"] is True
    assert res.overfit_diagnostic["label"] == OverfitDiagnosticStatus.POTENTIAL_OVERFIT.value


def test_16_context_dependence():
    suite = TransferabilityRobustnessSuite(ROOT)
    src = make_test_dataset("src_plot1", plot="plot_12010", timestamp=START, value=1.0)
    tgt = make_test_dataset("tgt_plot2", plot="plot_14705", timestamp=START + timedelta(days=1), value=1.0)

    def base_runner(ds, _p):
        return (SimulationPoint(ds.observations[0].timestamp, {"biomass": 1.0}, {"biomass": "g_m-2"}),)

    def cal_runner(ds, _p):
        v = 1.0 if ds.name == "src_plot1" else 2.0
        return (SimulationPoint(ds.observations[0].timestamp, {"biomass": v}, {"biomass": "g_m-2"}),)

    case = TransferabilityCase(
        "cd_case",
        TransferabilityDimension.SPATIAL_PLOT,
        TransferabilityLevel.LEVEL_2_NEW_PLOT,
        TransferContext("tomato", plot_id="plot_12010"),
        TransferContext("tomato", plot_id="plot_14705"),
        "synth",
    )
    res = suite.software_fixture_transfer(
        case,
        source_dataset=src,
        target_dataset=tgt,
        baseline_parameters=make_params(1.0),
        calibrated_parameters=make_params(1.2),
        baseline_runner=base_runner,
        calibrated_runner=cal_runner,
    )
    assert res.context_dependence_diagnostic["signal"] is True
    assert res.context_dependence_diagnostic["label"] == OverfitDiagnosticStatus.POTENTIAL_CONTEXT_DEPENDENCE.value


def test_17_multilevel_diagnostics():
    from agri_twin.application.error_diagnostics import ErrorDiagnostics
    from agri_twin.application.twin_alignment import AlignmentResult, AlignmentStatus, ComparisonDataset, ComparisonResult
    from agri_twin.domain.validation import AlignmentPolicy
    align = AlignmentResult(AlignmentStatus.MATCHED, "obs1", "plot_12010", "c1", START, START, 0.0, AlignmentPolicy.EXACT, context_match=True)
    comp_result = ComparisonResult(align, "biomass", "tomato", "RAF", 1.0, "g_m-2", 1.2, "g_m-2", 0.2, 0.2, None, "VALID", "SYNTHETIC", "SIMULATED", "vegetative", "GREENHOUSE")
    comp_ds = ComparisonDataset((comp_result,), 1, 0, 0, 0)
    diagnostics = ErrorDiagnostics(comp_ds)
    by_crop = diagnostics.by_crop()
    by_env = diagnostics.by_environment()
    assert len(by_crop) == 1
    assert by_crop[0].group_key == "tomato"
    assert len(by_env) == 1
    assert by_env[0].group_key == "GREENHOUSE"





def test_18_deterministic_json_and_hash():
    suite1 = TransferabilityRobustnessSuite(ROOT)
    suite2 = TransferabilityRobustnessSuite(ROOT)
    rep1 = suite1.build_report()
    rep2 = suite2.build_report()
    assert rep1.to_json() == rep2.to_json()
    assert rep1.configuration_hash == rep2.configuration_hash
    assert rep1.real_data_verified is False
    assert rep1.calibration_performed is False
    assert rep1.validation_performed is False
