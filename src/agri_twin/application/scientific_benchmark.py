"""Integrated, reproducible scientific software benchmark orchestration.

This module composes the existing scenario, sensitivity, uncertainty, ensemble,
and diagnostics contracts. It does not implement a second crop model or claim
agronomic validation from synthetic executions.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from agri_twin.application.scenarios import Scenario, ScenarioEvent, ScenarioKind, ScenarioResult, ScenarioRunner
from agri_twin.application.sensitivity import ParameterSensitivityAnalyzer
from agri_twin.application.uncertainty_ensemble import ScenarioEnsemble, ScenarioEnsembleGenerator
from agri_twin.domain.calibration import ObservationDataset
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry


PROVENANCE = "SIMULATED_REAL_DATA_SUBSTITUTE"
SCIENTIFIC_STATUS = "SYNTHETIC_SOFTWARE_BENCHMARK"
BENCHMARK_VERSION = "5.24.1"
BENCHMARK_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
KNOWN_CROPS = ("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple")
KNOWN_VARIETIES = {
    "tomato": "RAF",
    "pepper": "Lamuyo",
    "grape": "Monastrell",
    "plum": "Suplum 26",
}
PERENNIAL_CROPS = {"grape", "peach", "plum", "apple"}


class BenchmarkStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INVALID = "INVALID"


class MetricCategory(StrEnum):
    SOFTWARE = "software_metric"
    SCIENTIFIC = "scientific_metric"
    ROBUSTNESS = "robustness_metric"


@dataclass(frozen=True, slots=True)
class BenchmarkMetric:
    name: str
    value: float | None
    category: MetricCategory
    unit: str | None = None
    status: str = "AVAILABLE"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"category": self.category.value}


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    model_score: float | None
    baseline_score: float | None
    relative_difference: float | None
    improvement: float | None
    label: str = SCIENTIFIC_STATUS
    interpretation: str = "Synthetic software comparison; not biological validation."

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    benchmark_id: str
    scenario: Scenario
    plot_id: str | None
    cycle_id: str
    environment: str
    seed: int
    ensemble_method: str = "monte_carlo"
    ensemble_members: int = 6
    parameter_ids: tuple[str, ...] = ("radiation.rue", "greenhouse.cover_transmission")
    observation_dataset: ObservationDataset | None = None

    @property
    def scenario_id(self) -> str:
        return self.scenario.scenario_id

    @property
    def start_time(self) -> datetime:
        return self.scenario.start

    @property
    def end_time(self) -> datetime:
        return self.scenario.end

    def definition_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "scenario_id": self.scenario_id,
            "crop": self.scenario.crop,
            "variety": self.scenario.variety,
            "plot_id": self.plot_id,
            "cycle_id": self.cycle_id,
            "environment": self.environment,
            "seed": self.seed,
            "ensemble_method": self.ensemble_method,
            "ensemble_members": self.ensemble_members,
            "parameter_ids": list(self.parameter_ids),
            "scenario_config_hash": self.scenario.config_hash(),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkDefinition:
    benchmark_id: str
    cases: tuple[BenchmarkCase, ...]
    description: str = "Integrated synthetic software benchmark"
    version: str = BENCHMARK_VERSION
    provenance: str = PROVENANCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "description": self.description,
            "version": self.version,
            "provenance": self.provenance,
            "cases": [case.definition_dict() for case in self.cases],
        }

    def configuration_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    benchmark_id: str
    scenario_id: str
    crop: str
    variety: str | None
    plot_id: str | None
    cycle_id: str
    environment: str
    start_time: datetime
    end_time: datetime
    simulation_step: int
    seed: int
    model_configuration_hash: str
    parameter_configuration_hash: str
    input_hash: str
    result_hash: str
    status: BenchmarkStatus
    metrics: tuple[BenchmarkMetric, ...] = ()
    comparison: BenchmarkComparison | None = None
    sensitivity: dict[str, Any] = field(default_factory=dict)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    ensemble: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "scenario_id": self.scenario_id,
            "crop": self.crop,
            "variety": self.variety,
            "plot_id": self.plot_id,
            "cycle_id": self.cycle_id,
            "environment": self.environment,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "simulation_step": self.simulation_step,
            "seed": self.seed,
            "model_configuration_hash": self.model_configuration_hash,
            "parameter_configuration_hash": self.parameter_configuration_hash,
            "input_hash": self.input_hash,
            "result_hash": self.result_hash,
            "status": self.status.value,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "sensitivity": self.sensitivity,
            "uncertainty": self.uncertainty,
            "ensemble": self.ensemble,
            "warnings": list(self.warnings),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    total_cases: int
    successful_cases: int
    failed_cases: int
    invalid_cases: int
    valid_ensemble_members: int
    invalid_ensemble_members: int
    crops: tuple[str, ...]
    plots: tuple[str, ...]
    environments: tuple[str, ...]
    cycles: tuple[str, ...]
    classification: str = SCIENTIFIC_STATUS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScientificBenchmarkReport:
    version: str
    definition: BenchmarkDefinition
    results: tuple[BenchmarkRun, ...]
    summary: BenchmarkSummary
    configuration_hash: str
    artifact_status: str = SCIENTIFIC_STATUS
    real_data_status: str = "REAL AGRONOMIC DATA NOT VERIFIED"
    calibration_status: str = "CALIBRATION NOT PERFORMED"
    validation_status: str = "EXPERIMENTAL VALIDATION NOT CLAIMED"
    assimilation_status: str = "DATA ASSIMILATION NOT IMPLEMENTED"
    energyplus_status: str = "ENERGYPLUS_UNAVAILABLE"
    limitations: tuple[str, ...] = (
        "Synthetic outputs qualify software behavior only.",
        "No real agronomic dataset is verified.",
        "Sensitivity and ensemble spread do not establish identifiability.",
        "No calibration, experimental validation, or data assimilation is performed.",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "definition": self.definition.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "summary": self.summary.to_dict(),
            "configuration_hash": self.configuration_hash,
            "artifact_status": self.artifact_status,
            "real_data_status": self.real_data_status,
            "calibration_status": self.calibration_status,
            "validation_status": self.validation_status,
            "assimilation_status": self.assimilation_status,
            "energyplus_status": self.energyplus_status,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class ScientificBenchmarkSuite:
    """Compose existing deterministic services into an integrated benchmark."""

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None, runner: ScenarioRunner | None = None) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.runner = runner or ScenarioRunner()
        self.sensitivity = ParameterSensitivityAnalyzer(self.registry, root=self.root)

    @staticmethod
    def energyplus_status() -> str:
        return "ENERGYPLUS_AVAILABLE" if shutil.which("energyplus") else "ENERGYPLUS_UNAVAILABLE"

    def run_case(self, case: BenchmarkCase) -> BenchmarkRun:
        scenario = case.scenario
        model_hash = scenario.config_hash()
        parameter_hash = _hash({record.parameter_id: record.to_dict() for record in self.registry.records})
        input_hash = _hash({"case": case.definition_dict(), "model_configuration_hash": model_hash, "parameter_configuration_hash": parameter_hash})
        result = self.runner.run(scenario)
        final = result.snapshots[-1].crop if result.snapshots else None
        initial_biomass = scenario.initial_crop.biomass_total
        model_score = final.biomass_total if final is not None else None
        relative = ((model_score - initial_biomass) / abs(initial_biomass)) if model_score is not None and initial_biomass else None
        comparison = BenchmarkComparison(model_score, initial_biomass, relative, relative, SCIENTIFIC_STATUS)
        metrics = [
            BenchmarkMetric("final_biomass", model_score, MetricCategory.SOFTWARE, "g_DM_m-2", "AVAILABLE", "Deterministic scenario output"),
            BenchmarkMetric("ensemble_valid_fraction", None, MetricCategory.ROBUSTNESS),
        ]
        sensitivity: dict[str, Any] = {}
        uncertainty: dict[str, Any] = {}
        ensemble_payload: dict[str, Any] = {}
        warnings = list(result.warnings)
        status = BenchmarkStatus.SUCCESS if result.status == "SUCCESS" and final is not None else BenchmarkStatus.FAILED
        failure_reason = None if status is BenchmarkStatus.SUCCESS else "; ".join(result.warnings) or "scenario produced no final snapshot"
        try:
            sensitivity_result = self.sensitivity.analyze_parameter(case.parameter_ids[0], crop=scenario.crop, variety=scenario.variety, environment=case.environment)
            sensitivity["oat"] = sensitivity_result.to_dict()
            sensitivity["multivariable"] = self.sensitivity.analyze_multivariable(tuple(case.parameter_ids[:2]), crop=scenario.crop) if len(case.parameter_ids) >= 2 else None
            generator = ScenarioEnsembleGenerator(self.registry, seed=case.seed, sample_count=case.ensemble_members, crop=scenario.crop, root=self.root)
            ensemble = generator.generate(method=case.ensemble_method, parameter_ids=case.parameter_ids, scenario_id=case.scenario_id)
            ensemble_payload = _ensemble_summary(ensemble)
            uncertainty["report"] = generator.build_report(ensemble)
            metrics[-1] = BenchmarkMetric("ensemble_valid_fraction", ensemble_payload["valid_fraction"], MetricCategory.ROBUSTNESS, "fraction")
        except (KeyError, ValueError, TypeError) as exc:
            warnings.append(f"integrated analysis failed: {exc}")
            if status is BenchmarkStatus.SUCCESS:
                status = BenchmarkStatus.FAILED
            failure_reason = str(exc)
        scientific_result = {
            "model": "SYNTHETIC_SOFTWARE_BENCHMARK",
            "real_observations": bool(case.observation_dataset),
            "metrics_available": False if case.observation_dataset is None else "observation comparison requires explicit verified dataset",
        }
        result_payload = {
            "scenario": result.status,
            "final": final.to_dict() if final is not None else None,
            "sensitivity": sensitivity,
            "uncertainty": uncertainty,
            "ensemble": ensemble_payload,
        }
        result_hash = _hash(result_payload)
        return BenchmarkRun(case.benchmark_id, scenario.scenario_id, scenario.crop, scenario.variety, case.plot_id, case.cycle_id, case.environment, scenario.start, scenario.end, scenario.resolution_seconds, case.seed, model_hash, parameter_hash, input_hash, result_hash, status, tuple(metrics), comparison, sensitivity, uncertainty, ensemble_payload, tuple(warnings), failure_reason)

    def run(self, definition: BenchmarkDefinition | None = None) -> ScientificBenchmarkReport:
        definition = definition or self.default_definition()
        results = tuple(self.run_case(case) for case in definition.cases)
        valid_members = sum(int(result.ensemble.get("valid_members", 0)) for result in results)
        invalid_members = sum(int(result.ensemble.get("invalid_members", 0)) for result in results)
        summary = BenchmarkSummary(
            len(results),
            sum(result.status is BenchmarkStatus.SUCCESS for result in results),
            sum(result.status is BenchmarkStatus.FAILED for result in results),
            sum(result.status is BenchmarkStatus.INVALID for result in results),
            valid_members,
            invalid_members,
            tuple(sorted({result.crop for result in results})),
            tuple(sorted({result.plot_id for result in results if result.plot_id})),
            tuple(sorted({result.environment for result in results})),
            tuple(sorted({result.cycle_id for result in results})),
        )
        return ScientificBenchmarkReport(BENCHMARK_VERSION, definition, results, summary, _hash({"definition": definition.to_dict(), "results": [result.to_dict() for result in results]}), energyplus_status=self.energyplus_status())

    def write_artifacts(self, report: ScientificBenchmarkReport, directory: str | Path | None = None) -> tuple[Path, Path]:
        output_dir = Path(directory) if directory is not None else self.root / "data" / "benchmarks"
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "scientific_benchmark_report.json"
        readme_path = output_dir / "README.md"
        report_path.write_text(report.to_json() + "\n", encoding="utf-8")
        readme_path.write_text(
            "# Scientific benchmark artifact\n\n"
            "This deterministic artifact is a synthetic software benchmark. It does not claim real agronomic validation, calibration, or assimilation.\n\n"
            f"- version: `{report.version}`\n- configuration hash: `{report.configuration_hash}`\n"
            f"- cases: `{report.summary.total_cases}`\n- status: `{report.artifact_status}`\n",
            encoding="utf-8",
        )
        return report_path, readme_path

    def default_definition(self) -> BenchmarkDefinition:
        cases: list[BenchmarkCase] = []
        matrix = self._matrix_cases()
        for case in matrix:
            cases.append(case)
        tomato = next(case for case in matrix if case.scenario.crop == "tomato")
        for scenario_type in ("heat", "drought", "low_radiation", "high_vpd", "co2", "ventilation", "recovery", "combined"):
            scenario = _scenario_for("tomato", "RAF", "plot_12010", "annual-1", "greenhouse", scenario_type, seed=200 + len(cases))
            cases.append(BenchmarkCase(f"case_{scenario.scenario_id}", scenario, "plot_12010", "annual-1", "greenhouse", scenario.seed or 0))
        return BenchmarkDefinition("phase5_24_integrated", tuple(cases), "Integrated deterministic benchmark across crop, plot, cycle, environment, scenario, sensitivity and ensemble dimensions")

    def _matrix_cases(self) -> list[BenchmarkCase]:
        cases: list[BenchmarkCase] = []
        registered = {
            "plot_14705": ("plum", "Suplum 26"),
            "plot_12010": ("tomato", "RAF"),
            "plot_30412": ("grape", "Monastrell"),
            "plot_40811": ("pepper", "Lamuyo"),
        }
        for index, crop in enumerate(KNOWN_CROPS):
            plot_id, variety = next(((plot, value[1]) for plot, value in registered.items() if value[0] == crop), (None, KNOWN_VARIETIES.get(crop)))
            cycles = ("annual-1", "annual-2", "annual-3") if crop == "lettuce" else (("perennial-1",) if crop in PERENNIAL_CROPS else ("annual-1",))
            for cycle_index, cycle_id in enumerate(cycles):
                for environment in ("outdoor", "greenhouse"):
                    scenario = _scenario_for(crop, variety, plot_id, cycle_id, environment, "control", seed=100 + index * 10 + cycle_index)
                    cases.append(BenchmarkCase(f"case_{scenario.scenario_id}", scenario, plot_id, cycle_id, environment, scenario.seed or 0))
        return cases


def _scenario_for(crop: str, variety: str | None, plot_id: str | None, cycle_id: str, environment: str, scenario_type: str, *, seed: int) -> Scenario:
    start = BENCHMARK_TIME + timedelta(days=seed % 5)
    end = start + timedelta(hours=12)
    actual_variety = variety or "UNSPECIFIED"
    initial = CropGrowthState(start, crop, actual_variety, "vegetative_growth", biomass_total=10.0, biomass_leaf=4.0, biomass_stem=3.0, biomass_root=3.0, leaf_area_index=1.0, soil_water_vwc=0.25, phenology_model="BENCHMARK_SYNTHETIC")
    soil = SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 100.0)
    weather = WeatherState(24.0, 65.0, 500.0, 2.0, 180.0, 0.0, 1013.0)
    event_parameters: dict[str, Mapping[str, float]] = {
        "heat": {"temperature_offset_c": 15.0},
        "drought": {"rain_rate_mm_h": 0.0},
        "low_radiation": {"radiation_multiplier": 0.25},
        "high_vpd": {"relative_humidity_pct": 20.0},
        "co2": {"value": 1200.0, "maximum": 2000.0},
        "ventilation": {"value": 1.0, "maximum": 1.0},
        "recovery": {"rain_rate_mm_h": 5.0},
        "combined": {"temperature_offset_c": 8.0, "radiation_multiplier": 0.5},
    }
    events: tuple[ScenarioEvent, ...] = ()
    if scenario_type != "control":
        event_type = {"heat": "heat", "drought": "drought", "low_radiation": "low_radiation", "high_vpd": "high_vpd", "co2": "co2", "ventilation": "ventilation", "recovery": "wet", "combined": "heat"}[scenario_type]
        events = (ScenarioEvent(f"event_{scenario_type}", event_type, start, end, 1.0, event_parameters[scenario_type]),)
    scenario_id = f"{crop}_{cycle_id}_{environment}_{scenario_type}_{plot_id or 'unregistered'}"
    greenhouse_mode = "passive_greenhouse" if environment == "greenhouse" else "outdoor"
    return Scenario(scenario_id, scenario_id, "Synthetic benchmark scenario", crop, variety, start, end, 21600, ScenarioKind.BENCHMARK, initial, soil, weather, greenhouse_mode, events, seed=seed)


def _ensemble_summary(ensemble: ScenarioEnsemble) -> dict[str, Any]:
    valid = [member for member in ensemble.members if member.valid and "biomass" in member.outputs]
    invalid = [member for member in ensemble.members if not member.valid]
    values = sorted(float(member.outputs["biomass"]) for member in valid)
    if not values:
        return {"members": len(ensemble.members), "valid_members": 0, "invalid_members": len(invalid), "failed_members": [member.failure_reason for member in invalid], "valid_fraction": 0.0, "statistics": {}}
    mean = sum(values) / len(values)
    median = values[len(values) // 2] if len(values) % 2 else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2
    return {
        "members": len(ensemble.members),
        "valid_members": len(valid),
        "invalid_members": len(invalid),
        "failed_members": [member.failure_reason for member in invalid],
        "valid_fraction": len(valid) / len(ensemble.members),
        "statistics": {
            "mean": mean,
            "median": median,
            "min": values[0],
            "max": values[-1],
            "standard_deviation": (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5,
            "p10": values[min(len(values) - 1, int(0.10 * len(values)))],
            "p90": values[min(len(values) - 1, int(0.90 * len(values)))],
        },
    }


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


__all__ = [
    "BENCHMARK_TIME",
    "BenchmarkCase",
    "BenchmarkComparison",
    "BenchmarkDefinition",
    "BenchmarkMetric",
    "BenchmarkRun",
    "BenchmarkStatus",
    "BenchmarkSummary",
    "MetricCategory",
    "ScientificBenchmarkReport",
    "ScientificBenchmarkSuite",
]
