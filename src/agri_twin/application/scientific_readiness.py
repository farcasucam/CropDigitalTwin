"""Phase 5.20 scientific readiness gate and synthetic software benchmarking.

This module composes the existing Phase 5.1-5.19 contracts. It does not add a
second validation, calibration, observation, metric, clock, scheduler or
identifiability system, and it never treats synthetic evidence as agronomic
validation.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping

from agri_twin.application.instrumentation import AcquisitionFaults
from agri_twin.application.parameter_identifiability import IdentifiabilityStatus
from agri_twin.application.synthetic_campaign import (
    CampaignConfiguration,
    CampaignResult,
    SyntheticObservationCampaign,
    campaigns_are_deterministic,
    default_campaign_crops,
)
from agri_twin.domain.parameter_audit import ParameterRegistry


class ScientificReadinessStatus(StrEnum):
    NOT_ASSESSED = "NOT_ASSESSED"
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SCIENTIFIC_VALIDATION_REQUIRED = "SCIENTIFIC_VALIDATION_REQUIRED"


class EvidenceType(StrEnum):
    PROJECT_DATA = "PROJECT_DATA"
    MEASURED_DATA = "MEASURED_DATA"
    LITERATURE = "LITERATURE"
    SYNTHETIC = "SYNTHETIC"
    ENGINEERING_DEFAULT = "ENGINEERING_DEFAULT"
    CALIBRATED = "CALIBRATED"


@dataclass(frozen=True, slots=True)
class ComponentReadiness:
    component: str
    software_status: ScientificReadinessStatus
    data_status: ScientificReadinessStatus
    scientific_status: ScientificReadinessStatus
    evidence: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "software_status": self.software_status.value,
            "data_status": self.data_status.value,
            "scientific_status": self.scientific_status.value,
            "evidence": list(self.evidence),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class SyntheticBenchmarkResult:
    name: str
    status: str
    evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "evidence": list(self.evidence), "limitations": list(self.limitations)}


@dataclass(frozen=True, slots=True)
class ScientificReadinessReport:
    overall_status: ScientificReadinessStatus
    software_readiness: ScientificReadinessStatus
    data_readiness: ScientificReadinessStatus
    scientific_validation_status: ScientificReadinessStatus
    real_data_available: bool
    real_agronomic_data_verified: bool
    calibration_status: str
    assimilation_status: str
    component_results: tuple[ComponentReadiness, ...]
    parameter_results: tuple[dict[str, Any], ...]
    observable_results: tuple[dict[str, Any], ...]
    crop_results: tuple[dict[str, Any], ...]
    environment_results: tuple[dict[str, Any], ...]
    benchmark_results: tuple[SyntheticBenchmarkResult, ...]
    blocking_items: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence: tuple[str, ...]
    limitations: tuple[str, ...]
    generated_from: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "software_readiness": self.software_readiness.value,
            "data_readiness": self.data_readiness.value,
            "scientific_validation_status": self.scientific_validation_status.value,
            "real_data_available": self.real_data_available,
            "real_agronomic_data_verified": self.real_agronomic_data_verified,
            "calibration_status": self.calibration_status,
            "assimilation_status": self.assimilation_status,
            "component_results": [item.to_dict() for item in self.component_results],
            "parameter_results": list(self.parameter_results),
            "observable_results": list(self.observable_results),
            "crop_results": list(self.crop_results),
            "environment_results": list(self.environment_results),
            "benchmark_results": [item.to_dict() for item in self.benchmark_results],
            "blocking_items": list(self.blocking_items),
            "warnings": list(self.warnings),
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
            "generated_from": self.generated_from,
        }

    def configuration_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ScientificReadinessEvaluation:
    report: ScientificReadinessReport
    campaign: CampaignResult

    @property
    def overall_status(self) -> ScientificReadinessStatus:
        return self.report.overall_status

    @property
    def software_readiness(self) -> ScientificReadinessStatus:
        return self.report.software_readiness

    @property
    def data_readiness(self) -> ScientificReadinessStatus:
        return self.report.data_readiness

    @property
    def scientific_validation_status(self) -> ScientificReadinessStatus:
        return self.report.scientific_validation_status

    @property
    def real_data_available(self) -> bool:
        return self.report.real_data_available

    @property
    def real_agronomic_data_verified(self) -> bool:
        return self.report.real_agronomic_data_verified

    @property
    def calibration_status(self) -> str:
        return self.report.calibration_status

    @property
    def assimilation_status(self) -> str:
        return self.report.assimilation_status


class SyntheticBenchmarkSuite:
    """Formal software benchmarks; successful synthetic results are not validation."""

    def __init__(self, root: str | Path, *, start=None, end=None, seed: int = 520) -> None:
        from datetime import datetime, timezone, timedelta

        self.root = Path(root)
        self.start = start or datetime(2026, 6, 1, 10, tzinfo=timezone.utc)
        self.end = end or self.start + timedelta(hours=2)
        self.seed = seed

    def run(self, baseline: CampaignResult | None = None) -> tuple[SyntheticBenchmarkResult, ...]:
        baseline = baseline or self._campaign()
        results = [
            self._check("determinism", self._determinism, baseline),
            self._check("temporal_consistency", self._temporal_consistency, baseline),
            self._check("multi_plot_isolation", self._multi_plot_isolation, baseline),
            self._check("multi_cycle_isolation", self._multi_cycle_isolation, baseline),
            self._check("perennial_lifecycle", self._perennial_lifecycle, baseline),
            self._check("greenhouse_feedback_contract", self._greenhouse_feedback_contract, baseline),
            self._check("observation_defects", self._observation_defects, baseline),
            self._check("known_synthetic_bias", self._known_synthetic_bias, baseline),
            self._check("parameter_identifiability_conservatism", self._identifiability, baseline),
            self._check("backend_substitution", self._backend_substitution, baseline),
        ]
        return tuple(results)

    def _campaign(self, **changes: Any) -> CampaignResult:
        configuration = CampaignConfiguration(
            campaign_id="phase5-20-benchmark",
            root=self.root,
            start=self.start,
            end=self.end,
            interval_seconds=3600,
            seed=self.seed,
            **changes,
        )
        return SyntheticObservationCampaign(configuration).run()

    @staticmethod
    def _check(name: str, function: Callable[[CampaignResult], tuple[str, ...]], result: CampaignResult) -> SyntheticBenchmarkResult:
        try:
            evidence = function(result)
            return SyntheticBenchmarkResult(name, "PASS", evidence, ("synthetic software benchmark only; not scientific validation",))
        except (AssertionError, ImportError, KeyError, ValueError) as exc:
            return SyntheticBenchmarkResult(name, "FAIL", (str(exc),), ("benchmark failure requires investigation",))

    def _determinism(self, result: CampaignResult) -> tuple[str, ...]:
        repeat = self._campaign()
        assert campaigns_are_deterministic(result, repeat)
        return ("same configuration, seed, clock authority and plan produced identical artifacts",)

    @staticmethod
    def _temporal_consistency(result: CampaignResult) -> tuple[str, ...]:
        timestamps = [record.timestamp for record in result.acquisition_records]
        assert timestamps == sorted(timestamps)
        assert all(record.clock_source == "SimulationClock" for record in result.acquisition_records)
        assert result.twin_repository.latest_snapshot() is not None
        return ("acquisition timestamps are ordered and SimulationClock-sourced", "TwinSnapshot history exists")

    @staticmethod
    def _multi_plot_isolation(result: CampaignResult) -> tuple[str, ...]:
        plots = {item.plot_id for item in default_campaign_crops()}
        for plot in plots:
            assert result.twin_repository.history(plot)
        tomato = {state.key for state in result.twin_repository.history("P-TOMATO")}
        pepper = {state.key for state in result.twin_repository.history("P-PEPPER")}
        assert tomato.isdisjoint(pepper)
        return ("plot histories have distinct state keys",)

    @staticmethod
    def _multi_cycle_isolation(result: CampaignResult) -> tuple[str, ...]:
        first = result.twin_repository.history("P-LETTUCE-1", "cycle_1")
        second = result.twin_repository.history("P-LETTUCE-2", "cycle_2")
        assert first and second and {item.key for item in first}.isdisjoint({item.key for item in second})
        return ("lettuce cycle_1 and cycle_2 histories remain isolated",)

    @staticmethod
    def _perennial_lifecycle(result: CampaignResult) -> tuple[str, ...]:
        perennial = {item.crop for item in default_campaign_crops() if item.cycle_type == "perennial"}
        assert perennial == {"grape", "peach", "plum", "apple"}
        assert all(result.twin_repository.history(item.plot_id, item.cycle_id) for item in default_campaign_crops() if item.cycle_type == "perennial")
        return ("perennial crop/cycle scopes are represented without annual state sharing",)

    @staticmethod
    def _greenhouse_feedback_contract(result: CampaignResult) -> tuple[str, ...]:
        greenhouse = importlib.import_module("agri_twin.domain.greenhouse")
        feedback = importlib.import_module("agri_twin.domain.crop_greenhouse_feedback")
        assert hasattr(greenhouse, "GreenhousePhysicalModel") and hasattr(greenhouse, "SimplifiedGreenhouseModel")
        assert hasattr(feedback, "CropGreenhouseFeedbackLoop")
        assert any(item.environment == "GREENHOUSE" for item in default_campaign_crops())
        return ("simplified greenhouse and crop-feedback contracts are importable", "greenhouse remains optional to EnergyPlus")

    def _observation_defects(self, result: CampaignResult) -> tuple[str, ...]:
        from dataclasses import replace

        faults = AcquisitionFaults(missing_every=7, duplicate_every=11, invalid_every=13, out_of_range_every=17, unit_error_every=19)
        defective = self._campaign(faults=faults)
        counts = defective.report.quality_counts
        assert all(counts[key] > 0 for key in ("missing", "duplicate", "invalid", "out_of_range", "unit_error"))
        return ("missing, duplicate, invalid, out_of_range and unit_error remain observable in QC",)

    def _known_synthetic_bias(self, result: CampaignResult) -> tuple[str, ...]:
        biased = self._campaign(known_bias_variable="air_temperature", known_bias_offset=1.5, bias_threshold=0.1)
        summary = next(item for item in biased.diagnostics.by_variable() if item.variable == "air_temperature")
        assert summary.mae == 1.5 and abs(summary.bias or 0.0) == 1.5 and summary.rmse == 1.5
        return ("configured synthetic offset recovered by existing MAE/RMSE/bias diagnostics",)

    @staticmethod
    def _identifiability(result: CampaignResult) -> tuple[str, ...]:
        assert result.identifiability_after.synthetic_data_only
        assert not any(item.identifiability_status is IdentifiabilityStatus.IDENTIFIABLE for item in result.identifiability_after.assessments)
        return ("synthetic observations do not promote IDENTIFIABLE",)

    def _backend_substitution(self, result: CampaignResult) -> tuple[str, ...]:
        substituted = self._campaign(use_future_real_adapter=True)
        assert substituted.report.pipeline_status == "SUCCESS"
        assert substituted.report.backend_substitution_status.startswith("FUTURE_REAL_ADAPTER_SUBSTITUTED")
        return ("future-real adapter and simulated backend share the ingestion contract",)


class ScientificReadinessGate:
    """Evaluate software readiness separately from data readiness and validation."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def evaluate(self, *, campaign: CampaignResult | None = None) -> ScientificReadinessEvaluation:
        campaign = campaign or SyntheticBenchmarkSuite(self.root). _campaign()
        registry = ParameterRegistry.from_repository(self.root)
        benchmarks = SyntheticBenchmarkSuite(self.root).run(campaign)
        report = self._report(registry, campaign, benchmarks)
        return ScientificReadinessEvaluation(report, campaign)

    def _report(self, registry: ParameterRegistry, campaign: CampaignResult, benchmarks: tuple[SyntheticBenchmarkResult, ...]) -> ScientificReadinessReport:
        components = self._components(campaign)
        all_benchmarks_pass = all(item.status == "PASS" for item in benchmarks)
        software_status = ScientificReadinessStatus.READY if all_benchmarks_pass else ScientificReadinessStatus.PARTIAL
        data_status = ScientificReadinessStatus.INSUFFICIENT_DATA
        validation_status = ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED
        parameter_results = tuple(self._parameter_result(item) for item in campaign.identifiability_after.assessments)
        observables = tuple(sorted({item.variable for item in campaign.ingestion.dataset.observations})) if campaign.ingestion.dataset else ()
        observable_results = tuple({"observable": variable, "status": "SYNTHETIC_ONLY", "data_available": True} for variable in observables)
        crop_results = tuple({"crop": item.crop, "variety": item.variety, "cycle_type": item.cycle_type, "status": "SOFTWARE_READY", "data_status": "SYNTHETIC_ONLY"} for item in default_campaign_crops())
        environment_results = tuple({"environment": value, "status": "SOFTWARE_READY", "data_status": "SYNTHETIC_ONLY"} for value in ("OUTDOOR", "GREENHOUSE"))
        blocking = (
            "REAL_AGRONOMIC_DATA_NOT_AVAILABLE",
            "VERIFIED_REAL_DATA_REQUIRED_BEFORE_CALIBRATION",
            "INDEPENDENT_DATASET_REQUIRED_BEFORE_EXPERIMENTAL_VALIDATION",
        )
        warnings = (
            "synthetic benchmarks qualify software interfaces only",
            "literature and engineering defaults are not local measured data",
            "EnergyPlus is optional and does not validate the crop model",
        )
        evidence = (
            "PROJECT_DATA: existing source/configuration/test contracts",
            "SYNTHETIC: SyntheticObservationCampaign and SyntheticBenchmarkSuite",
            "LITERATURE: parameter registry evidence entries where present",
            "ENGINEERING_DEFAULT: runtime and greenhouse defaults where present",
        )
        limitations = (
            "REAL AGRONOMIC DATASET NOT VERIFIED",
            "CALIBRATION NOT PERFORMED",
            "DATA ASSIMILATION NOT IMPLEMENTED",
            "EXPERIMENTAL VALIDATION NOT CLAIMED",
            "THRESHOLD_NOT_DEFINED for scientific acceptance metrics",
        )
        return ScientificReadinessReport(
            overall_status=ScientificReadinessStatus.PARTIAL,
            software_readiness=software_status,
            data_readiness=data_status,
            scientific_validation_status=validation_status,
            real_data_available=False,
            real_agronomic_data_verified=False,
            calibration_status="CALIBRATION_BLOCKED: REAL_AGRONOMIC_DATA_NOT_AVAILABLE",
            assimilation_status="NOT_IMPLEMENTED",
            component_results=components,
            parameter_results=parameter_results,
            observable_results=observable_results,
            crop_results=crop_results,
            environment_results=environment_results,
            benchmark_results=benchmarks,
            blocking_items=blocking,
            warnings=warnings,
            evidence=evidence,
            limitations=limitations,
            generated_from="ParameterRegistry+ParameterIdentifiabilityAnalyzer+ExperimentalObservationPlan+InstrumentationSpecification+SimulatedAcquisitionBackend+ObservationIngestion+TwinState+TemporalAlignment+ErrorDiagnostics+SyntheticBenchmarkSuite",
        )

    @staticmethod
    def _parameter_result(item: Any) -> dict[str, Any]:
        return {
            "parameter_id": item.parameter_id,
            "identifiability_status": item.identifiability_status.value,
            "calibration_allowed": item.calibration_allowed,
            "observational_data_required": item.required_observation_types,
            "linked_observables": item.observable_variables,
            "confounders": item.confounders,
            "data_available": False,
            "scientific_blockers": ("REAL_AGRONOMIC_DATA_NOT_AVAILABLE", "SYNTHETIC_DATA_NOT_SCIENTIFIC_EVIDENCE"),
        }

    @staticmethod
    def _components(campaign: CampaignResult) -> tuple[ComponentReadiness, ...]:
        return (
            ComponentReadiness("mechanistic_model", ScientificReadinessStatus.READY, ScientificReadinessStatus.INSUFFICIENT_DATA, ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED, ("growth/radiation/water/stress/greenhouse contracts and tests exist",), ("verified experimental observations required",)),
            ComponentReadiness("phenology", ScientificReadinessStatus.READY, ScientificReadinessStatus.INSUFFICIENT_DATA, ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED, ("PhenologyEngine and annual/perennial scopes exist",), ("local crop/variety calibration and validation data required",)),
            ComponentReadiness("greenhouse", ScientificReadinessStatus.READY, ScientificReadinessStatus.INSUFFICIENT_DATA, ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED, ("simplified physical model and feedback loop available",), ("EnergyPlus optional; no experimental greenhouse dataset",)),
            ComponentReadiness("observations", ScientificReadinessStatus.READY, ScientificReadinessStatus.INSUFFICIENT_DATA, ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED, ("ingestion/alignment/comparison/diagnostics exercised",), ("verified real observations required",)),
            ComponentReadiness("instrumentation", ScientificReadinessStatus.READY, ScientificReadinessStatus.INSUFFICIENT_DATA, ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED, ("simulated backend and future-real adapter contract exercised",), ("real sensor deployment not executed",)),
            ComponentReadiness("identifiability", ScientificReadinessStatus.READY, ScientificReadinessStatus.INSUFFICIENT_DATA, ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED, ("existing analyzer preserves synthetic-only conservatism",), ("real data and confounder evidence required",)),
        )


def evaluate_scientific_readiness(root: str | Path) -> ScientificReadinessEvaluation:
    return ScientificReadinessGate(root).evaluate()


__all__ = [
    "ComponentReadiness",
    "EvidenceType",
    "ScientificReadinessEvaluation",
    "ScientificReadinessGate",
    "ScientificReadinessReport",
    "ScientificReadinessStatus",
    "SyntheticBenchmarkResult",
    "SyntheticBenchmarkSuite",
    "evaluate_scientific_readiness",
]
