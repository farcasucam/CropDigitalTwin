"""Climate control for interactive simulations: request parsing, crop thresholds from the catalogue, and the per-step bridge to the orchestrator.

The controller (``domain.climate_control``) is stateless. ``ControlSession`` only builds its observation from the orchestrator state at the START
of each step, asks the controller for commands, lets manual events override them, and hands the result to the orchestrator as ordinary actuator
commands. Nothing here writes a physical state.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from agri_twin.domain.climate_control import (
    ACTUATORS,
    ActuatorMode,
    ClimateControlConfig,
    ClimateControlError,
    ClimateController,
    ControlDecision,
    ControlDesign,
    ControlObservation,
    ControlRecord,
    RuleBasedClimateController,
    StageSetpoints,
    commands_from_decision,
)
from agri_twin.domain.greenhouse import AIR_DENSITY_KG_M3, AIR_SPECIFIC_HEAT_J_KG_K, ActuatorControl
from agri_twin.domain.water_balance import IrrigationRequest

SRC = Path(__file__).resolve().parents[2]
CROP_CATALOGUE = SRC / "crop_config.json"
DESIGN_FILE = SRC / "climate_control_config.json"
MANUAL_TO_ACTUATORS = {"shade": ("shade",), "ventilation": ("vents", "extractors"), "heating": ("heating",), "cooling": ("cooling",)}


class ClimateControlRequestError(ValueError):
    """A control block that cannot be honoured; carries the field path for the API error."""

    def __init__(self, message: str, path: str = "control", kind: str = "INVALID_CONFIGURATION") -> None:
        super().__init__(message)
        self.message, self.path, self.kind = message, path, kind


@lru_cache(maxsize=1)
def load_design() -> ControlDesign:
    try:
        return ControlDesign.from_mapping(json.loads(DESIGN_FILE.read_text(encoding="utf-8")).get("design"))
    except (OSError, ValueError) as exc:
        raise ClimateControlError(f"climate_control_config.json is unreadable: {exc}") from exc


@lru_cache(maxsize=1)
def _catalogue() -> Mapping[str, Any]:
    return json.loads(CROP_CATALOGUE.read_text(encoding="utf-8")).get("crops", {})


def stage_setpoints(crop: str, stage: str) -> StageSetpoints:
    """Thresholds of ``stage`` from the crop catalogue; every undefined value stays ``None`` (no default is invented)."""
    return StageSetpoints.from_stage_config(crop, stage, ((_catalogue().get(crop) or {}).get("stages") or {}).get(stage))


def parse_control(document: Any, environment: str, backend: str = "SIMPLIFIED") -> ClimateControlConfig | None:
    """``None`` (no control block, or every actuator OFF) leaves requests, hashes and checkpoints exactly as before."""
    if document is None:
        return None
    try:
        config = ClimateControlConfig.from_mapping(document, load_design())
    except ClimateControlError as exc:
        raise ClimateControlRequestError(str(exc)) from None
    if not config.any_active:
        return None
    if backend != "SIMPLIFIED":
        raise ClimateControlRequestError("climate control needs the simplified greenhouse backend: EnergyPlus runs as a precomputed timeline and cannot react to the controller", "control", "INVALID_CONFIGURATION")
    if environment != "greenhouse":
        climate = [name for name in ACTUATORS if name != "irrigation" and config.mode(name) is not ActuatorMode.OFF]
        if climate:
            raise ClimateControlRequestError(f"{', '.join(climate)} need the greenhouse environment; open-field runs can only control irrigation", f"control.actuators.{climate[0]}", "UNSUPPORTED_ENVIRONMENT")
    return config


def describe(config: ClimateControlConfig) -> dict[str, Any]:
    """Effective-configuration block (hashed with the rest of the effective configuration)."""
    return {**config.to_dict(), "controller": RuleBasedClimateController.name, "design_evidence_status": "DESIGN_CONVENTION_NOT_VALIDATED",
            "thresholds": "per stage from crop_config.json; undefined thresholds disable the rule that needs them",
            "limits": ["stateless rules: the decision depends only on the state at the start of the step",
                       "energy is an estimate from user-defined efficiencies, not a measurement",
                       "equipment values are user-defined site inventory; none is validated",
                       "software qualification only; not validated against a real greenhouse"]}


class ControlSession:
    """Binds a control configuration (and any ``ClimateController``) to one run."""

    def __init__(self, config: ClimateControlConfig, crop: str, controller: ClimateController | None = None) -> None:
        self.config, self.crop = config, crop
        self.controller = controller or RuleBasedClimateController(config)

    def plan(self, orchestrator: Any, provider: Any, current: Any, dt_seconds: float, manual: Mapping[str, ActuatorControl]) -> tuple[dict[str, ActuatorControl], IrrigationRequest | None, ControlRecord]:
        observation = self.observe(orchestrator, provider, current)
        decision = self.controller.decide(observation)
        equipment = self.config.equipment
        overridden = tuple(sorted(name for name in manual if name in MANUAL_TO_ACTUATORS))
        decision = _without_overridden(decision, overridden)
        record = commands_from_decision(decision, equipment, dt_seconds, overridden)
        actuators = dict(manual)
        for name, requested in (("shade", record.shade_fraction), ("heating", record.heating_kw), ("cooling", record.cooling_kw)):
            if name not in actuators and (requested > 0 or self.config.mode(name) is not ActuatorMode.OFF):
                actuators[name] = _control(requested, 1.0)
        if "ventilation" not in actuators:
            actuators["ventilation"] = _control(record.vent_ach + record.extractor_ach, 1.0)
        irrigation = None
        if decision.irrigation_target_vwc is not None:
            irrigation = IrrigationRequest("vwc_target", target_vwc=decision.irrigation_target_vwc, maximum_mm=equipment.irrigation_max_mm_step)
        elif decision.irrigation_mm > 0:
            irrigation = IrrigationRequest("scheduled", amount_mm=decision.irrigation_mm, irrigation_type="drip")
        return actuators, irrigation, record

    def observe(self, orchestrator: Any, provider: Any, current: Any) -> ControlObservation:
        outdoor = provider.get(current)
        indoor = orchestrator.microclimate
        transmission, conductance, per_ach = 1.0, None, 0.0
        try:  # an engine without a profile: the screen rule sees the outdoor radiation and the HVAC rules fall back to a ramp
            profile = orchestrator.greenhouse.profile_for(orchestrator.greenhouse_mode)
            per_ach = AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_K * profile.volume_m3 / 3600.0
            transmission, conductance = profile.solar_transmission, profile.heat_loss_w_k + per_ach * profile.ventilation_ach
        except Exception:
            pass
        stage = orchestrator.crop.current_stage
        return ControlObservation(
            current.month, current.day, current.hour, stage, stage_setpoints(self.crop, stage),
            indoor.temperature_c if indoor is not None else outdoor.temperature_c,
            indoor.relative_humidity_pct if indoor is not None else outdoor.relative_humidity_pct,
            indoor.vpd_kpa if indoor is not None else 0.0,
            outdoor.temperature_c, outdoor.solar_radiation_w_m2, outdoor.solar_radiation_w_m2 * transmission,
            orchestrator.soil.vwc_m3_m3, conductance, per_ach,
            (indoor.heating_kw - indoor.cooling_kw) if indoor is not None else 0.0)


def _control(requested: float, floor: float) -> ActuatorControl:
    ceiling = max(floor, requested)
    return ActuatorControl(requested, maximum=ceiling, capacity=ceiling)


def _without_overridden(decision: ControlDecision, overridden: tuple[str, ...]) -> ControlDecision:
    """A manual event on an actuator replaces the controller for it: the controller's command (and its energy) is dropped."""
    if not overridden:
        return decision
    dropped = {actuator for name in overridden for actuator in MANUAL_TO_ACTUATORS[name]}
    values = {name: (0.0 if name in dropped else decision.level(name)) for name in ("shade", "vents", "extractors", "cooling", "heating")}
    source = {name: ("MANUAL" if name in dropped else value) for name, value in decision.source.items()}
    return ControlDecision(irrigation_mm=decision.irrigation_mm, irrigation_target_vwc=decision.irrigation_target_vwc, source=source, reasons=decision.reasons, **values)


