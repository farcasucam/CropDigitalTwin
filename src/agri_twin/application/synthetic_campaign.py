"""Phase 5.18 synthetic observation campaign orchestration layer.

This module does not introduce a second observation, acquisition, alignment,
diagnostics, identifiability, registry, clock or scheduler system. It wires
together the existing Phase 5.8-5.17 components to run a reproducible,
end-to-end, fully synthetic observation campaign so the software pipeline can
be qualified before any real agronomic data becomes available.

Scientific boundaries (must not be crossed by this module):
- no parameter calibration (no GridSearchCalibrator, no optimizer);
- no data assimilation (TwinState is never derived from observations);
- no claim of experimental/scientific validation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agri_twin.application.clock import SimulationClock
from agri_twin.application.error_diagnostics import ErrorDiagnostics, diagnose
from agri_twin.application.instrumentation import (
    AcquisitionConnectionStatus,
    AcquisitionFaults,
    AcquisitionRecord,
    FakeExternalSensorSource,
    FutureRealAcquisitionAdapter,
    InstrumentationSpecification,
    SimulatedAcquisitionBackend,
)
from agri_twin.application.observation_plan import (
    ExperimentalObservationPlan,
    ObservationPlanItem,
    PlanPriority,
    PlanStatus,
    RequirementSource,
)
from agri_twin.application.parameter_identifiability import (
    IdentifiabilityReport,
    IdentifiabilityStatus,
    ParameterIdentifiabilityAnalyzer,
)
from agri_twin.application.twin_alignment import ComparisonDataset, TemporalAlignment, compare_dataset
from agri_twin.application.twin_state import InMemoryTwinStateRepository, TwinSnapshot, TwinState, TwinStateRepository
from agri_twin.domain.calibration import DatasetRole, ObservationDataset
from agri_twin.domain.observation_ingestion import (
    CANONICAL_UNITS,
    ObservationIngestionResult,
    ObservationSourceType,
    QualityFlag,
    ingest_rows,
)
from agri_twin.domain.parameter_audit import ParameterRegistry


class SyntheticCampaignError(ValueError):
    """Raised for invalid campaign configuration."""


# Only continuous variables supported by SimulatedAcquisitionBackend and directly
# comparable against an existing TwinState field (see twin_alignment._VARIABLES).
DEFAULT_VARIABLES: tuple[str, ...] = (
    "air_temperature",
    "relative_humidity",
    "solar_radiation",
    "co2",
    "lai",
    "biomass",
    "soil_water_content",
)

# Which TwinState field a given acquisition variable feeds when synthesizing
# the deterministic "twin ground truth" used only to qualify the pipeline.
VARIABLE_TWIN_FIELDS: dict[str, str] = {
    "air_temperature": "temperature_c",
    "relative_humidity": "relative_humidity_pct",
    "solar_radiation": "radiation_w_m2",
    "co2": "co2_ppm",
    "lai": "lai",
    "biomass": "biomass_g_m2",
    "soil_water_content": "soil_water_m3_m3",
}


@dataclass(frozen=True, slots=True)
class CampaignCropSpec:
    """One synthetic plot/cycle scope covered by the campaign."""

    crop: str
    variety: str | None
    environment: str
    plot_id: str
    cycle_id: str
    cycle_type: str
    phenological_stage: str
    variables: tuple[str, ...] = DEFAULT_VARIABLES


def default_campaign_crops() -> tuple[CampaignCropSpec, ...]:
    """The 7 project crops, known varieties, annual/perennial cycles and lettuce multi-cycle coverage."""

    return (
        CampaignCropSpec("tomato", "RAF", "GREENHOUSE", "P-TOMATO", "C-TOMATO-1", "annual", "vegetative_growth"),
        # lettuce cycle_1/cycle_2 use distinct plot_id on purpose: ObservationIngestion deduplicates
        # by (plot_id, variable, timestamp), so two concurrent cycles sharing one plot_id would be
        # (correctly) flagged as duplicates. Using two plots keeps cycle isolation observable end-to-end.
        CampaignCropSpec("lettuce", None, "GREENHOUSE", "P-LETTUCE-1", "cycle_1", "annual", "vegetative_growth"),
        CampaignCropSpec("lettuce", None, "GREENHOUSE", "P-LETTUCE-2", "cycle_2", "annual", "establishment"),
        CampaignCropSpec("pepper", "Lamuyo", "GREENHOUSE", "P-PEPPER", "C-PEPPER-1", "annual", "establishment"),
        CampaignCropSpec("grape", "Monastrell", "OUTDOOR", "P-GRAPE", "C-GRAPE-1", "perennial", "yield_maturation"),
        CampaignCropSpec("peach", None, "OUTDOOR", "P-PEACH", "C-PEACH-1", "perennial", "establishment"),
        CampaignCropSpec("plum", "Suplum 26", "OUTDOOR", "P-PLUM", "C-PLUM-1", "perennial", "yield_maturation"),
        CampaignCropSpec("apple", None, "OUTDOOR", "P-APPLE", "C-APPLE-1", "perennial", "post_harvest_dormancy"),
    )


@dataclass(frozen=True, slots=True)
class CampaignConfiguration:
    """Fully deterministic campaign inputs. No wall-clock or network sources are allowed."""

    campaign_id: str
    root: Path
    start: datetime
    end: datetime
    interval_seconds: float = 3600.0
    seed: int = 0
    crops: tuple[CampaignCropSpec, ...] = field(default_factory=default_campaign_crops)
    faults: AcquisitionFaults = field(default_factory=AcquisitionFaults)
    alignment: TemporalAlignment = field(default_factory=TemporalAlignment)
    outlier_threshold: float | None = None
    bias_threshold: float | None = None
    known_bias_variable: str | None = None
    known_bias_offset: float = 0.0
    temporal_shift_variable: str | None = None
    temporal_shift_seconds: float = 0.0
    use_future_real_adapter: bool = False

    def __post_init__(self) -> None:
        if not self.campaign_id:
            raise SyntheticCampaignError("campaign_id is required")
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end < self.start:
            raise SyntheticCampaignError("campaign window must be ordered and timezone-aware")
        if self.interval_seconds <= 0:
            raise SyntheticCampaignError("interval_seconds must be positive")
        if not self.crops:
            raise SyntheticCampaignError("at least one crop scope is required")
        keys = [(item.plot_id, item.cycle_id) for item in self.crops]
        if len(keys) != len(set(keys)):
            raise SyntheticCampaignError("plot_id/cycle_id pairs must be unique")

    def config_hash(self) -> str:
        payload = {
            "campaign_id": self.campaign_id,
            "root": str(self.root),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "interval_seconds": self.interval_seconds,
            "seed": self.seed,
            "crops": [asdict(item) for item in self.crops],
            "faults": asdict(self.faults),
            "alignment_policy": self.alignment.policy.value,
            "alignment_max_time_delta_seconds": self.alignment.max_time_delta_seconds,
            "alignment_tie_break": self.alignment.tie_break,
            "outlier_threshold": self.outlier_threshold,
            "bias_threshold": self.bias_threshold,
            "known_bias_variable": self.known_bias_variable,
            "known_bias_offset": self.known_bias_offset,
            "temporal_shift_variable": self.temporal_shift_variable,
            "temporal_shift_seconds": self.temporal_shift_seconds,
            "use_future_real_adapter": self.use_future_real_adapter,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CampaignQualityReport:
    """JSON-serializable, deterministic campaign summary. Never claims scientific validation."""

    campaign_id: str
    configuration_hash: str
    synthetic: bool
    forcing_source: str
    observation_count: int
    acquisition_count: int
    comparison_count: int
    valid_comparison_count: int
    quality_counts: dict[str, int]
    diagnostic_summary: dict[str, Any]
    identifiability_summary: dict[str, Any]
    determinism_status: str
    backend_substitution_status: str
    pipeline_status: str
    scientific_status: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(slots=True)
class CampaignResult:
    """Full pipeline output. Raw components are kept for inspection by tests."""

    configuration: CampaignConfiguration
    plan: ExperimentalObservationPlan
    specifications: tuple[InstrumentationSpecification, ...]
    truth_records: tuple[AcquisitionRecord, ...]
    acquisition_records: tuple[AcquisitionRecord, ...]
    ingestion: ObservationIngestionResult
    twin_repository: TwinStateRepository
    comparison: ComparisonDataset
    diagnostics: ErrorDiagnostics
    identifiability_before: IdentifiabilityReport
    identifiability_after: IdentifiabilityReport
    report: CampaignQualityReport


class SyntheticObservationCampaign:
    """Coordinates the existing 5.8-5.17 components; introduces no new science."""

    def __init__(self, configuration: CampaignConfiguration) -> None:
        self.configuration = configuration

    def run(self) -> CampaignResult:
        cfg = self.configuration
        registry = ParameterRegistry.from_repository(cfg.root)
        analyzer = ParameterIdentifiabilityAnalyzer(registry, repository_root=cfg.root)
        identifiability_before = analyzer.analyze_all()
        plan = ExperimentalObservationPlan.from_identifiability_report(identifiability_before)
        specifications = self._build_specifications(plan)

        clock = SimulationClock(cfg.start)
        truth_records = SimulatedAcquisitionBackend(clock, AcquisitionFaults()).acquire(
            cfg.start, cfg.end, interval_seconds=cfg.interval_seconds, specifications=specifications, seed=cfg.seed
        )
        acquisition_records = SimulatedAcquisitionBackend(clock, cfg.faults).acquire(
            cfg.start, cfg.end, interval_seconds=cfg.interval_seconds, specifications=specifications, seed=cfg.seed
        )
        acquisition_records = self._apply_controlled_defects(acquisition_records)

        backend_substitution_status = "SIMULATED_ACQUISITION_ONLY"
        source_type = ObservationSourceType.SYNTHETIC_TEST
        if cfg.use_future_real_adapter:
            acquisition_records = self._through_future_real_adapter(acquisition_records, specifications)
            backend_substitution_status = "FUTURE_REAL_ADAPTER_SUBSTITUTED_WITH_FAKE_EXTERNAL_SOURCE"
            source_type = ObservationSourceType.MEASURED

        ingestion = ingest_rows(
            (record.to_row() for record in acquisition_records),
            dataset_id=f"{cfg.campaign_id}-observations",
            role=DatasetRole.TEST,
            source="synthetic_observation_campaign",
            source_type=source_type,
        )

        twin_repository = self._build_twin_repository(truth_records)
        comparison = (
            compare_dataset(twin_repository, ingestion.dataset, cfg.alignment)
            if ingestion.dataset is not None
            else ComparisonDataset((), 0, 0, 0, 0)
        )
        diagnostics = diagnose(comparison, outlier_threshold=cfg.outlier_threshold, bias_threshold=cfg.bias_threshold)
        identifiability_after = analyzer.analyze_all(ingestion.dataset)

        report = self._build_report(
            plan, acquisition_records, ingestion, comparison, diagnostics, identifiability_after, backend_substitution_status
        )
        return CampaignResult(
            cfg, plan, specifications, truth_records, acquisition_records, ingestion,
            twin_repository, comparison, diagnostics, identifiability_before, identifiability_after, report,
        )

    def _build_specifications(self, plan: ExperimentalObservationPlan) -> tuple[InstrumentationSpecification, ...]:
        cfg = self.configuration
        specifications: list[InstrumentationSpecification] = []
        for crop_spec in cfg.crops:
            for variable in crop_spec.variables:
                candidates = plan.for_observable(variable)
                item = next((entry for entry in candidates if entry.crop in (None, crop_spec.crop)), None)
                if item is None:
                    item = candidates[0] if candidates else _fallback_plan_item(variable)
                unit = CANONICAL_UNITS.get(variable, "UNKNOWN")
                base = InstrumentationSpecification.from_plan_item(
                    item,
                    instrument_id=f"SIM-{crop_spec.plot_id}-{crop_spec.cycle_id}-{variable}",
                    device_id=f"DEV-{crop_spec.plot_id}-{variable}",
                    unit=unit,
                    interval=f"{cfg.interval_seconds:g}s",
                )
                specifications.append(
                    replace(
                        base,
                        plot_id=crop_spec.plot_id,
                        cycle_id=crop_spec.cycle_id,
                        crop=crop_spec.crop,
                        variety=crop_spec.variety,
                        environment=crop_spec.environment,
                        phenological_stage=crop_spec.phenological_stage,
                        clock_source="SimulationClock",
                        timezone="UTC",
                    )
                )
        return tuple(specifications)

    def _apply_controlled_defects(self, records: tuple[AcquisitionRecord, ...]) -> tuple[AcquisitionRecord, ...]:
        cfg = self.configuration
        if not cfg.known_bias_variable and not cfg.temporal_shift_variable:
            return records
        updated: list[AcquisitionRecord] = []
        for record in records:
            item = record
            if (
                cfg.known_bias_variable
                and item.variable == cfg.known_bias_variable
                and item.quality is QualityFlag.VALID
                and isinstance(item.value, (int, float))
            ):
                item = replace(
                    item,
                    value=float(item.value) + cfg.known_bias_offset,
                    configuration=f"{item.configuration}|known_bias_offset={cfg.known_bias_offset}",
                )
            if cfg.temporal_shift_variable and item.variable == cfg.temporal_shift_variable and item.timestamp.tzinfo is not None:
                item = replace(
                    item,
                    timestamp=item.timestamp + timedelta(seconds=cfg.temporal_shift_seconds),
                    configuration=f"{item.configuration}|temporal_shift_seconds={cfg.temporal_shift_seconds}",
                )
            updated.append(item)
        return tuple(updated)

    def _through_future_real_adapter(
        self, records: tuple[AcquisitionRecord, ...], specifications: tuple[InstrumentationSpecification, ...]
    ) -> tuple[AcquisitionRecord, ...]:
        spec_by_instrument = {spec.instrument_id: spec for spec in specifications}
        source = FakeExternalSensorSource(seed=self.configuration.seed)
        adapter = FutureRealAcquisitionAdapter(status=AcquisitionConnectionStatus.ONLINE, available=True)
        adapted: list[AcquisitionRecord] = []
        for record in records:
            if record.quality is not QualityFlag.VALID:
                adapted.append(record)
                continue
            spec = spec_by_instrument.get(record.instrument_id)
            payload = source.payload(
                timestamp=record.timestamp, variable=record.variable, value=record.value, unit=record.unit,
                instrument_id=record.instrument_id, device_id=record.device_id, plot_id=record.plot_id,
                cycle_id=record.cycle_id, crop=record.crop, variety=record.variety, environment=record.environment,
                phenological_stage=record.phenological_stage, quality=record.quality.value,
            )
            adapted.append(adapter.adapt(payload, specification=spec))
        return tuple(adapted)

    def _build_twin_repository(self, truth_records: tuple[AcquisitionRecord, ...]) -> TwinStateRepository:
        cfg = self.configuration
        crop_spec_by_key = {(item.plot_id, item.cycle_id): item for item in cfg.crops}
        grouped: dict[datetime, dict[tuple[str, str], dict[str, float]]] = {}
        for record in truth_records:
            if record.quality is not QualityFlag.VALID or not isinstance(record.value, (int, float)):
                continue
            if record.variable not in VARIABLE_TWIN_FIELDS or record.plot_id is None or record.cycle_id is None:
                continue
            key = (record.plot_id, record.cycle_id)
            grouped.setdefault(record.timestamp, {}).setdefault(key, {})[record.variable] = float(record.value)
        repository = InMemoryTwinStateRepository()
        for timestamp in sorted(grouped):
            states: list[TwinState] = []
            for key, values in grouped[timestamp].items():
                spec = crop_spec_by_key.get(key)
                if spec is None:
                    continue
                field_values = {VARIABLE_TWIN_FIELDS[variable]: value for variable, value in values.items()}
                states.append(
                    TwinState(
                        simulation_time=timestamp,
                        plot_id=spec.plot_id,
                        cycle_id=spec.cycle_id,
                        crop=spec.crop,
                        variety=spec.variety or "",
                        cycle_status="ACTIVE",
                        phenological_stage=spec.phenological_stage,
                        weather_source="SYNTHETIC_TWIN_FORCING",
                        weather_timestamp=timestamp,
                        **field_values,
                    )
                )
            if states:
                repository.save_snapshot(TwinSnapshot(timestamp, tuple(sorted(states, key=lambda item: (item.plot_id, item.cycle_id)))))
        return repository

    def _build_report(
        self,
        plan: ExperimentalObservationPlan,
        acquisition_records: tuple[AcquisitionRecord, ...],
        ingestion: ObservationIngestionResult,
        comparison: ComparisonDataset,
        diagnostics: ErrorDiagnostics,
        identifiability_after: IdentifiabilityReport,
        backend_substitution_status: str,
    ) -> CampaignQualityReport:
        cfg = self.configuration
        # Acquisition-level faults (missing/invalid/out_of_range/unit_error) are tagged on the
        # AcquisitionRecord itself; duplicates are only detected downstream by ObservationIngestion.
        quality_counts = {
            "valid": sum(record.quality is QualityFlag.VALID for record in acquisition_records),
            "missing": sum(record.quality is QualityFlag.MISSING for record in acquisition_records),
            "invalid": sum(record.quality is QualityFlag.INVALID for record in acquisition_records),
            "duplicate": sum(issue.quality is QualityFlag.DUPLICATE for issue in ingestion.qc),
            "out_of_range": sum(record.quality is QualityFlag.OUT_OF_RANGE for record in acquisition_records),
            "unit_error": sum(record.quality is QualityFlag.UNIT_ERROR for record in acquisition_records),
        }
        identifiability_summary = {
            "total_assessments": len(identifiability_after.assessments),
            "by_status": {status.value: len(identifiability_after.by_status(status)) for status in IdentifiabilityStatus},
            "synthetic_data_only": identifiability_after.synthetic_data_only,
            "real_data_available": identifiability_after.real_data_available,
        }
        pipeline_status = "SUCCESS" if ingestion.dataset is not None else "NO_VALID_OBSERVATIONS"
        return CampaignQualityReport(
            campaign_id=cfg.campaign_id,
            configuration_hash=cfg.config_hash(),
            synthetic=True,
            forcing_source=f"SimulationClock+SimulatedAcquisitionBackend(seed={cfg.seed})",
            observation_count=len(ingestion.dataset.observations) if ingestion.dataset is not None else 0,
            acquisition_count=len(acquisition_records),
            comparison_count=len(comparison.results),
            valid_comparison_count=comparison.matched_count,
            quality_counts=quality_counts,
            diagnostic_summary=diagnostics.global_summary().to_dict(),
            identifiability_summary=identifiability_summary,
            determinism_status="DETERMINISTIC_GIVEN_FIXED_SEED_CLOCK_PLAN_AND_INSTRUMENTATION",
            backend_substitution_status=backend_substitution_status,
            pipeline_status=pipeline_status,
            scientific_status=(
                "SOFTWARE_PIPELINE_QUALIFIED",
                "END_TO_END_OBSERVATION_FLOW_VERIFIED",
                "NOT_SCIENTIFICALLY_VALIDATED",
                "CALIBRATION_NOT_PERFORMED",
                "DATA_ASSIMILATION_NOT_IMPLEMENTED",
            ),
            limitations=(
                "REAL AGRONOMIC DATA NOT AVAILABLE",
                "SIMULATED ACQUISITION ONLY" if backend_substitution_status == "SIMULATED_ACQUISITION_ONLY"
                else "BACKEND SUBSTITUTION DEMONSTRATED WITH FakeExternalSensorSource ONLY (NO HARDWARE OR NETWORK)",
                "CALIBRATION NOT PERFORMED",
                "DATA ASSIMILATION NOT IMPLEMENTED",
                "EXPERIMENTAL VALIDATION NOT CLAIMED",
            ),
        )


def _fallback_plan_item(variable: str) -> ObservationPlanItem:
    """Minimal ObservationPlanItem for variables not covered by any registry parameter (e.g. relative_humidity)."""

    return ObservationPlanItem(
        observation_id=f"campaign.fallback.{variable}",
        parameter_ids=(),
        variable=variable,
        purpose=f"Synthetic campaign observable coverage for {variable}",
        crop=None,
        variety=None,
        plot=None,
        environment=None,
        phenological_stage=None,
        measurement_method="synthetic_campaign_instrument",
        unit=None,
        temporal_resolution="hourly",
        spatial_scope="plot",
        required_conditions=(),
        uncertainty_target="UNKNOWN",
        quality_requirements=("VALID", "MISSING", "ESTIMATED", "INVALID", "DUPLICATE", "OUT_OF_RANGE", "UNIT_ERROR"),
        source_type=RequirementSource.ENGINEERING_RECOMMENDATION,
        source_reference=None,
        evidence_level="none",
        confidence="low",
        priority=PlanPriority.LOW,
        status=PlanStatus.PLANNED,
        confounders=(),
        identifiability_status=IdentifiabilityStatus.INSUFFICIENT_DATA,
        notes="Synthetic-only instrumentation fallback; not tied to a registry parameter.",
    )


def campaigns_are_deterministic(first: CampaignResult, second: CampaignResult) -> bool:
    """Compare two campaign executions for reproducibility (Phase 5.18 determinism contract)."""

    first_observations = first.ingestion.dataset.observations if first.ingestion.dataset is not None else ()
    second_observations = second.ingestion.dataset.observations if second.ingestion.dataset is not None else ()
    return (
        first.report.configuration_hash == second.report.configuration_hash
        and first.acquisition_records == second.acquisition_records
        and first_observations == second_observations
        and first.comparison.results == second.comparison.results
        and first.diagnostics.global_summary() == second.diagnostics.global_summary()
        and first.report == second.report
    )


__all__ = [
    "CampaignConfiguration",
    "CampaignCropSpec",
    "CampaignQualityReport",
    "CampaignResult",
    "DEFAULT_VARIABLES",
    "SyntheticCampaignError",
    "SyntheticObservationCampaign",
    "VARIABLE_TWIN_FIELDS",
    "campaigns_are_deterministic",
    "default_campaign_crops",
]
