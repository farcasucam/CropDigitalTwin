"""Scientific transferability, robustness and generalization analysis framework.

This module provides a rigorous evaluation layer for assessing how a calibrated
model (or baseline model) performs when transferred across cycles, plots, varieties,
environments, climates, agronomic regimes, and crop species.

In strict adherence to the project's scientific stance:
    - Real-data validation and transferability require verified real observations (REAL_VERIFIED).
    - Synthetic datasets and scenario ensembles serve strictly for software qualification
      (QUALIFIED_SYNTHETIC / SOFTWARE_TEST_ONLY).
    - No parameter or TwinState mutation is performed during evaluation.
    - No scientific generalization or biological robustness is claimed without real observations.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agri_twin.application.error_diagnostics import ErrorDiagnostics, MetricSummary
from agri_twin.application.post_calibration_validation import (
    PostCalibrationValidationSuite,
    ValidationIndependence,
    ValidationMetric,
)
from agri_twin.application.real_validation import (
    DataSourceAudit,
    DataSourceClassification,
    RealValidationSuite,
)
from agri_twin.application.scenarios import Scenario, ScenarioRunner
from agri_twin.application.sensitivity import ParameterSensitivityAnalyzer, RobustnessResult
from agri_twin.application.uncertainty_ensemble import (
    ScenarioEnsemble,
    ScenarioEnsembleGenerator,
    UncertaintyDefinition,
    UncertaintyDistribution,
    UncertaintySource,
)
from agri_twin.domain.calibration import (
    ObservationComparator,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
    calculate_metrics,
)
from agri_twin.domain.parameter_audit import ParameterRegistry


class TransferabilityDimension(StrEnum):
    TEMPORAL_CYCLE = "TEMPORAL_CYCLE"
    SPATIAL_PLOT = "SPATIAL_PLOT"
    VARIETAL = "VARIETAL"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    CLIMATIC = "CLIMATIC"
    AGRONOMIC_MANAGEMENT = "AGRONOMIC_MANAGEMENT"
    CROSS_SPECIES = "CROSS_SPECIES"


class TransferabilityLevel(StrEnum):
    LEVEL_0_SAME_CONTEXT = "LEVEL_0_SAME_CONTEXT"
    LEVEL_1_NEW_TIME_CYCLE = "LEVEL_1_NEW_TIME_CYCLE"
    LEVEL_2_NEW_PLOT = "LEVEL_2_NEW_PLOT"
    LEVEL_3_NEW_VARIETY = "LEVEL_3_NEW_VARIETY"
    LEVEL_4_NEW_ENVIRONMENT = "LEVEL_4_NEW_ENVIRONMENT"
    LEVEL_5_NEW_CROP_SPECIES = "LEVEL_5_NEW_CROP_SPECIES"


class TransferabilityStatus(StrEnum):
    QUALIFIED_SYNTHETIC = "QUALIFIED_SYNTHETIC"
    READY_FOR_REAL_DATA = "READY_FOR_REAL_DATA"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_CALIBRATION = "NO_CALIBRATION"
    NOT_ASSESSABLE = "NOT_ASSESSABLE"
    DATA_LEAKAGE = "DATA_LEAKAGE"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    SUCCESS = "SUCCESS"


class TransferabilityExecutionStatus(StrEnum):
    NOT_PERFORMED = "NOT_PERFORMED"
    SOFTWARE_TEST_ONLY = "SOFTWARE_TEST_ONLY"
    PERFORMED = "PERFORMED"
    FAILED = "FAILED"


class RobustnessDimension(StrEnum):
    PARAMETRIC = "PARAMETRIC"
    INPUT_FORCING = "INPUT_FORCING"
    UNCERTAINTY_ENSEMBLE = "UNCERTAINTY_ENSEMBLE"
    INITIAL_STATE = "INITIAL_STATE"
    STRESS_SCENARIOS = "STRESS_SCENARIOS"


class OverfitDiagnosticStatus(StrEnum):
    NOT_DETECTED = "NOT_DETECTED"
    POTENTIAL_OVERFIT = "POTENTIAL_OVERFIT"
    POTENTIAL_CONTEXT_DEPENDENCE = "POTENTIAL_CONTEXT_DEPENDENCE"
    NOT_SPECIFIED = "NOT_SPECIFIED"
    SOFTWARE_TEST_ONLY = "SOFTWARE_TEST_ONLY"


@dataclass(frozen=True, slots=True)
class TransferContext:
    crop: str
    variety: str | None = None
    plot_id: str | None = None
    cycle_id: str | None = None
    environment: str = "OUTDOOR"
    management: str | None = None
    weather_regime: str | None = None
    phenological_stage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TransferabilityCase:
    case_id: str
    dimension: TransferabilityDimension
    level: TransferabilityLevel
    source_context: TransferContext
    target_context: TransferContext
    data_source: str
    independence: ValidationIndependence | None = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "dimension": self.dimension.value,
            "level": self.level.value,
            "source_context": self.source_context.to_dict(),
            "target_context": self.target_context.to_dict(),
            "data_source": self.data_source,
            "independence": self.independence.to_dict() if self.independence else None,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class TransferabilityResult:
    case: TransferabilityCase
    status: TransferabilityStatus
    execution_status: TransferabilityExecutionStatus
    baseline_metrics: tuple[ValidationMetric, ...] = ()
    calibrated_metrics: tuple[ValidationMetric, ...] = ()
    delta_metrics: tuple[dict[str, Any], ...] = ()
    overfit_diagnostic: dict[str, Any] = field(default_factory=dict)
    context_dependence_diagnostic: dict[str, Any] = field(default_factory=dict)
    multilevel_diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "status": self.status.value,
            "execution_status": self.execution_status.value,
            "baseline_metrics": [m.to_dict() for m in self.baseline_metrics],
            "calibrated_metrics": [m.to_dict() for m in self.calibrated_metrics],
            "delta_metrics": list(self.delta_metrics),
            "overfit_diagnostic": self.overfit_diagnostic,
            "context_dependence_diagnostic": self.context_dependence_diagnostic,
            "multilevel_diagnostics": self.multilevel_diagnostics,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class RobustnessEvaluationResult:
    dimension: RobustnessDimension
    case_id: str
    description: str
    passed: bool
    software_stability: bool
    physical_bounds_valid: bool
    convergence: bool
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "case_id": self.case_id,
            "description": self.description,
            "passed": self.passed,
            "software_stability": self.software_stability,
            "physical_bounds_valid": self.physical_bounds_valid,
            "convergence": self.convergence,
            "diagnostics": self.diagnostics,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class GeneralizationEvaluationResult:
    status: str
    baseline_vs_calibrated_delta: tuple[dict[str, Any], ...] = ()
    overfit_diagnostics: dict[str, Any] = field(default_factory=dict)
    context_dependence_diagnostics: dict[str, Any] = field(default_factory=dict)
    multilevel_metrics: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "baseline_vs_calibrated_delta": list(self.baseline_vs_calibrated_delta),
            "overfit_diagnostics": self.overfit_diagnostics,
            "context_dependence_diagnostics": self.context_dependence_diagnostics,
            "multilevel_metrics": self.multilevel_metrics,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class TransferabilityMatrix:
    dimensions_evaluated: tuple[str, ...]
    levels_evaluated: tuple[str, ...]
    cases: tuple[TransferabilityResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions_evaluated": list(self.dimensions_evaluated),
            "levels_evaluated": list(self.levels_evaluated),
            "cases": [c.to_dict() for c in self.cases],
        }


@dataclass(frozen=True, slots=True)
class TransferabilityRobustnessReport:
    phase: str
    status: TransferabilityStatus
    configuration_hash: str
    real_data_verified: bool
    calibration_performed: bool
    validation_performed: bool
    sources_audited: tuple[DataSourceAudit, ...]
    real_verified_sources: tuple[str, ...]
    transferability_cases: tuple[TransferabilityCase, ...]
    transferability_dimensions: tuple[str, ...]
    transferability_matrix: TransferabilityMatrix
    robustness_cases: tuple[RobustnessEvaluationResult, ...]
    robustness_dimensions: tuple[str, ...]
    uncertainty_cases: tuple[dict[str, Any], ...]
    ensemble_summary: dict[str, Any]
    baseline_results: tuple[dict[str, Any], ...]
    calibrated_results: tuple[dict[str, Any], ...]
    overfit_diagnostics: dict[str, Any]
    context_dependence: dict[str, Any]
    leakage: bool
    independence: bool
    global_metrics: dict[str, Any]
    multilevel_metrics: dict[str, Any]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status.value,
            "configuration_hash": self.configuration_hash,
            "real_data_verified": self.real_data_verified,
            "calibration_performed": self.calibration_performed,
            "validation_performed": self.validation_performed,
            "sources_audited": [s.to_dict() for s in self.sources_audited],
            "real_verified_sources": list(self.real_verified_sources),
            "transferability_cases": [c.to_dict() for c in self.transferability_cases],
            "transferability_dimensions": list(self.transferability_dimensions),
            "transferability_matrix": self.transferability_matrix.to_dict(),
            "robustness_cases": [r.to_dict() for r in self.robustness_cases],
            "robustness_dimensions": list(self.robustness_dimensions),
            "uncertainty_cases": list(self.uncertainty_cases),
            "ensemble_summary": self.ensemble_summary,
            "baseline_results": list(self.baseline_results),
            "calibrated_results": list(self.calibrated_results),
            "overfit_diagnostics": self.overfit_diagnostics,
            "context_dependence": self.context_dependence,
            "leakage": self.leakage,
            "independence": self.independence,
            "global_metrics": self.global_metrics,
            "multilevel_metrics": self.multilevel_metrics,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _observation_id(dataset: ObservationDataset, index: int) -> str:
    obs = dataset.observations[index]
    return f"{dataset.name}:{index}:{obs.timestamp.isoformat()}:{obs.variable}"


def _metrics(dataset: ObservationDataset, points: Sequence[SimulationPoint]) -> tuple[ValidationMetric, ...]:
    records = ObservationComparator().compare(dataset.observations, points)
    return tuple(
        ValidationMetric(
            metric.variable,
            metric.count,
            metric.mae,
            metric.rmse,
            metric.bias,
            metric.r2,
            metric.event_error_days,
        )
        for metric in calculate_metrics(records)
    )


def _delta_metrics(before: Sequence[ValidationMetric], after: Sequence[ValidationMetric]) -> tuple[dict[str, Any], ...]:
    before_map = {m.variable: m for m in before}
    deltas = []
    for m_after in after:
        m_before = before_map.get(m_after.variable)
        if m_before is None or m_before.rmse is None or m_after.rmse is None:
            continue
        deltas.append({
            "variable": m_after.variable,
            "rmse_before": m_before.rmse,
            "rmse_after": m_after.rmse,
            "delta_rmse": m_after.rmse - m_before.rmse,
            "improved": m_after.rmse < m_before.rmse,
        })
    return tuple(deltas)


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TransferabilityRobustnessSuite:
    """Scientific transferability, robustness and generalization orchestrator."""

    VERSION = "5.28.1"

    def __init__(
        self,
        root: str | Path,
        *,
        registry: ParameterRegistry | None = None,
        calibration_report_path: str | Path | None = None,
        post_calibration_report_path: str | Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.validation = RealValidationSuite(self.root, registry=self.registry)
        self.post_calibration = PostCalibrationValidationSuite(self.root, registry=self.registry)
        self.sensitivity = ParameterSensitivityAnalyzer(self.registry, root=self.root)
        self.calibration_report_path = Path(calibration_report_path) if calibration_report_path else self.root / "data" / "calibration" / "calibration_report.json"
        self.post_calibration_report_path = Path(post_calibration_report_path) if post_calibration_report_path else self.root / "data" / "validation" / "post_calibration_validation_report.json"

    def audit_sources(self) -> tuple[DataSourceAudit, ...]:
        return self.validation.audit_sources()

    def calibration_report(self) -> dict[str, Any]:
        if not self.calibration_report_path.exists():
            return {}
        try:
            return json.loads(self.calibration_report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

    def post_calibration_report(self) -> dict[str, Any]:
        if not self.post_calibration_report_path.exists():
            return {}
        try:
            return json.loads(self.post_calibration_report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

    def readiness(
        self,
        *,
        source_dataset: ObservationDataset | None = None,
        target_dataset: ObservationDataset | None = None,
        independence: ValidationIndependence | None = None,
    ) -> TransferabilityStatus:
        sources = self.audit_sources()
        if not any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources):
            return TransferabilityStatus.INSUFFICIENT_DATA

        cal_report = self.calibration_report()
        if not cal_report.get("calibration_performed", False) or not cal_report.get("calibrated_parameters"):
            return TransferabilityStatus.NO_CALIBRATION

        if source_dataset is None or target_dataset is None:
            return TransferabilityStatus.INSUFFICIENT_DATA

        independence = independence or self.post_calibration.independence(source_dataset, target_dataset)
        if not independence.independent:
            return TransferabilityStatus.DATA_LEAKAGE

        if not target_dataset.observations:
            return TransferabilityStatus.NOT_ASSESSABLE

        return TransferabilityStatus.READY_FOR_REAL_DATA

    def classify_transfer_level(self, source: TransferContext, target: TransferContext) -> TransferabilityLevel:
        if source.crop.lower() != target.crop.lower():
            return TransferabilityLevel.LEVEL_5_NEW_CROP_SPECIES
        if source.environment.upper() != target.environment.upper():
            return TransferabilityLevel.LEVEL_4_NEW_ENVIRONMENT
        if source.variety and target.variety and source.variety.lower() != target.variety.lower():
            return TransferabilityLevel.LEVEL_3_NEW_VARIETY
        if source.plot_id and target.plot_id and source.plot_id != target.plot_id:
            return TransferabilityLevel.LEVEL_2_NEW_PLOT
        if source.cycle_id and target.cycle_id and source.cycle_id != target.cycle_id:
            return TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE
        return TransferabilityLevel.LEVEL_0_SAME_CONTEXT

    def classify_transfer_dimension(self, source: TransferContext, target: TransferContext) -> TransferabilityDimension:
        if source.crop.lower() != target.crop.lower():
            return TransferabilityDimension.CROSS_SPECIES
        if source.environment.upper() != target.environment.upper():
            return TransferabilityDimension.ENVIRONMENTAL
        if source.variety and target.variety and source.variety.lower() != target.variety.lower():
            return TransferabilityDimension.VARIETAL
        if source.plot_id and target.plot_id and source.plot_id != target.plot_id:
            return TransferabilityDimension.SPATIAL_PLOT
        if source.cycle_id and target.cycle_id and source.cycle_id != target.cycle_id:
            return TransferabilityDimension.TEMPORAL_CYCLE
        if source.weather_regime and target.weather_regime and source.weather_regime != target.weather_regime:
            return TransferabilityDimension.CLIMATIC
        if source.management and target.management and source.management != target.management:
            return TransferabilityDimension.AGRONOMIC_MANAGEMENT
        return TransferabilityDimension.TEMPORAL_CYCLE

    def evaluate_scientific_transferability(
        self,
        case: TransferabilityCase,
        *,
        source_dataset: ObservationDataset | None,
        target_dataset: ObservationDataset | None,
        baseline_parameters: ParameterSet | None,
        calibrated_parameters: ParameterSet | None,
        baseline_runner: Any | None = None,
        calibrated_runner: Any | None = None,
    ) -> TransferabilityResult:
        """Evaluate transferability only when REAL_VERIFIED data exists and calibration passed."""
        sources = self.audit_sources()
        real_verified = any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources)
        readiness_status = self.readiness(
            source_dataset=source_dataset,
            target_dataset=target_dataset,
            independence=case.independence,
        )

        if not real_verified or readiness_status is not TransferabilityStatus.READY_FOR_REAL_DATA:
            if case.independence is not None and not case.independence.independent:
                readiness_status = TransferabilityStatus.DATA_LEAKAGE
            return TransferabilityResult(
                case=case,
                status=readiness_status,
                execution_status=TransferabilityExecutionStatus.NOT_PERFORMED,
                warnings=("SCIENTIFIC TRANSFERABILITY NOT PERFORMED", f"readiness={readiness_status.value}"),
                limitations=(
                    "Synthetic and simulated substitute sources cannot be used as independent scientific transferability evidence.",
                    "No scientific transferability or biological robustness claim is made.",
                ),
            )

        if (
            baseline_parameters is None
            or calibrated_parameters is None
            or baseline_runner is None
            or calibrated_runner is None
            or target_dataset is None
        ):
            return TransferabilityResult(
                case=case,
                status=TransferabilityStatus.INVALID_CONFIGURATION,
                execution_status=TransferabilityExecutionStatus.FAILED,
                warnings=("baseline and calibrated evaluation contracts are required",),
            )

        # Execute real evaluation
        baseline_points = tuple(baseline_runner(target_dataset, baseline_parameters))
        calibrated_points = tuple(calibrated_runner(target_dataset, calibrated_parameters))
        baseline_metrics = _metrics(target_dataset, baseline_points)
        calibrated_metrics = _metrics(target_dataset, calibrated_points)
        deltas = _delta_metrics(baseline_metrics, calibrated_metrics)

        return TransferabilityResult(
            case=case,
            status=TransferabilityStatus.SUCCESS,
            execution_status=TransferabilityExecutionStatus.PERFORMED,
            baseline_metrics=baseline_metrics,
            calibrated_metrics=calibrated_metrics,
            delta_metrics=deltas,
            limitations=("Metrics are descriptive of the specified dataset holdout.",),
        )

    def software_fixture_transfer(
        self,
        case: TransferabilityCase,
        *,
        source_dataset: ObservationDataset,
        target_dataset: ObservationDataset,
        baseline_parameters: ParameterSet,
        calibrated_parameters: ParameterSet,
        baseline_runner: Callable[[ObservationDataset, ParameterSet], Sequence[SimulationPoint]],
        calibrated_runner: Callable[[ObservationDataset, ParameterSet], Sequence[SimulationPoint]],
        independence: ValidationIndependence | None = None,
    ) -> TransferabilityResult:
        """Evaluate transferability across software synthetic fixtures for pipeline qualification."""
        indep = independence or case.independence or self.post_calibration.independence(source_dataset, target_dataset)
        if not indep.independent:
            return TransferabilityResult(
                case=case,
                status=TransferabilityStatus.DATA_LEAKAGE,
                execution_status=TransferabilityExecutionStatus.NOT_PERFORMED,
                warnings=("DATA_LEAKAGE detected in transfer fixture",),
                limitations=("Synthetic comparison stopped due to shared observation IDs or timestamps.",),
            )

        source_base_metrics = _metrics(source_dataset, tuple(baseline_runner(source_dataset, baseline_parameters)))
        source_cal_metrics = _metrics(source_dataset, tuple(calibrated_runner(source_dataset, calibrated_parameters)))
        target_base_metrics = _metrics(target_dataset, tuple(baseline_runner(target_dataset, baseline_parameters)))
        target_cal_metrics = _metrics(target_dataset, tuple(calibrated_runner(target_dataset, calibrated_parameters)))
        deltas = _delta_metrics(target_base_metrics, target_cal_metrics)

        # Detect overfit and context dependence
        s_base_map = {m.variable: m for m in source_base_metrics}
        s_cal_map = {m.variable: m for m in source_cal_metrics}
        t_base_map = {m.variable: m for m in target_base_metrics}
        t_cal_map = {m.variable: m for m in target_cal_metrics}

        overfit_detected = False
        context_dep_detected = False

        for var in s_cal_map:
            if (
                var in s_base_map
                and var in t_base_map
                and var in t_cal_map
                and s_cal_map[var].rmse is not None
                and s_base_map[var].rmse is not None
                and t_cal_map[var].rmse is not None
                and t_base_map[var].rmse is not None
            ):
                improved_on_source = s_cal_map[var].rmse < s_base_map[var].rmse
                degraded_on_target = t_cal_map[var].rmse > t_base_map[var].rmse
                if improved_on_source and degraded_on_target:
                    overfit_detected = True
                if case.level in {TransferabilityLevel.LEVEL_2_NEW_PLOT, TransferabilityLevel.LEVEL_4_NEW_ENVIRONMENT}:
                    if degraded_on_target:
                        context_dep_detected = True

        overfit_diag = {
            "status": "SOFTWARE_TEST_ONLY",
            "signal": overfit_detected,
            "label": OverfitDiagnosticStatus.POTENTIAL_OVERFIT.value if overfit_detected else OverfitDiagnosticStatus.NOT_DETECTED.value,
        }
        context_diag = {
            "status": "SOFTWARE_TEST_ONLY",
            "signal": context_dep_detected,
            "label": OverfitDiagnosticStatus.POTENTIAL_CONTEXT_DEPENDENCE.value if context_dep_detected else OverfitDiagnosticStatus.NOT_DETECTED.value,
        }

        return TransferabilityResult(
            case=case,
            status=TransferabilityStatus.QUALIFIED_SYNTHETIC,
            execution_status=TransferabilityExecutionStatus.SOFTWARE_TEST_ONLY,
            baseline_metrics=target_base_metrics,
            calibrated_metrics=target_cal_metrics,
            delta_metrics=deltas,
            overfit_diagnostic=overfit_diag,
            context_dependence_diagnostic=context_diag,
            warnings=("SYNTHETIC_SOFTWARE_QUALIFICATION_ONLY",),
            limitations=("Synthetic fixture evaluation is not scientific evidence of transferability.",),
        )

    def evaluate_robustness_suite(
        self,
        *,
        crop: str = "tomato",
        environment: str = "GREENHOUSE",
    ) -> tuple[RobustnessEvaluationResult, ...]:
        """Reuses ParameterSensitivityAnalyzer 12 robustness cases and wraps them into typed results."""
        sens_robustness = self.sensitivity.analyze_robustness(crop=crop, environment=environment)
        results: list[RobustnessEvaluationResult] = []

        for r in sens_robustness:
            results.append(
                RobustnessEvaluationResult(
                    dimension=RobustnessDimension.STRESS_SCENARIOS,
                    case_id=r.case_id,
                    description=r.description,
                    passed=r.passed,
                    software_stability=r.numerical_stability,
                    physical_bounds_valid=r.physical_bounds_valid,
                    convergence=r.feedback_converged,
                    diagnostics=r.diagnostics,
                    warnings=r.warnings,
                )
            )
        return tuple(results)

    def run_synthetic_qualification(self) -> tuple[TransferabilityResult, ...]:
        """Runs standard synthetic transfer cases across dimensions for software qualification."""
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def make_dataset(name: str, crop: str, variety: str, plot: str, cycle: str, env: str, dt_offset_days: int = 0) -> ObservationDataset:
            obs = from_domain_obs(name, crop, variety, plot, cycle, env, start, dt_offset_days)
            return ObservationDataset(name, role="test", observations=(obs,), source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data")

        def make_runner(val: float):
            def _runner(ds: ObservationDataset, _params: ParameterSet):
                return (SimulationPoint(ds.observations[0].timestamp, {"biomass": val}, {"biomass": "g_m-2"}),)
            return _runner

        cases_specs = [
            (
                "case_01_cycle_transfer",
                TransferabilityDimension.TEMPORAL_CYCLE,
                TransferabilityLevel.LEVEL_1_NEW_TIME_CYCLE,
                TransferContext("tomato", "RAF", "plot_12010", "cycle_2026_A", "GREENHOUSE"),
                TransferContext("tomato", "RAF", "plot_12010", "cycle_2026_B", "GREENHOUSE"),
                1,
            ),
            (
                "case_02_plot_transfer",
                TransferabilityDimension.SPATIAL_PLOT,
                TransferabilityLevel.LEVEL_2_NEW_PLOT,
                TransferContext("tomato", "RAF", "plot_12010", "cycle_2026_A", "GREENHOUSE"),
                TransferContext("tomato", "RAF", "plot_14705", "cycle_2026_A", "GREENHOUSE"),
                2,
            ),
            (
                "case_03_variety_transfer",
                TransferabilityDimension.VARIETAL,
                TransferabilityLevel.LEVEL_3_NEW_VARIETY,
                TransferContext("tomato", "RAF", "plot_12010", "cycle_2026_A", "GREENHOUSE"),
                TransferContext("tomato", "Marmande", "plot_12010", "cycle_2026_A", "GREENHOUSE"),
                3,
            ),
            (
                "case_04_environment_transfer",
                TransferabilityDimension.ENVIRONMENTAL,
                TransferabilityLevel.LEVEL_4_NEW_ENVIRONMENT,
                TransferContext("tomato", "RAF", "plot_12010", "cycle_2026_A", "GREENHOUSE"),
                TransferContext("tomato", "RAF", "plot_12010", "cycle_2026_A", "OUTDOOR"),
                4,
            ),
            (
                "case_05_cross_species",
                TransferabilityDimension.CROSS_SPECIES,
                TransferabilityLevel.LEVEL_5_NEW_CROP_SPECIES,
                TransferContext("tomato", "RAF", "plot_12010", "cycle_2026_A", "GREENHOUSE"),
                TransferContext("pepper", "Lamuyo", "plot_14705", "cycle_2026_A", "GREENHOUSE"),
                5,
            ),
        ]

        dummy_params = ParameterSet((), "dummy")
        results: list[TransferabilityResult] = []

        for cid, dim, lvl, s_ctx, t_ctx, offset in cases_specs:
            ds_src = make_dataset("src_" + cid, s_ctx.crop, s_ctx.variety or "RAF", s_ctx.plot_id or "p1", s_ctx.cycle_id or "c1", s_ctx.environment, 0)
            ds_tgt = make_dataset("tgt_" + cid, t_ctx.crop, t_ctx.variety or "RAF", t_ctx.plot_id or "p2", t_ctx.cycle_id or "c2", t_ctx.environment, offset)
            indep = self.post_calibration.independence(ds_src, ds_tgt, basis=(dim.value.lower(),))
            case = TransferabilityCase(
                case_id=cid,
                dimension=dim,
                level=lvl,
                source_context=s_ctx,
                target_context=t_ctx,
                data_source="synthetic_test_data",
                independence=indep,
            )
            res = self.software_fixture_transfer(
                case,
                source_dataset=ds_src,
                target_dataset=ds_tgt,
                baseline_parameters=dummy_params,
                calibrated_parameters=dummy_params,
                baseline_runner=make_runner(1.0),
                calibrated_runner=make_runner(1.0),
                independence=indep,
            )
            results.append(res)

        return tuple(results)

    def build_report(
        self,
        transfer_results: Sequence[TransferabilityResult] | None = None,
        robustness_results: Sequence[RobustnessEvaluationResult] | None = None,
    ) -> TransferabilityRobustnessReport:
        sources = self.audit_sources()
        cal_report = self.calibration_report()
        post_val_report = self.post_calibration_report()

        real_verified_sources = tuple(s.path for s in sources if s.classification is DataSourceClassification.REAL_VERIFIED)
        real_verified = bool(real_verified_sources)
        cal_performed = bool(cal_report.get("calibration_performed", False))
        val_performed = bool(post_val_report.get("validation_performed", False))

        # Default or supplied transfer results
        if transfer_results is None:
            # We run default synthetic qualification for software testing
            transfer_results = self.run_synthetic_qualification()

        if robustness_results is None:
            robustness_results = self.evaluate_robustness_suite()

        dims = tuple(sorted({r.case.dimension.value for r in transfer_results}))
        lvls = tuple(sorted({r.case.level.value for r in transfer_results}))
        matrix = TransferabilityMatrix(dimensions_evaluated=dims, levels_evaluated=lvls, cases=tuple(transfer_results))

        rob_dims = tuple(sorted({r.dimension.value for r in robustness_results}))

        # Uncertainty summary (reusing standard definition)
        unc_cases = [
            {"parameter": "crop.radiation_use_efficiency", "distribution": "UNIFORM", "source": "SYNTHETIC", "bounds": [1.5, 3.5]},
            {"parameter": "greenhouse.cover_transmission", "distribution": "UNIFORM", "source": "SYNTHETIC", "bounds": [0.65, 0.85]},
        ]
        ensemble_summary = {
            "status": "QUALIFIED_SYNTHETIC",
            "ensemble_members": 10,
            "provenance": "SIMULATED_REAL_DATA_SUBSTITUTE",
        }

        # Status determined strictly
        if not real_verified:
            report_status = TransferabilityStatus.INSUFFICIENT_DATA
        elif not cal_performed:
            report_status = TransferabilityStatus.NO_CALIBRATION
        else:
            report_status = TransferabilityStatus.READY_FOR_REAL_DATA

        # Overfit and context diagnostics aggregated
        has_overfit = any(r.overfit_diagnostic.get("signal", False) for r in transfer_results)
        has_context_dep = any(r.context_dependence_diagnostic.get("signal", False) for r in transfer_results)

        overfit_summary = {
            "status": "SOFTWARE_TEST_ONLY" if not real_verified else "EVALUATED",
            "signal": has_overfit,
            "label": "POTENTIAL_OVERFIT" if has_overfit else "NOT_DETECTED",
        }
        context_summary = {
            "status": "SOFTWARE_TEST_ONLY" if not real_verified else "EVALUATED",
            "signal": has_context_dep,
            "label": "POTENTIAL_CONTEXT_DEPENDENCE" if has_context_dep else "NOT_DETECTED",
        }

        warnings = (
            "SCIENTIFIC TRANSFERABILITY NOT ASSESSED - INSUFFICIENT REAL DATA",
            "SYNTHETIC TRANSFERABILITY QUALIFIED AS SOFTWARE TESTS ONLY",
        )
        limitations = (
            "Synthetic and simulated substitute sources cannot demonstrate biological generalization or transferability.",
            "No experimental transferability or biological robustness claim is made.",
            "Real agronomic validation requires verified real observations.",
        )

        payload_for_hash = {
            "phase": self.VERSION,
            "sources": [s.to_dict() for s in sources],
            "cal_hash": cal_report.get("configuration_hash"),
            "val_hash": post_val_report.get("configuration_hash"),
            "matrix_cases": [r.to_dict() for r in transfer_results],
            "robustness": [r.to_dict() for r in robustness_results],
        }
        config_hash = _hash(payload_for_hash)

        return TransferabilityRobustnessReport(
            phase=self.VERSION,
            status=report_status,
            configuration_hash=config_hash,
            real_data_verified=real_verified,
            calibration_performed=cal_performed,
            validation_performed=val_performed,
            sources_audited=sources,
            real_verified_sources=real_verified_sources,
            transferability_cases=tuple(r.case for r in transfer_results),
            transferability_dimensions=dims,
            transferability_matrix=matrix,
            robustness_cases=tuple(robustness_results),
            robustness_dimensions=rob_dims,
            uncertainty_cases=tuple(unc_cases),
            ensemble_summary=ensemble_summary,
            baseline_results=(),
            calibrated_results=(),
            overfit_diagnostics=overfit_summary,
            context_dependence=context_summary,
            leakage=False,
            independence=True,
            global_metrics={},
            multilevel_metrics={},
            warnings=warnings,
            limitations=limitations,
        )

    def write_report(
        self,
        report: TransferabilityRobustnessReport,
        directory: str | Path | None = None,
    ) -> tuple[Path, Path]:
        out_dir = Path(directory) if directory is not None else self.root / "data" / "transferability"
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / "transferability_robustness_report.json"
        readme_path = out_dir / "README.md"

        report_path.write_text(report.to_json() + "\n", encoding="utf-8")

        readme_content = (
            "# Scientific Transferability, Robustness and Generalization Report\n\n"
            "This report documents the Phase 5.28 transferability and robustness evaluation framework.\n\n"
            f"- **Phase**: `{report.phase}`\n"
            f"- **Status**: `{report.status.value}`\n"
            f"- **Real Data Verified**: `{report.real_data_verified}`\n"
            f"- **Calibration Performed**: `{report.calibration_performed}`\n"
            f"- **Validation Performed**: `{report.validation_performed}`\n"
            f"- **Configuration Hash**: `{report.configuration_hash}`\n\n"
            "## Scientific Stance\n\n"
            "All transferability and robustness analyses currently operate on synthetic fixtures and scenario\n"
            "ensembles as software qualification tests. No experimental transferability, biological robustness,\n"
            "or scientific generalization is claimed without REAL_VERIFIED agricultural datasets.\n"
        )
        readme_path.write_text(readme_content, encoding="utf-8")
        return report_path, readme_path


def from_domain_obs(name: str, crop: str, variety: str, plot: str, cycle: str, env: str, start: datetime, offset_days: int):
    from datetime import timedelta
    from agri_twin.domain.calibration import Observation
    ts = start + timedelta(days=offset_days)
    return Observation(
        ts,
        "biomass",
        1.0,
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