ACTUATOR_INFO = (
    ("shade", "Shade screen", "PASSIVE", "fraction of the radiation blocked", "Deploys when the radiation reaching the crop exceeds the stage optimum, up to the stage's shading reduction."),
    ("vents", "Roof/side vents", "PASSIVE", "fraction open", "First line of cooling: opens as the greenhouse passes the stage's upper temperature, only while the outside air is cooler."),
    ("extractors", "Extractor fans", "ACTIVE", "fraction of full speed", "Second line: starts once the vents are fully open. Consumes electricity."),
    ("cooling", "HVAC cooling", "ACTIVE", "fraction of capacity", "Last resort: works only beyond what vents and extractors can do. Consumes energy."),
    ("heating", "HVAC heating", "ACTIVE", "fraction of capacity", "Holds the stage's minimum temperature. Consumes energy."),
    ("irrigation", "Irrigation", "PASSIVE", "mm per step (schedule) or refill to target (auto)", "Refills the root zone to the stage target when the soil water falls below the stage's optimal minimum."),
)
EQUIPMENT_INFO = (
    ("vent_max_ach", "Vents: air changes/h fully open", "1/h", "vents"), ("extractor_max_ach", "Extractors: air changes/h at full speed", "1/h", "extractors"),
    ("extractor_power_kw", "Extractors: electric power at full speed", "kW", "extractors"), ("cooling_capacity_kw", "HVAC cooling: thermal capacity", "kW", "cooling"),
    ("cooling_cop", "HVAC cooling: COP (thermal kW per electric kW)", "-", "cooling"), ("heating_capacity_kw", "HVAC heating: thermal capacity", "kW", "heating"),
    ("heating_efficiency", "HVAC heating: efficiency or COP", "-", "heating"), ("irrigation_max_mm_step", "Irrigation: maximum per step", "mm", "irrigation"),
)


