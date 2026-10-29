"""Runtime climate-event contract (Phase 5.39).

A runtime event is a user-defined, *future* intervention expressed in simulation time.
It is translated one-to-one into an existing ``ScenarioEvent`` (the overlay already
applied by ``ScenarioRunner``); this module adds no equation, weather generator or
event engine. Only event types the backend already executes are exposed; the others
are listed as ``NOT_SUPPORTED`` with the reason, and nothing is fabricated.

Every event is classified ``USER_DEFINED_EVENT`` / ``USER_DEFINED_SYNTHETIC_FORCING``
and is never observed agricultural data. The module reads no clock.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from agri_twin.application.scenarios import HALF_OPEN_INTERVAL, HOLD_DEW_POINT, ScenarioEvent

UTC = timezone.utc
SOURCE_USER_EVENT = "USER_DEFINED_EVENT"
FORCING_CLASSIFICATION = "USER_DEFINED_SYNTHETIC_FORCING"
PROVENANCE_CLASSES = ("BASE_SCENARIO", "SYNTHETIC_FORCING", "MODEL_FORCING", SOURCE_USER_EVENT)
EVENT_FIELDS = ("event_id", "event_type", "start_simulation_time", "duration_hours", "intensity", "ramp_hours", "parameters", "source")
BOUND_NOTE = "TECHNICAL_INPUT_SANITY_BOUND (software input guard, not an agronomic or physical limit)"


class RuntimeEventError(ValueError):
    """Structured validation failure; ``kind`` maps to an existing 5.37 error code."""

    def __init__(self, kind: str, message: str, path: str) -> None:
        super().__init__(message)
        self.kind, self.message, self.path = kind, message, path


@dataclass(frozen=True, slots=True)
class EventSpec:
    api_type: str
    scenario_type: str
    primary_parameter: str | None
    unit: str
    scope: str  # ALL | GREENHOUSE
    minimum: float = 0.0
    maximum: float | None = None
    minimum_exclusive: bool = False
    maximum_exclusive: bool = False
    ramp_supported: bool = False
    affected_variables: tuple[str, ...] = ()
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"event_type": self.api_type, "support": "SUPPORTED", "scenario_event_type": self.scenario_type, "intensity_parameter": self.primary_parameter,
                "intensity_unit": self.unit, "environments": "outdoor, greenhouse" if self.scope == "ALL" else "greenhouse only",
                "minimum": self.minimum, "minimum_exclusive": self.minimum_exclusive, "maximum": self.maximum, "maximum_exclusive": self.maximum_exclusive,
                "bound_note": BOUND_NOTE, "ramp_supported": self.ramp_supported, "affected_variables": list(self.affected_variables), "summary": self.summary,
                "source": SOURCE_USER_EVENT, "classification": FORCING_CLASSIFICATION}


SPECS: tuple[EventSpec, ...] = (
    EventSpec("HEAT_WAVE", "heat_wave", "temperature_offset_c", "degC added to the air temperature", "ALL", 0.0, 50.0, True, False, True,
              ("temperature_c", "vpd_kpa", "heat_stress"), "adds a temperature offset to the weather forcing"),
    EventSpec("COLD_WAVE", "cold_wave", "temperature_offset_c", "degC subtracted from the air temperature", "ALL", 0.0, 50.0, True, False, True,
              ("temperature_c", "vpd_kpa", "cold_stress", "frost_damage"), "subtracts a temperature offset from the weather forcing"),
    EventSpec("DRYNESS", "dry", None, "not used", "ALL", 0.0, 0.0, False, False, False,
              ("precipitation_mm", "soil_water_vwc_m3_m3", "water_stress"), "sets the rain rate of the weather forcing to zero for the interval"),
    EventSpec("RAIN", "wet", "rain_rate_mm_h", "mm h-1 replacing the forcing rain rate", "ALL", 0.0, 200.0, True, False, True,
              ("precipitation_mm", "soil_water_vwc_m3_m3", "water_stress"), "replaces the rain rate of the weather forcing (no rain reaches an indoor crop)"),
    EventSpec("HIGH_RADIATION", "high_radiation", "radiation_multiplier", "multiplier of the forcing solar radiation (> 1)", "ALL", 1.0, 5.0, True, False, True,
              ("radiation_w_m2", "radiation_stress", "temperature_c"), "scales the solar radiation of the weather forcing"),
    EventSpec("LOW_RADIATION", "low_radiation", "radiation_multiplier", "multiplier of the forcing solar radiation (< 1)", "ALL", 0.0, 1.0, False, True, True,
              ("radiation_w_m2", "radiation_stress", "temperature_c"), "scales the solar radiation of the weather forcing"),
    EventSpec("WIND", "wind", "speed_multiplier", "multiplier of the forcing wind speed", "ALL", 0.0, 10.0, False, False, True,
              ("temperature_c",), "scales the wind speed of the weather forcing; only the EnergyPlus backend uses wind (its convection and infiltration): the outdoor and simplified models change only when model_options.et0_method is PENMAN_MONTEITH_FAO56, where wind enters the evapotranspiration (audit finding 5)"),
    EventSpec("IRRIGATION", "irrigation", "amount_mm", "mm of irrigation applied in every step of the interval", "ALL", 0.0, 100.0, True, False, False,
              ("irrigation_mm", "soil_water_vwc_m3_m3", "water_stress"), "requests drip irrigation in each step of the interval"),
    EventSpec("FERTILIZATION", "fertilization", "amount_kg_ha", "kg ha-1 applied IN TOTAL over the interval, split evenly over its steps and ADDED to the available nutrient pool", "ALL", 0.0, 1000.0, True, False, False,
              ("nutrient_available_kg_ha", "nutrient_applied_kg_ha", "nutrient_status", "growth_factor"),
              "adds the stated total dose to the available nutrient pool over the interval (it never replaces a plan, events add up); the pool is capped at the reserve, so a dose that does not fit is discarded; efficiency 1 and no leaching are assumed (uncalibrated reduced model)"),
    EventSpec("VENTILATION", "ventilation", "value", "greenhouse ventilation actuator command (fraction of its maximum)", "GREENHOUSE", 0.0, 1.0, False, False, False,
              ("greenhouse_ventilation_fraction", "temperature_c", "relative_humidity_pct", "co2_ppm"), "commands the existing greenhouse ventilation actuator"),
    EventSpec("SHADING", "shade", "value", "greenhouse shading actuator command (fraction of its maximum)", "GREENHOUSE", 0.0, 1.0, False, False, False,
              ("greenhouse_shading_fraction", "radiation_w_m2", "temperature_c"), "commands the existing greenhouse shading actuator"),
    EventSpec("CO2", "co2", "value", "greenhouse CO2 actuator command (fraction of its maximum)", "GREENHOUSE", 0.0, 1.0, False, False, False,
              ("co2_ppm",), "commands the existing greenhouse CO2 actuator; the crop's growth response is min(1, CO2/420), so enrichment above 420 ppm does not raise growth by default; model_options.co2_response LOG_RELATIVE_GAIN lets it (audit finding 6)"),
)
SPEC_INDEX = {spec.api_type: spec for spec in SPECS}
NOT_SUPPORTED: Mapping[str, str] = {
    "WATER_STRESS": "water stress is an output of the model, not a forcing: the backend defines no injectable event for it. Use DRYNESS (no rain) to leave water to the model.",
}


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    event_id: str
    event_type: str
    start: datetime
    duration_hours: float
    intensity: float
    ramp_hours: float = 0.0
    source: str = SOURCE_USER_EVENT

    @property
    def spec(self) -> EventSpec:
        return SPEC_INDEX[self.event_type]

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=self.duration_hours)

    def to_dict(self) -> dict[str, Any]:
        spec = self.spec
        parameters = {spec.primary_parameter: self.intensity} if spec.primary_parameter else {}
        return {"event_id": self.event_id, "event_type": self.event_type, "start_simulation_time": self.start.isoformat(), "duration_hours": self.duration_hours,
                "end_simulation_time": self.end.isoformat(), "intensity": self.intensity, "ramp_hours": self.ramp_hours, "parameters": parameters, "source": self.source}

    def request_dict(self) -> dict[str, Any]:
        """Canonical, re-submittable form (round-trips through ``parse_runtime_events``)."""
        data = self.to_dict()
        del data["end_simulation_time"]
        return data

    def to_scenario_event(self) -> ScenarioEvent:
        spec = self.spec
        parameters: dict[str, float] = {spec.primary_parameter: self.intensity} if spec.primary_parameter else {}
        parameters[HALF_OPEN_INTERVAL] = 1.0  # N hours act on N steps (audit finding 10)
        if spec.api_type in {"HEAT_WAVE", "COLD_WAVE"}:
            parameters[HOLD_DEW_POINT] = 1.0  # the air keeps its vapour pressure when its temperature changes (audit finding 4)
        if self.ramp_hours > 0.0:
            parameters["ramp_hours"] = self.ramp_hours
        return ScenarioEvent(self.event_id, spec.scenario_type, self.start, self.end, self.intensity, parameters)


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RuntimeEventError("INVALID_REQUEST", f"{path} must be a finite number, got {value!r}", path)
    return float(value)


def _parse_one(raw: Any, index: int, *, environment: str, earliest: datetime, latest: datetime) -> RuntimeEvent:
    base = f"runtime_events[{index}]"
    if not isinstance(raw, Mapping):
        raise RuntimeEventError("INVALID_REQUEST", f"{base} must be a mapping, got {type(raw).__name__}", base)
    unknown = sorted(set(raw) - set(EVENT_FIELDS))
    if unknown:
        raise RuntimeEventError("INVALID_REQUEST", f"unknown fields: {', '.join(unknown)}; allowed: {', '.join(EVENT_FIELDS)}", f"{base}.{unknown[0]}")
    event_type = raw.get("event_type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise RuntimeEventError("INVALID_REQUEST", "event_type is required", f"{base}.event_type")
    event_type = event_type.strip().upper()
    if event_type in NOT_SUPPORTED:
        raise RuntimeEventError("INVALID_CONFIGURATION", f"event type {event_type} is NOT_SUPPORTED: {NOT_SUPPORTED[event_type]}", f"{base}.event_type")
    spec = SPEC_INDEX.get(event_type)
    if spec is None:
        raise RuntimeEventError("INVALID_CONFIGURATION", f"unknown event type {event_type!r}; supported: {', '.join(SPEC_INDEX)}", f"{base}.event_type")
    if spec.scope == "GREENHOUSE" and environment != "greenhouse":
        raise RuntimeEventError("UNSUPPORTED_ENVIRONMENT", f"{event_type} commands a greenhouse actuator and is NOT_APPLICABLE to outdoor runs", f"{base}.event_type")
    source = raw.get("source", SOURCE_USER_EVENT)
    if source != SOURCE_USER_EVENT:
        raise RuntimeEventError("INVALID_REQUEST", f"source must be {SOURCE_USER_EVENT!r}: runtime events are never observed or scenario data", f"{base}.source")
    event_id = raw.get("event_id", f"rt-{index + 1:03d}-{event_type.lower()}")
    if not isinstance(event_id, str) or not event_id.strip():
        raise RuntimeEventError("INVALID_REQUEST", "event_id must be a non-empty string", f"{base}.event_id")
    start_raw = raw.get("start_simulation_time")
    if not isinstance(start_raw, str):
        raise RuntimeEventError("INVALID_REQUEST", "start_simulation_time must be an ISO-8601 string with a UTC offset", f"{base}.start_simulation_time")
    try:
        start = datetime.fromisoformat(start_raw)
    except ValueError:
        raise RuntimeEventError("INVALID_REQUEST", f"start_simulation_time is not an ISO-8601 instant: {start_raw!r}", f"{base}.start_simulation_time") from None
    if start.tzinfo is None:
        raise RuntimeEventError("INVALID_REQUEST", "start_simulation_time needs an explicit UTC offset; browser or wall-clock time is never used", f"{base}.start_simulation_time")
    start = start.astimezone(UTC)
    if start < earliest:
        raise RuntimeEventError("INVALID_TIME_RANGE", f"event starts at {start.isoformat()}, before the current simulation time {earliest.isoformat()}: events may only affect the future, never simulated history", f"{base}.start_simulation_time")
    if (start - earliest).total_seconds() % 3600:
        raise RuntimeEventError("INVALID_TIME_RANGE", "start_simulation_time must lie on a whole simulation step (1 h) from the current simulation time", f"{base}.start_simulation_time")
    duration = _number(raw.get("duration_hours"), f"{base}.duration_hours") if "duration_hours" in raw else None
    if duration is None or duration <= 0 or duration % 1:
        raise RuntimeEventError("INVALID_TIME_RANGE", "duration_hours must be a positive whole number of hours", f"{base}.duration_hours")
    if start + timedelta(hours=duration) > latest:
        raise RuntimeEventError("INVALID_TIME_RANGE", f"event ends after the synthetic campaign end {latest.isoformat()}", f"{base}.duration_hours")
    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise RuntimeEventError("INVALID_REQUEST", "parameters must be a mapping", f"{base}.parameters")
    allowed = {spec.primary_parameter} if spec.primary_parameter else set()
    extra = sorted(set(parameters) - allowed)
    if extra:
        raise RuntimeEventError("INVALID_CONFIGURATION", f"parameter {extra[0]!r} is not supported by {event_type}; supported: {', '.join(sorted(allowed)) or 'none'}", f"{base}.parameters.{extra[0]}")
    given = [("intensity", raw["intensity"])] if "intensity" in raw else []
    if spec.primary_parameter in parameters:
        given.append((f"parameters.{spec.primary_parameter}", parameters[spec.primary_parameter]))
    if spec.primary_parameter is None:
        if given and _number(given[0][1], f"{base}.intensity") != 0.0:
            raise RuntimeEventError("INVALID_CONFIGURATION", f"{event_type} has no intensity parameter", f"{base}.intensity")
        intensity = 0.0
    else:
        if not given:
            raise RuntimeEventError("INVALID_REQUEST", f"intensity ({spec.primary_parameter}) is required for {event_type}", f"{base}.intensity")
        values = {_number(value, f"{base}.{name}") for name, value in given}
        if len(values) > 1:
            raise RuntimeEventError("INVALID_REQUEST", f"intensity and parameters.{spec.primary_parameter} disagree", f"{base}.intensity")
        intensity = values.pop()
        low = intensity <= spec.minimum if spec.minimum_exclusive else intensity < spec.minimum
        high = spec.maximum is not None and (intensity >= spec.maximum if spec.maximum_exclusive else intensity > spec.maximum)
        if low or high:
            lower = f"{'>' if spec.minimum_exclusive else '>='} {spec.minimum:g}"
            upper = f", {'<' if spec.maximum_exclusive else '<='} {spec.maximum:g}" if spec.maximum is not None else ""
            raise RuntimeEventError("INVALID_CONFIGURATION", f"intensity {intensity:g} is outside the accepted range ({lower}{upper}) for {event_type} [{BOUND_NOTE}]", f"{base}.intensity")
    ramp = _number(raw.get("ramp_hours", 0.0), f"{base}.ramp_hours")
    if ramp < 0:
        raise RuntimeEventError("INVALID_CONFIGURATION", "ramp_hours cannot be negative", f"{base}.ramp_hours")
    if ramp > 0 and not spec.ramp_supported:
        raise RuntimeEventError("INVALID_CONFIGURATION", f"{event_type} does not support ramp_hours in the existing backend event model", f"{base}.ramp_hours")
    return RuntimeEvent(event_id.strip(), event_type, start, duration, intensity, ramp)


def parse_runtime_events(raw: Any, *, environment: str, earliest: datetime, latest: datetime, reserved_ids: Sequence[str] = ()) -> tuple[RuntimeEvent, ...]:
    """Validate a runtime event sequence against the execution it will be attached to.

    ``earliest`` is the current simulation time (the run start or the checkpoint time):
    no event may start before it, so simulated history is never altered.
    """
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise RuntimeEventError("INVALID_REQUEST", f"runtime_events must be a list, got {type(raw).__name__}", "runtime_events")
    events = tuple(_parse_one(item, index, environment=environment, earliest=earliest, latest=latest) for index, item in enumerate(raw))
    identifiers = [event.event_id for event in events]
    for index, identifier in enumerate(identifiers):
        if identifiers.count(identifier) > 1 or identifier in reserved_ids:
            raise RuntimeEventError("INVALID_REQUEST", f"event_id {identifier!r} is not unique", f"runtime_events[{index}].event_id")
    return events


def event_sequence_hash(events: Sequence[RuntimeEvent]) -> str:
    payload = json.dumps([event.request_dict() for event in events], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def event_contract() -> dict[str, Any]:
    """Machine-readable runtime event contract (what a frontend may offer)."""
    return {
        "version": "5.39.0", "source": SOURCE_USER_EVENT, "classification": FORCING_CLASSIFICATION, "provenance_classes": list(PROVENANCE_CLASSES),
        "event_fields": list(EVENT_FIELDS), "time_basis": "simulation time only (ISO-8601 with UTC offset); no wall-clock input",
        "supported": [spec.to_dict() for spec in SPECS],
        "not_supported": [{"event_type": name, "support": "NOT_SUPPORTED", "reason": reason} for name, reason in NOT_SUPPORTED.items()],
        "rules": ["an event may only start at or after the current simulation time (the checkpoint time)", "events never modify the simulated history",
                  "the backend executes every event; consequences are never predicted or calculated by the interface",
                  "an intervention is a new branch resumed from a checkpoint; the baseline branch is preserved unchanged"],
        "statement": "Runtime climate events are USER-DEFINED SYNTHETIC FORCING and are never observed agricultural data.",
    }
