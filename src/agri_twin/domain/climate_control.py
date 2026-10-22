"""Greenhouse climate control: passive-first strategies, schedules and an estimate of the energy they spend.

Causal chain kept: observation -> controller -> command (``ControlDecision``) -> actuator -> physical model. A controller never writes a
temperature, humidity or water content; it only returns actuator commands for the next step.

Controllers are STATELESS functions of the observation. That is what makes a run reproducible, lets a what-if branch resume from a checkpoint with
exactly the same behaviour, and lets any other decision source plug in later (``ClimateController`` is the single extension point, e.g. a model that
predicts the next hours from ``ControlObservation.forecast``).

Where each number comes from:
* crop thresholds (temperature range, critical heat/frost, radiation, soil water, shading reduction) come from the crop catalogue JSON per stage
  (``StageSetpoints``); a missing value means "no threshold": the rule that needs it does not act and says so;
* the tier fractions (``ControlDesign``) are algorithm design conventions, NOT agronomic values (see ``src/climate_control_config.json``);
* equipment (capacity, COP, fan power) is site inventory supplied by the user (``EquipmentSpec``); an unset item makes that actuator unavailable;
* energy is an estimate from user-defined efficiencies, never a measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol, Sequence


class ClimateControlError(ValueError):
    """Invalid control configuration."""


class ControlLayer(StrEnum):
    PASSIVE = "PASSIVE"  # screens and natural ventilation: no energy
    ACTIVE = "ACTIVE"    # extractors and HVAC: spend energy
    NONE = "NONE"


class ActuatorMode(StrEnum):
    OFF = "OFF"
    AUTO = "AUTO"
    SCHEDULE = "SCHEDULE"


# the actuators a strategy can drive; each one has its own mode
ACTUATORS = ("shade", "vents", "extractors", "cooling", "heating", "irrigation")
PASSIVE_ACTUATORS = ("shade", "vents")


def _number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None, allow_none: bool = True) -> float | None:
    if value is None:
        if allow_none:
            return None
        raise ClimateControlError(f"{name} is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ClimateControlError(f"{name} must be a finite number")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ClimateControlError(f"{name} must be within [{minimum}, {maximum}]")
    return float(value)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


# ---------------------------------------------------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StageSetpoints:
    """Crop thresholds of one phenological stage, read from the crop catalogue JSON. ``None`` = the catalogue does not define it."""

    crop: str
    stage: str
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    critical_heat_c: float | None = None
    critical_frost_c: float | None = None
    optimal_max_w_m2: float | None = None
    photoinhibition_w_m2: float | None = None
    shading_reduction_pct: float | None = None
    vwc_optimal_min: float | None = None
    target_vwc_after_irrigation: float | None = None

    @classmethod
    def from_stage_config(cls, crop: str, stage: str, config: Mapping[str, Any] | None) -> "StageSetpoints":
        config = config or {}
        stress, radiation = config.get("stress_thresholds") or {}, config.get("solar_radiation_thresholds") or {}
        irrigation, water = config.get("irrigation") or {}, config.get("vwc_thresholds") or {}
        pick = lambda block, key: (float(block[key]) if isinstance(block.get(key), (int, float)) and not isinstance(block.get(key), bool) else None)  # noqa: E731
        return cls(crop, stage, pick(stress, "min_temp_c"), pick(stress, "max_temp_c"), pick(stress, "critical_heat_c"), pick(stress, "critical_frost_c"),
                   pick(radiation, "optimal_max_w_m2"), pick(radiation, "photoinhibition_w_m2"), pick(irrigation, "shading_reduction_pct"),
                   pick(water, "optimal_min"), pick(irrigation, "target_vwc_after_irrigation"))

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class EquipmentSpec:
    """Site inventory, user-defined. Anything left ``None`` makes the dependent actuator unavailable (never a silent default)."""

    vent_max_ach: float | None = None          # extra air changes per hour with the roof/side vents fully open
    extractor_max_ach: float | None = None     # extra air changes per hour with the extractors at full speed
    extractor_power_kw: float | None = None    # electric power of the extractors at full speed
    cooling_capacity_kw: float | None = None   # thermal power removed at full output
    cooling_cop: float | None = None           # thermal kW removed per electric kW
    heating_capacity_kw: float | None = None   # thermal power delivered at full output
    heating_efficiency: float | None = None    # thermal kW per input kW (boiler efficiency or heat-pump COP)
    irrigation_max_mm_step: float | None = None

    FIELDS = ("vent_max_ach", "extractor_max_ach", "extractor_power_kw", "cooling_capacity_kw", "cooling_cop", "heating_capacity_kw", "heating_efficiency", "irrigation_max_mm_step")

    @classmethod
    def from_mapping(cls, document: Mapping[str, Any] | None) -> "EquipmentSpec":
        document = dict(document or {})
        unknown = sorted(set(document) - set(cls.FIELDS))
        if unknown:
            raise ClimateControlError(f"unknown equipment fields: {', '.join(unknown)}; allowed: {', '.join(cls.FIELDS)}")
        values = {name: _number(document.get(name), f"equipment.{name}", minimum=0.0) for name in cls.FIELDS}
        for name in ("cooling_cop", "heating_efficiency"):
            if values[name] is not None and values[name] <= 0:
                raise ClimateControlError(f"equipment.{name} must be positive")
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.FIELDS}

    def available(self, actuator: str) -> bool:
        return {"shade": True, "irrigation": True, "vents": bool(self.vent_max_ach), "extractors": bool(self.extractor_max_ach),
                "cooling": bool(self.cooling_capacity_kw), "heating": bool(self.heating_capacity_kw)}[actuator]


@dataclass(frozen=True, slots=True)
class ControlDesign:
    """Algorithm design conventions (provisional, not agronomic): where each tier reaches full output inside the hot band.

    The hot band runs from the stage's ``max_temp_c`` (demand 0) to its ``critical_heat_c`` (demand 1). Passive vents ramp over [0, vents_full_at],
    extractors over [vents_full_at, extractors_full_at]; HVAC cooling starts where the last available tier ends, so active equipment only works once the passive tier is exhausted.

    HVAC power compensates the disturbance: the controller estimates the temperature the greenhouse would settle at WITHOUT HVAC (today's temperature minus the effect of
    the HVAC power applied in the previous step, over the conductance in W K-1) and commands the power that would close ``hvac_gain`` of the distance to the target. Because the
    estimate removes the previous HVAC action, the loop does not feed its own output back and stays stable and free of oscillation (a plain proportional loop on the measured
    temperature alternates in sign when it runs once per simulated step). The gain stays below 1 to leave room for the estimate's error.
    """

    vents_full_at: float = 0.3
    extractors_full_at: float = 0.6
    hvac_gain: float = 0.9
    vents_start_margin_c: float = 0.0  # the hot band starts this many degrees BELOW the stage's max_temp_c: a real greenhouse opens before the crop's limit

    def __post_init__(self) -> None:
        if not 0.0 < self.vents_full_at <= self.extractors_full_at < 1.0:
            raise ClimateControlError("design fractions must satisfy 0 < vents_full_at <= extractors_full_at < 1")
        if not 0.0 < self.hvac_gain <= 1.0:
            raise ClimateControlError("hvac_gain must be in (0, 1]")
        if not 0.0 <= self.vents_start_margin_c <= 15.0:
            raise ClimateControlError("vents_start_margin_c must be within [0, 15] degC")

    @classmethod
    def from_mapping(cls, document: Mapping[str, Any] | None) -> "ControlDesign":
        document = dict(document or {})
        known = {"vents_full_at", "extractors_full_at", "hvac_gain", "vents_start_margin_c"}
        unknown = sorted(set(document) - known - {"source", "note", "evidence_status", "meaning"})
        if unknown:
            raise ClimateControlError(f"unknown design fields: {', '.join(unknown)}")
        return cls(**{name: float(document[name]) for name in known if name in document})

    def to_dict(self) -> dict[str, Any]:
        return {"vents_full_at": self.vents_full_at, "extractors_full_at": self.extractors_full_at, "hvac_gain": self.hvac_gain, "vents_start_margin_c": self.vents_start_margin_c}


@dataclass(frozen=True, slots=True)
class ScheduleProgram:
    """A recurring daily window: ``actuator`` is driven to ``value`` between ``start_hour`` and ``end_hour`` on every day from ``from_day`` to ``to_day``.

    Days are ``MM-DD`` (the range may wrap the year end, e.g. 11-01 to 02-28); hours are UTC, ``start_hour`` inclusive, ``end_hour`` exclusive (may wrap midnight).
    ``value`` is a fraction of the actuator's capacity in [0, 1] (for irrigation: mm per step).
    """

    actuator: str
    from_day: str
    to_day: str
    start_hour: int
    end_hour: int
    value: float

    def __post_init__(self) -> None:
        if self.actuator not in ACTUATORS:
            raise ClimateControlError(f"schedule actuator must be one of {', '.join(ACTUATORS)}")
        for name, text in (("from_day", self.from_day), ("to_day", self.to_day)):
            _month_day(text, f"schedule.{name}")
        if not (isinstance(self.start_hour, int) and isinstance(self.end_hour, int) and 0 <= self.start_hour <= 23 and 0 <= self.end_hour <= 24 and self.start_hour != self.end_hour):
            raise ClimateControlError("schedule hours must be integers: start_hour 0-23, end_hour 0-24, and different")
        if not math.isfinite(self.value) or self.value < 0 or (self.actuator != "irrigation" and self.value > 1):
            raise ClimateControlError("schedule value must be in [0, 1] (irrigation: mm per step >= 0)")

    @classmethod
    def from_mapping(cls, document: Mapping[str, Any]) -> "ScheduleProgram":
        if not isinstance(document, Mapping):
            raise ClimateControlError("a schedule entry must be a mapping")
        known = ("actuator", "from_day", "to_day", "start_hour", "end_hour", "value")
        unknown = sorted(set(document) - set(known))
        if unknown:
            raise ClimateControlError(f"unknown schedule fields: {', '.join(unknown)}; allowed: {', '.join(known)}")
        missing = [name for name in known if name not in document]
        if missing:
            raise ClimateControlError(f"schedule is missing: {', '.join(missing)}")
        value = _number(document["value"], "schedule.value", allow_none=False)
        return cls(str(document["actuator"]), str(document["from_day"]), str(document["to_day"]), _hour(document["start_hour"], "start_hour"), _hour(document["end_hour"], "end_hour"), value)

    def to_dict(self) -> dict[str, Any]:
        return {"actuator": self.actuator, "from_day": self.from_day, "to_day": self.to_day, "start_hour": self.start_hour, "end_hour": self.end_hour, "value": self.value}

    def active(self, month: int, day: int, hour: int) -> bool:
        start, end, today = _month_day(self.from_day, "from_day"), _month_day(self.to_day, "to_day"), (month, day)
        in_days = start <= today <= end if start <= end else today >= start or today <= end
        in_hours = self.start_hour <= hour < self.end_hour if self.start_hour < self.end_hour else hour >= self.start_hour or hour < self.end_hour
        return in_days and in_hours


def _hour(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClimateControlError(f"schedule.{name} must be an integer hour")
    return value


def _month_day(text: str, name: str) -> tuple[int, int]:
    try:
        month, day = (int(part) for part in text.split("-"))
    except (ValueError, AttributeError):
        raise ClimateControlError(f"{name} must be MM-DD") from None
    if not (1 <= month <= 12 and 1 <= day <= (29 if month == 2 else 30 if month in (4, 6, 9, 11) else 31)):
        raise ClimateControlError(f"{name} {text!r} is not a valid day")
    return month, day


@dataclass(frozen=True, slots=True)
class ControlObservation:
    """What a controller may look at: the state at the START of the step. Never the result of the step it is deciding."""

    month: int
    day: int
    hour: int
    stage: str
    setpoints: StageSetpoints
    indoor_temp_c: float
    indoor_rh_pct: float
    indoor_vpd_kpa: float
    outdoor_temp_c: float
    outdoor_radiation_w_m2: float
    crop_radiation_unshaded_w_m2: float  # radiation the crop would get with the screen open
    soil_vwc: float | None
    conductance_w_k: float | None = None            # cover heat loss plus the base air exchange (W K-1); None: HVAC falls back to a ramp over the crop's critical band
    air_conductance_per_ach_w_k: float = 0.0       # extra conductance per additional air change per hour (W K-1)
    previous_hvac_net_kw: float = 0.0              # heating minus cooling thermal power applied in the previous step (kW)
    predict: Callable[[float, float, float], float] | None = field(default=None, compare=False, repr=False)  # (extra air changes/h, net HVAC kW (+heating), shade fraction) -> air temperature at the END of this step, from the greenhouse model itself
    forecast: tuple[tuple[float, float], ...] = ()  # (outdoor temperature degC, outdoor radiation W m-2) for the next hours; unused by the rules, there for predictive controllers


@dataclass(frozen=True, slots=True)
class ControlDecision:
    """Normalised commands for the next step. Fractions are of the equipment capacity."""

    shade: float = 0.0
    vents: float = 0.0
    extractors: float = 0.0
    cooling: float = 0.0
    heating: float = 0.0
    irrigation_mm: float = 0.0
    irrigation_target_vwc: float | None = None
    source: dict[str, str] = field(default_factory=dict)   # actuator -> RULES | SCHEDULE | OFF | UNAVAILABLE | NO_THRESHOLD
    reasons: tuple[str, ...] = ()

    def level(self, actuator: str) -> float:
        return self.irrigation_mm if actuator == "irrigation" else getattr(self, actuator)


class ClimateController(Protocol):
    """The extension point: anything that maps an observation to commands (rules today, a learned predictor tomorrow)."""

    name: str

    def decide(self, observation: ControlObservation) -> ControlDecision: ...


# ---------------------------------------------------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ClimateControlConfig:
    modes: tuple[tuple[str, ActuatorMode], ...]
    equipment: EquipmentSpec = EquipmentSpec()
    schedules: tuple[ScheduleProgram, ...] = ()
    design: ControlDesign = ControlDesign()

    def mode(self, actuator: str) -> ActuatorMode:
        return dict(self.modes).get(actuator, ActuatorMode.OFF)

    @property
    def any_active(self) -> bool:
        return any(mode is not ActuatorMode.OFF for _, mode in self.modes)

    def to_dict(self) -> dict[str, Any]:
        return {"actuators": {name: self.mode(name).value for name in ACTUATORS}, "equipment": self.equipment.to_dict(),
                "schedules": [program.to_dict() for program in self.schedules], "design": self.design.to_dict()}

    @classmethod
    def from_mapping(cls, document: Mapping[str, Any], design: ControlDesign | None = None) -> "ClimateControlConfig":
        if not isinstance(document, Mapping):
            raise ClimateControlError("control must be a mapping")
        unknown = sorted(set(document) - {"actuators", "equipment", "schedules"})
        if unknown:
            raise ClimateControlError(f"unknown control fields: {', '.join(unknown)}; allowed: actuators, equipment, schedules")
        raw = document.get("actuators") or {}
        if not isinstance(raw, Mapping):
            raise ClimateControlError("control.actuators must be a mapping")
        bad = sorted(set(raw) - set(ACTUATORS))
        if bad:
            raise ClimateControlError(f"unknown actuators: {', '.join(bad)}; allowed: {', '.join(ACTUATORS)}")
        modes = []
        for name in ACTUATORS:
            try:
                modes.append((name, ActuatorMode(str(raw.get(name, "OFF")).upper())))
            except ValueError:
                raise ClimateControlError(f"control.actuators.{name} must be one of {', '.join(m.value for m in ActuatorMode)}") from None
        schedules = document.get("schedules") or []
        if not isinstance(schedules, Sequence) or isinstance(schedules, (str, bytes)):
            raise ClimateControlError("control.schedules must be a list")
        return cls(tuple(modes), EquipmentSpec.from_mapping(document.get("equipment")), tuple(ScheduleProgram.from_mapping(item) for item in schedules), design or ControlDesign())


# ---------------------------------------------------------------------------------------------------------------------
# the rule-based controller
# ---------------------------------------------------------------------------------------------------------------------
class RuleBasedClimateController:
    """Passive-first rules over the crop thresholds of the current stage, plus daily schedules, per actuator mode."""

    name = "rules-passive-first"

    def __init__(self, config: ClimateControlConfig) -> None:
        self.config = config

    def decide(self, observation: ControlObservation) -> ControlDecision:
        cfg, sp, eq = self.config, observation.setpoints, self.config.equipment
        levels: dict[str, float] = {name: 0.0 for name in ACTUATORS}
        source: dict[str, str] = {}
        reasons: list[str] = []

        scheduled = {name: self._scheduled(name, observation) for name in ACTUATORS if cfg.mode(name) is ActuatorMode.SCHEDULE}
        auto = {name for name in ACTUATORS if cfg.mode(name) is ActuatorMode.AUTO}
        for name in ACTUATORS:
            mode = cfg.mode(name)
            if mode is ActuatorMode.OFF:
                source[name] = "OFF"
            elif not eq.available(name):
                source[name] = "UNAVAILABLE"
                reasons.append(f"{name}: equipment not defined (set it in the equipment list)")
            elif mode is ActuatorMode.SCHEDULE:
                levels[name] = scheduled[name]
                source[name] = "SCHEDULE"

        usable = {name for name in auto if eq.available(name)}
        # ---- screen: radiation above the crop's optimum, up to the stage's shading reduction (decided first: the cooling search below knows about it)
        if "shade" in auto:
            if sp.optimal_max_w_m2 is None or sp.photoinhibition_w_m2 is None or sp.shading_reduction_pct is None or sp.photoinhibition_w_m2 <= sp.optimal_max_w_m2:
                source["shade"] = "NO_THRESHOLD"
                reasons.append("the screen rule needs optimal_max_w_m2, photoinhibition_w_m2 and shading_reduction_pct for the stage")
            else:
                level = _clamp((observation.crop_radiation_unshaded_w_m2 - sp.optimal_max_w_m2) / (sp.photoinhibition_w_m2 - sp.optimal_max_w_m2))
                levels["shade"] = level * _clamp(sp.shading_reduction_pct / 100.0)
                source["shade"] = "RULES"
        shade = levels["shade"] if cfg.mode("shade") is not ActuatorMode.SCHEDULE else scheduled.get("shade", 0.0)
        # ---- cooling: passive first (vents), then extractors, then HVAC cooling
        hot_start = None if sp.max_temp_c is None else sp.max_temp_c - cfg.design.vents_start_margin_c
        cooling_names = [name for name in ("vents", "extractors", "cooling") if name in auto]
        if cooling_names and (hot_start is None or sp.critical_heat_c is None):
            for name in cooling_names:
                if name in usable:
                    source[name] = "NO_THRESHOLD"
            reasons.append("cooling rules need max_temp_c and critical_heat_c for the stage; the catalogue does not define them")
        elif cooling_names:
            outdoor_helps = observation.outdoor_temp_c < observation.indoor_temp_c  # vents and extractors only cool with cooler outside air
            if observation.predict is not None:
                self._cool_by_prediction(observation, hot_start, shade, usable, outdoor_helps, levels, reasons)
            else:
                self._cool_by_ramp(observation, hot_start, usable, outdoor_helps, levels, reasons)
            for name in cooling_names:
                source[name] = "RULES" if name in usable else source.get(name, "UNAVAILABLE")
        # ---- heating
        if "heating" in auto and "heating" in usable:
            if sp.min_temp_c is None:
                source["heating"] = "NO_THRESHOLD"
                reasons.append("the heating rule needs min_temp_c for the stage; the catalogue does not define it")
            elif observation.predict is not None:
                air = levels["vents"] * (eq.vent_max_ach or 0.0) + levels["extractors"] * (eq.extractor_max_ach or 0.0)
                if observation.predict(air, 0.0, shade) < sp.min_temp_c:
                    # the smallest heating power that brings the end of the step up to the minimum (the model is monotone in the power)
                    kw = self._solve(lambda power: observation.predict(air, power, shade), 0.0, eq.heating_capacity_kw or 0.0, sp.min_temp_c, rising=True)
                    levels["heating"] = _clamp(kw / eq.heating_capacity_kw)
                source["heating"] = "RULES"
            else:
                fallback = self._demand(observation.indoor_temp_c, sp.min_temp_c, sp.critical_frost_c, below=True)
                if fallback is None and observation.conductance_w_k is None:
                    source["heating"] = "NO_THRESHOLD"
                    reasons.append("without the greenhouse conductance the heating rule needs critical_frost_c for the stage")
                else:
                    levels["heating"] = self._hvac_level(observation, 0.0, sp.min_temp_c, True, eq.heating_capacity_kw, cfg.design.hvac_gain, fallback=fallback or 0.0)
                    source["heating"] = "RULES"
        # ---- irrigation: below the optimal soil water, refill to the stage's target
        target = None
        if "irrigation" in auto:
            if observation.soil_vwc is None or sp.vwc_optimal_min is None or sp.target_vwc_after_irrigation is None:
                source["irrigation"] = "NO_THRESHOLD"
                reasons.append("the irrigation rule needs vwc_thresholds.optimal_min and irrigation.target_vwc_after_irrigation for the stage")
            else:
                source["irrigation"] = "RULES"
                if observation.soil_vwc < sp.vwc_optimal_min:
                    target = sp.target_vwc_after_irrigation
        scheduled_irrigation = levels["irrigation"] if cfg.mode("irrigation") is ActuatorMode.SCHEDULE else 0.0
        return ControlDecision(shade=levels["shade"], vents=levels["vents"], extractors=levels["extractors"], cooling=levels["cooling"], heating=levels["heating"],
                               irrigation_mm=scheduled_irrigation, irrigation_target_vwc=target, source=source, reasons=tuple(reasons))

    @staticmethod
    def _solve(function: Callable[[float], float], low: float, high: float, target: float, *, rising: bool = False) -> float:
        """The smallest x in [low, high] whose value reaches ``target`` (``rising``: the function grows with x; else it falls). ``high`` if it never does. 14 halvings."""
        reached = (lambda value: value >= target) if rising else (lambda value: value <= target)
        if not reached(function(high)):
            return high
        for _ in range(14):
            middle = (low + high) / 2.0
            if reached(function(middle)):
                high = middle
            else:
                low = middle
        return high

    def _cool_by_prediction(self, observation: ControlObservation, ceiling: float, shade: float, usable: set[str], outdoor_helps: bool, levels: dict[str, float], reasons: list[str]) -> None:
        """Each tier takes only what the greenhouse model says is still needed to keep the END of the step at the ceiling: vents, then extractors, then HVAC cooling."""
        eq, predict = self.config.equipment, observation.predict
        assert predict is not None
        if predict(0.0, 0.0, shade) <= ceiling:
            return
        air = 0.0
        if not outdoor_helps and ("vents" in usable or "extractors" in usable):
            reasons.append("outside air is not cooler than the greenhouse: ventilation held back")
        for name, capacity in (("vents", eq.vent_max_ach), ("extractors", eq.extractor_max_ach)):
            if name in usable and outdoor_helps and capacity:
                start = air
                added = self._solve(lambda extra: predict(start + extra, 0.0, shade), 0.0, capacity, ceiling)
                levels[name] = _clamp(added / capacity)
                air = start + added
                if predict(air, 0.0, shade) <= ceiling:
                    return
        if "cooling" in usable and eq.cooling_capacity_kw:
            kw = self._solve(lambda power: predict(air, -power, shade), 0.0, eq.cooling_capacity_kw, ceiling)
            levels["cooling"] = _clamp(kw / eq.cooling_capacity_kw)

    def _cool_by_ramp(self, observation: ControlObservation, hot_start: float, usable: set[str], outdoor_helps: bool, levels: dict[str, float], reasons: list[str]) -> None:
        """Without a model of the greenhouse: ramps over the hot band, passive tiers first (the historical rule)."""
        cfg, sp, eq = self.config, observation.setpoints, self.config.equipment
        hot = self._demand(observation.indoor_temp_c, hot_start, sp.critical_heat_c)
        if hot is None:
            return
        previous = 0.0
        for name, end in (("vents", cfg.design.vents_full_at), ("extractors", cfg.design.extractors_full_at)):
            if name in usable and outdoor_helps:
                levels[name] = _clamp((hot - previous) / (end - previous))
                previous = end
        if "cooling" in usable:
            air_changes = levels["vents"] * (eq.vent_max_ach or 0.0) + levels["extractors"] * (eq.extractor_max_ach or 0.0)
            target = hot_start + previous * (sp.critical_heat_c - hot_start)
            levels["cooling"] = self._hvac_level(observation, air_changes, target, False, eq.cooling_capacity_kw, cfg.design.hvac_gain, fallback=_clamp((hot - previous) / (1.0 - previous)))
        if hot > 0 and not outdoor_helps and ("vents" in usable or "extractors" in usable):
            reasons.append("outside air is not cooler than the greenhouse: ventilation held back")

    @staticmethod
    def _hvac_level(observation: ControlObservation, extra_air_changes: float, target_c: float, heating: bool, capacity_kw: float | None, gain: float, fallback: float) -> float:
        """Fraction of the HVAC capacity that closes ``gain`` of the distance between the HVAC-free equilibrium and ``target_c``; a ramp over the critical band if the conductance is unknown."""
        if observation.conductance_w_k is None or not capacity_kw:
            return fallback
        free_equilibrium = observation.indoor_temp_c - observation.previous_hvac_net_kw * 1000.0 / observation.conductance_w_k
        conductance = observation.conductance_w_k + observation.air_conductance_per_ach_w_k * extra_air_changes
        distance = (target_c - free_equilibrium) if heating else (free_equilibrium - target_c)
        return _clamp(gain * conductance * max(0.0, distance) / 1000.0 / capacity_kw)

    def _scheduled(self, actuator: str, observation: ControlObservation) -> float:
        values = [program.value for program in self.config.schedules if program.actuator == actuator and program.active(observation.month, observation.day, observation.hour)]
        return max(values) if values else 0.0

    @staticmethod
    def _demand(value: float, start: float | None, end: float | None, below: bool = False) -> float | None:
        """0 at ``start`` (the edge of the comfortable range) rising to 1 at ``end`` (the critical value)."""
        if start is None or end is None or (end <= start if not below else end >= start):
            return None
        return _clamp((start - value) / (start - end)) if below else _clamp((value - start) / (end - start))


# ---------------------------------------------------------------------------------------------------------------------
# commands, energy
# ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ControlRecord:
    """What was commanded in one step and what it cost; attached to the step's snapshot so the trajectory can show it."""

    decision: ControlDecision
    shade_fraction: float
    vent_ach: float
    extractor_ach: float
    cooling_kw: float
    heating_kw: float
    irrigation_mm: float
    layer: str
    electric_kw: float | None
    energy_kwh: float | None
    manual_override: tuple[str, ...] = ()

    @property
    def vent_level(self) -> float:
        return self.decision.vents

    @property
    def extractor_level(self) -> float:
        return self.decision.extractors


