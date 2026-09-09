"""Read-only temporal and contextual alignment of TwinState and observations."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable, Mapping

from agri_twin.application.twin_state import TwinState, TwinStateRepository
from agri_twin.domain.calibration import Observation, ObservationDataset, ObservationResolution
from agri_twin.domain.observation_ingestion import QualityFlag, _normalize_value
from agri_twin.domain.validation import AlignmentPolicy


class AlignmentStatus(StrEnum):
    MATCHED = "MATCHED"
    NO_MATCH = "NO_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    INCOMPATIBLE_CONTEXT = "INCOMPATIBLE_CONTEXT"
    INVALID_OBSERVATION = "INVALID_OBSERVATION"
    INVALID_TWIN_STATE = "INVALID_TWIN_STATE"
    MISSING_SIMULATION_VARIABLE = "MISSING_SIMULATION_VARIABLE"
    UNIT_ERROR = "UNIT_ERROR"


class CycleResolution(StrEnum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    NOT_RESOLVED = "NOT_RESOLVED"


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    status: AlignmentStatus
    observation_id: str | None
    plot_id: str | None
    cycle_id: str | None
    observation_time: datetime
    simulation_time: datetime | None
    time_delta_seconds: float | None
    alignment_method: AlignmentPolicy
    cycle_resolution: CycleResolution = CycleResolution.NOT_RESOLVED
    reason: str = ""
    context_match: bool = False

    @property
    def time_delta(self) -> float | None:
        return self.time_delta_seconds


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    alignment: AlignmentResult
    variable: str
    crop: str | None
    variety: str | None
    observed_value: float | str | None
    observed_unit: str | None
    simulated_value: float | str | None
    simulated_unit: str | None
    residual: float | None
    absolute_error: float | None
    observed_uncertainty: float | None
    quality: str
    observed_provenance: str
    simulation_provenance: str
    phenological_stage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alignment": {
                "status": self.alignment.status.value,
                "observation_id": self.alignment.observation_id,
                "plot_id": self.alignment.plot_id,
                "cycle_id": self.alignment.cycle_id,
                "observation_time": self.alignment.observation_time.isoformat(),
                "simulation_time": self.alignment.simulation_time.isoformat() if self.alignment.simulation_time else None,
                "time_delta_seconds": self.alignment.time_delta_seconds,
                "alignment_method": self.alignment.alignment_method.value,
                "cycle_resolution": self.alignment.cycle_resolution.value,
                "reason": self.alignment.reason,
                "context_match": self.alignment.context_match,
            },
            "variable": self.variable,
            "crop": self.crop,
            "variety": self.variety,
            "observed_value": self.observed_value,
            "observed_unit": self.observed_unit,
            "simulated_value": self.simulated_value,
            "simulated_unit": self.simulated_unit,
            "residual": self.residual,
            "absolute_error": self.absolute_error,
            "observed_uncertainty": self.observed_uncertainty,
            "quality": self.quality,
            "observed_provenance": self.observed_provenance,
            "simulation_provenance": self.simulation_provenance,
            "phenological_stage": self.phenological_stage,
        }


@dataclass(frozen=True, slots=True)
class ComparisonDataset:
    results: tuple[ComparisonResult, ...]
    matched_count: int
    unmatched_count: int
    ambiguous_count: int
    invalid_count: int

    @property
    def coverage_ratio(self) -> float:
        return self.matched_count / len(self.results) if self.results else 0.0

    def for_plot(self, plot_id: str) -> tuple[ComparisonResult, ...]:
        return tuple(item for item in self.results if item.alignment.plot_id == plot_id)

    def for_crop(self, crop: str) -> tuple[ComparisonResult, ...]:
        return tuple(item for item in self.results if item.crop == crop)

    def for_variety(self, variety: str) -> tuple[ComparisonResult, ...]:
        return tuple(item for item in self.results if item.variety == variety)


@dataclass(frozen=True, slots=True)
class TemporalAlignment:
    policy: AlignmentPolicy = AlignmentPolicy.EXACT
    max_time_delta_seconds: float | None = None
    tie_break: str = "PREVIOUS"

    def __post_init__(self) -> None:
        if self.max_time_delta_seconds is not None and (not math.isfinite(self.max_time_delta_seconds) or self.max_time_delta_seconds < 0):
            raise ValueError("max_time_delta_seconds must be finite and non-negative")
        if self.tie_break not in {"PREVIOUS", "NEXT"}:
            raise ValueError("tie_break must be PREVIOUS or NEXT")

    def align(self, observation: Observation, states: Iterable[TwinState]) -> AlignmentResult:
        observation_time = _utc(observation.timestamp)
        candidates = tuple(sorted(states, key=lambda state: (state.simulation_time, state.plot_id, state.cycle_id)))
        if not candidates:
            return self._result(AlignmentStatus.NO_MATCH, observation, None, "no TwinState history")
        context = [state for state in candidates if self._context_matches(observation, state)]
        if not context:
            return self._result(AlignmentStatus.INCOMPATIBLE_CONTEXT, observation, None, "plot, crop or variety context is incompatible")
        cycle_resolution = CycleResolution.EXPLICIT if observation.cycle_id else CycleResolution.NOT_RESOLVED
        if observation.cycle_id is None:
            cycle_ids = {state.cycle_id for state in context}
            if len(cycle_ids) > 1:
                return self._result(AlignmentStatus.AMBIGUOUS, observation, None, "multiple candidate cycles", CycleResolution.NOT_RESOLVED)
            cycle_resolution = CycleResolution.INFERRED
        else:
            context = [state for state in context if state.cycle_id == observation.cycle_id]
            if not context:
                return self._result(AlignmentStatus.NO_MATCH, observation, None, "explicit cycle_id has no matching TwinState", cycle_resolution)
        chosen = self._choose(observation_time, context)
        if chosen is None:
            return self._result(AlignmentStatus.NO_MATCH, observation, None, "no state satisfies alignment policy", cycle_resolution)
        delta = (chosen.simulation_time - observation_time).total_seconds()
        return self._result(AlignmentStatus.MATCHED, observation, chosen, "matched", cycle_resolution, True, delta)

    def _choose(self, observation_time: datetime, states: list[TwinState]) -> TwinState | None:
        if self.policy is AlignmentPolicy.EXACT:
            return next((state for state in states if _utc(state.simulation_time) == observation_time), None)
        if self.policy is AlignmentPolicy.SAME_DAY:
            same_day = [state for state in states if _utc(state.simulation_time).date() == observation_time.date()]
            return self._nearest(observation_time, same_day)
        if self.policy is AlignmentPolicy.NEAREST:
            candidate = self._nearest(observation_time, states)
            if candidate is None:
                return None
            if self.max_time_delta_seconds is not None and abs((candidate.simulation_time - observation_time).total_seconds()) > self.max_time_delta_seconds:
                return None
            return candidate
        return self._nearest(observation_time, states)

    def _nearest(self, timestamp: datetime, states: list[TwinState]) -> TwinState | None:
        if not states:
            return None
        return min(states, key=lambda state: (abs((_utc(state.simulation_time) - timestamp).total_seconds()), 0 if (_utc(state.simulation_time) <= timestamp and self.tie_break == "PREVIOUS") or (_utc(state.simulation_time) >= timestamp and self.tie_break == "NEXT") else 1, _utc(state.simulation_time)))

    @staticmethod
    def _context_matches(observation: Observation, state: TwinState) -> bool:
        return (observation.plot_id is None or observation.plot_id == state.plot_id) and (observation.crop is None or observation.crop == state.crop) and (observation.variety is None or observation.variety == state.variety)

    def _result(self, status, observation, state, reason, cycle_resolution=CycleResolution.NOT_RESOLVED, context_match=False, delta=None):
        return AlignmentResult(status, observation.dataset_id, observation.plot_id, state.cycle_id if state else observation.cycle_id, _utc(observation.timestamp), _utc(state.simulation_time) if state else None, delta, self.policy, cycle_resolution, reason, context_match)


def compare_observation(repository: TwinStateRepository, observation: Observation, alignment: TemporalAlignment = TemporalAlignment()) -> ComparisonResult:
    if observation.value is None or observation.quality.upper() in {QualityFlag.MISSING.value, QualityFlag.INVALID.value, QualityFlag.DUPLICATE.value, QualityFlag.OUT_OF_RANGE.value}:
        result = AlignmentResult(AlignmentStatus.INVALID_OBSERVATION, observation.dataset_id, observation.plot_id, observation.cycle_id, _utc(observation.timestamp), None, None, alignment.policy, CycleResolution.EXPLICIT if observation.cycle_id else CycleResolution.NOT_RESOLVED, f"observation quality is {observation.quality}")
        return _empty_result(result, observation)
    states = repository.history(observation.plot_id, observation.cycle_id) if observation.plot_id and observation.cycle_id else repository.history(observation.plot_id) if observation.plot_id else ()
    match = alignment.align(observation, states)
    if match.status is not AlignmentStatus.MATCHED:
        return _empty_result(match, observation)
    state = repository.get_exact(match.plot_id, match.cycle_id, match.simulation_time)
    field_name, simulated_unit = _VARIABLES.get(observation.variable, (None, None))
    if field_name is None:
        return _empty_result(replace(match, status=AlignmentStatus.MISSING_SIMULATION_VARIABLE, reason="TwinState has no compatible variable"), observation)
    simulated_value = getattr(state, field_name)
    if simulated_value is None:
        return _empty_result(replace(match, status=AlignmentStatus.MISSING_SIMULATION_VARIABLE, reason="TwinState variable is unknown"), observation)
    try:
        observed_value, normalized_unit = _normalize_value(observation.variable, float(observation.value), observation.unit)
    except (ValueError, TypeError, KeyError):
        return _empty_result(replace(match, status=AlignmentStatus.UNIT_ERROR, reason="observation unit cannot be normalized"), observation)
    if normalized_unit != simulated_unit:
        return _empty_result(replace(match, status=AlignmentStatus.UNIT_ERROR, reason=f"simulation unit is {simulated_unit}, observation unit is {normalized_unit}"), observation)
    residual = float(simulated_value) - observed_value
    return ComparisonResult(match, observation.variable, state.crop, state.variety, observed_value, normalized_unit, simulated_value, simulated_unit, residual, abs(residual), observation.uncertainty, observation.quality, observation.source, state.state_provenance, state.phenological_stage)


def compare_dataset(repository: TwinStateRepository, dataset: ObservationDataset | Iterable[Observation], alignment: TemporalAlignment = TemporalAlignment()) -> ComparisonDataset:
    observations = dataset.observations if isinstance(dataset, ObservationDataset) else tuple(dataset)
    results = tuple(compare_observation(repository, observation, alignment) for observation in observations)
    matched = sum(item.alignment.status is AlignmentStatus.MATCHED for item in results)
    ambiguous = sum(item.alignment.status is AlignmentStatus.AMBIGUOUS for item in results)
    invalid = sum(item.alignment.status in {AlignmentStatus.INVALID_OBSERVATION, AlignmentStatus.UNIT_ERROR, AlignmentStatus.MISSING_SIMULATION_VARIABLE} for item in results)
    return ComparisonDataset(results, matched, len(results) - matched - ambiguous - invalid, ambiguous, invalid)


def _empty_result(alignment: AlignmentResult, observation: Observation) -> ComparisonResult:
    return ComparisonResult(alignment, observation.variable, observation.crop, observation.variety, observation.value, observation.unit, None, None, None, None, observation.uncertainty, observation.quality, observation.source, "SIMULATION")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


_VARIABLES: Mapping[str, tuple[str, str]] = {
    "lai": ("lai", "m2_m-2"),
    "biomass": ("biomass_g_m2", "g_m-2"),
    "soil_water_content": ("soil_water_m3_m3", "m3_m-3"),
    "air_temperature": ("temperature_c", "degC"),
    "relative_humidity": ("relative_humidity_pct", "%"),
    "solar_radiation": ("radiation_w_m2", "W_m-2"),
    "co2": ("co2_ppm", "ppm"),
}


__all__ = ["AlignmentResult", "AlignmentStatus", "ComparisonDataset", "ComparisonResult", "CycleResolution", "TemporalAlignment", "compare_dataset", "compare_observation"]