def capabilities() -> dict[str, Any]:
    """What the interface may offer: actuators, the equipment the user must define, and the per-stage thresholds the rules will really use."""
    thresholds = {crop: {stage: stage_setpoints(crop, stage).to_dict() for stage in (config.get("stages") or {})} for crop, config in sorted(_catalogue().items())}
    return {
        "controller": RuleBasedClimateController.name,
        "actuators": [{"id": i, "label": label, "layer": layer, "unit": unit, "rule": rule} for i, label, layer, unit, rule in ACTUATOR_INFO],
        "equipment": [{"id": i, "label": label, "unit": unit, "actuator": actuator} for i, label, unit, actuator in EQUIPMENT_INFO],
        "modes": ["OFF", "AUTO", "SCHEDULE"], "design": load_design().to_dict(),
        "design_status": "DESIGN_CONVENTION_NOT_VALIDATED: algorithm parameters, not agronomic values",
        "stage_thresholds": thresholds, "threshold_source": "src/crop_config.json (per crop and stage); a missing value disables the rule that needs it",
        "equipment_status": "USER_DEFINED site inventory: nothing is assumed; an actuator without its equipment is unavailable",
        "schedule_fields": ["actuator", "from_day", "to_day", "start_hour", "end_hour", "value"],
        "extension_point": "agri_twin.domain.climate_control.ClimateController: any object with decide(ControlObservation) -> ControlDecision (for example a trained predictor) replaces the rules",
    }