def commands_from_decision(decision: ControlDecision, equipment: EquipmentSpec, dt_seconds: float, manual: Sequence[str] = ()) -> ControlRecord:
    """Translate fractions into physical commands and estimate the electric energy of the step.

    Heating/cooling are thermal powers (what the physical model receives); the electric/fuel input divides them by the user-defined efficiency.
    The energy is ``None`` (not estimable) as soon as an active actuator runs without the efficiency it needs; nothing is substituted.
    """
    vent_ach = decision.vents * (equipment.vent_max_ach or 0.0)
    extractor_ach = decision.extractors * (equipment.extractor_max_ach or 0.0)
    cooling_kw = decision.cooling * (equipment.cooling_capacity_kw or 0.0)
    heating_kw = decision.heating * (equipment.heating_capacity_kw or 0.0)
    parts: list[float | None] = []
    if decision.extractors > 0:
        parts.append(decision.extractors * equipment.extractor_power_kw if equipment.extractor_power_kw is not None else None)
    if cooling_kw > 0:
        parts.append(cooling_kw / equipment.cooling_cop if equipment.cooling_cop else None)
    if heating_kw > 0:
        parts.append(heating_kw / equipment.heating_efficiency if equipment.heating_efficiency else None)
    electric = None if any(part is None for part in parts) else float(sum(parts))
    active = decision.extractors > 0 or cooling_kw > 0 or heating_kw > 0
    passive = decision.shade > 0 or decision.vents > 0
    layer = ControlLayer.ACTIVE if active else ControlLayer.PASSIVE if passive else ControlLayer.NONE
    return ControlRecord(decision, decision.shade, vent_ach, extractor_ach, cooling_kw, heating_kw, decision.irrigation_mm, layer.value, electric,
                         None if electric is None else electric * dt_seconds / 3600.0, tuple(manual))
