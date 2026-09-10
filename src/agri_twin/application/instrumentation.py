"""Modular simulated acquisition contracts; real sensors are intentionally out of scope."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable, Mapping, Protocol

from agri_twin.application.clock import SimulationClock
from agri_twin.application.observation_plan import ExperimentalObservationPlan, ObservationPlanItem
from agri_twin.domain.observation_ingestion import QualityFlag


class AcquisitionError(ValueError):
    """Raised for invalid simulated acquisition configuration."""


class AcquisitionSourceType(StrEnum):
    SYNTHETIC = "synthetic"
    MEASURED = "measured"


@dataclass(frozen=True, slots=True)
class InstrumentationSpecification:
    instrument_id: str
    device_id: str
    observable: str
    variable: str
    unit: str | None = None
    normalized_unit: str | None = None
    method: str = "TO_BE_DEFINED"
    accuracy: str = "UNKNOWN"
    precision: str = "UNKNOWN"
    resolution: str = "UNKNOWN"
    uncertainty: str = "UNKNOWN"
    range_min: float | None = None
    range_max: float | None = None
    sampling_interval: str = "TO_BE_DEFINED"
    aggregation_method: str = "TO_BE_DEFINED"
    timestamp_policy: str = "timezone-aware ISO-8601"
    timezone: str = "UTC"
    clock_source: str = "SimulationClock"
    latency: str = "UNKNOWN"
    parameter_ids: tuple[str, ...] = ()
    plot_id: str | None = None
    cycle_id: str | None = None
    crop: str | None = None
    variety: str | None = None
    environment: str = "UNKNOWN"
    phenological_stage: str | None = None
    installation_location: str = "TO_BE_DEFINED"
    installation_height: str = "TO_BE_DEFINED"
    installation_depth: str = "TO_BE_DEFINED"
    representativeness: str = "UNKNOWN"
    calibration_status: str = "NOT_AVAILABLE"
    calibration_certificate: str = "NOT_AVAILABLE"
    calibration_date: str = "NOT_AVAILABLE"
    calibration_due: str = "NOT_AVAILABLE"
    maintenance_requirements: str = "TO_BE_DEFINED"
    provenance: str = "experimental_observation_plan"
    requirement_source: str = "unknown"
    status: str = "PLANNED"
    notes: str = ""

    @classmethod
    def from_plan_item(cls, item: ObservationPlanItem, *, instrument_id: str, device_id: str, unit: str | None = None, interval: str = "TO_BE_DEFINED") -> "InstrumentationSpecification":
        return cls(instrument_id, device_id, item.variable or item.observation_id, item.variable or item.observation_id, unit, unit, item.measurement_method, uncertainty=item.uncertainty_target, sampling_interval=interval, parameter_ids=item.parameter_ids, plot_id=item.plot, crop=item.crop, variety=item.variety, environment=item.environment or "UNKNOWN", phenological_stage=item.phenological_stage, provenance=item.observation_id, requirement_source=item.source_type.value, status=item.status.value, notes=item.notes)

    def to_dict(self) -> dict[str, Any]:
        result = {}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = list(value) if isinstance(value, tuple) else value
        return result


@dataclass(frozen=True, slots=True)
class AcquisitionRecord:
    acquisition_id: str
    instrument_id: str
    device_id: str
    timestamp: datetime
    timezone: str
    clock_source: str
    variable: str
    value: float | str | None
    unit: str
    plot_id: str | None
    cycle_id: str | None
    crop: str | None
    variety: str | None
    environment: str
    phenological_stage: str | None
    quality: QualityFlag
    provenance: str
    source_type: AcquisitionSourceType = AcquisitionSourceType.SYNTHETIC
    backend: str = "SimulatedAcquisitionBackend"
    simulation_seed: int | None = None
    configuration: str = ""

    def to_row(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp.isoformat(), "variable": self.variable, "value": self.value, "unit": self.unit, "source": self.provenance, "plot_id": self.plot_id, "cycle_id": self.cycle_id, "crop": self.crop, "variety": self.variety, "environment": self.environment, "measurement_method": self.instrument_id, "quality": self.quality.value, "observation_type": "continuous", "source_type": self.source_type.value}

    def to_dict(self) -> dict[str, Any]:
        result = {}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = value.isoformat() if isinstance(value, datetime) else value.value if isinstance(value, StrEnum) else value
        return result


class AcquisitionBackend(Protocol):
    def acquire(self, start: datetime, end: datetime, *, interval_seconds: float, specifications: Iterable[InstrumentationSpecification], seed: int = 0) -> tuple[AcquisitionRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class AcquisitionFaults:
    missing_every: int | None = None
    duplicate_every: int | None = None
    out_of_range_every: int | None = None
    invalid_every: int | None = None
    unit_error_every: int | None = None
    naive_timestamp_every: int | None = None


class SimulatedAcquisitionBackend:
    """Deterministic synthetic backend; it never mutates the clock or twin."""

    def __init__(self, clock: SimulationClock, faults: AcquisitionFaults = AcquisitionFaults()) -> None:
        self.clock = clock
        self.faults = faults

    def acquire(self, start: datetime, end: datetime, *, interval_seconds: float, specifications: Iterable[InstrumentationSpecification], seed: int = 0) -> tuple[AcquisitionRecord, ...]:
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise AcquisitionError("acquisition window must be ordered and timezone-aware")
        if interval_seconds <= 0 or not math.isfinite(interval_seconds):
            raise AcquisitionError("interval_seconds must be positive and finite")
        specs = tuple(sorted(specifications, key=lambda item: (item.plot_id or "", item.cycle_id or "", item.variable, item.instrument_id)))
        if any(spec.clock_source != "SimulationClock" for spec in specs):
            raise AcquisitionError("simulated acquisition requires SimulationClock")
        random_source = random.Random(seed)
        records: list[AcquisitionRecord] = []
        current = start.astimezone(timezone.utc)
        index = 0
        while current <= end:
            for spec in specs:
                index += 1
                value = self._value(spec.variable, current, random_source)
                quality = QualityFlag.VALID
                unit = spec.unit or "UNKNOWN"
                timestamp = current
                if self.faults.missing_every and index % self.faults.missing_every == 0:
                    value, quality = None, QualityFlag.MISSING
                if self.faults.out_of_range_every and index % self.faults.out_of_range_every == 0:
                    value, quality = -1.0, QualityFlag.OUT_OF_RANGE
                if self.faults.invalid_every and index % self.faults.invalid_every == 0:
                    value, quality = "not-a-number", QualityFlag.INVALID
                if self.faults.unit_error_every and index % self.faults.unit_error_every == 0:
                    unit, quality = "UNKNOWN_UNIT", QualityFlag.UNIT_ERROR
                if self.faults.naive_timestamp_every and index % self.faults.naive_timestamp_every == 0:
                    timestamp = timestamp.replace(tzinfo=None)
                record = AcquisitionRecord(f"acq-{seed}-{index:06d}", spec.instrument_id, spec.device_id, timestamp, spec.timezone, spec.clock_source, spec.variable, value, unit, spec.plot_id, spec.cycle_id, spec.crop, spec.variety, spec.environment, spec.phenological_stage, quality, f"synthetic:{spec.instrument_id}", simulation_seed=seed, configuration=f"interval_seconds={interval_seconds}")
                records.append(record)
                if self.faults.duplicate_every and index % self.faults.duplicate_every == 0:
                    records.append(record)
            current += timedelta(seconds=interval_seconds)
        return tuple(records)

    @staticmethod
    def _value(variable: str, timestamp: datetime, random_source: random.Random) -> float | str:
        hour = timestamp.hour + timestamp.minute / 60
        daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.0
        values = {"air_temperature": 20 + 5 * math.sin(2 * math.pi * (hour - 8) / 24), "relative_humidity": 70 - 20 * daylight, "solar_radiation": 800 * daylight, "vpd": 1.0 + daylight, "co2": 420.0, "wind_speed": 1.5, "precipitation": 0.0, "soil_water_content": 0.25, "lai": 1.0 + 0.1 * daylight, "biomass": 100.0, "yield": 1.0, "fruit_weight": 50.0, "fruit_count": 10.0}
        return round(values.get(variable, random_source.random()), 6)


__all__ = ["AcquisitionBackend", "AcquisitionError", "AcquisitionFaults", "AcquisitionRecord", "AcquisitionSourceType", "InstrumentationSpecification", "SimulatedAcquisitionBackend"]
