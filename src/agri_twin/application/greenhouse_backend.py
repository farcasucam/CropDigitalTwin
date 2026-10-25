"""Greenhouse backend selection for interactive simulations (SIMPLIFIED default, optional ENERGYPLUS).

The SIMPLIFIED backend is the historical behaviour and leaves requests, hashes and checkpoints unchanged. ENERGYPLUS runs the
parametric greenhouse (see ``greenhouse_typology``) in EnergyPlus once per run and serves its hourly timeline to the orchestrator.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from agri_twin.application.scenarios import Scenario, actuator_controls, scenario_weather_provider
from agri_twin.domain.farm import FarmConfigRepository
from agri_twin.domain.greenhouse_modularity import configure_greenhouse
from agri_twin.domain.greenhouse_typology import EvidenceStatus, GreenhouseGeometrySpec, GreenhouseTypology, GreenhouseTypologyError, Sourced
from agri_twin.domain.models import WeatherState
from agri_twin.infrastructure.energyplus_timeline import (
    EnergyPlusMicroclimateEngine,
    EnergyPlusTimeline,
    EnergyPlusTimelineError,
    TimelineInputs,
    find_energyplus,
    require_energyplus,
    run_timeline,
)
from agri_twin.infrastructure.energyplus_lockstep import LockstepMicroclimateEngine, LockstepSession
from agri_twin.infrastructure.epw_weather import EpwLocation
from agri_twin.infrastructure.greenhouse_idf import EnvelopeSpec, ThermalSpec

BACKENDS = ("SIMPLIFIED", "ENERGYPLUS")
BACKEND_FIELDS = ("backend", "layout", "hvac", "crop_exchange", "parameters")
# Values of the lumped model that a variant of the simplified greenhouse may override (name -> (spec, field)). Every one is a PROVISIONAL_DEFAULT of the envelope/thermal spec, so a variant is a
# deliberate departure from a placeholder, never a sourced value; the EnergyPlus backend always uses the nominal values.
PARAMETER_FIELDS = {"cover_u_w_m2k": ("envelope", "cover_u_w_m2k"), "cover_shgc": ("envelope", "cover_shgc"), "cover_area_fraction": ("envelope", "cover_area_fraction"),
                    "infiltration_ach": ("thermal", "infiltration_ach"), "max_ventilation_ach": ("thermal", "max_ventilation_ach"), "vent_open_above_c": ("thermal", "vent_open_above_c"),
                    "heating_setpoint_c": ("thermal", "heating_setpoint_c"), "heater_capacity_w_m2": ("thermal", "heater_capacity_w_m2"), "ground_temperature_c": ("thermal", "ground_temperature_c")}
HVAC_FIELDS = ("cooling_setpoint_c", "cooling_capacity_w_m2")
LAYOUT_FIELDS = ("typology", "span_m", "n_spans", "n_bays", "gutter_height_m", "ridge_rise_m", "pillar_spacing_m")
DEFAULT_TYPOLOGY = GreenhouseTypology.MULTITUNEL_CAPILLA.value
FARM_CONFIG = Path(__file__).resolve().parents[3] / "src" / "farm_config.json"
DEFAULT_LOCATION = EpwLocation(40.0, -3.0, 0.0, "Provisional site", "N/A")
UNSUPPORTED_EVENT_TYPES = {"CO2": "the EnergyPlus backend does not model CO2"}


class GreenhouseBackendError(ValueError):
    """A backend request that cannot be honoured; carries the field path for the API error."""

    def __init__(self, message: str, path: str, kind: str = "INVALID_CONFIGURATION") -> None:
        super().__init__(message)
        self.message, self.path, self.kind = message, path, kind


class GreenhouseBackendRequest:
    """Canonical backend selection. Only non-default (ENERGYPLUS) selections exist as objects; SIMPLIFIED is represented by None."""

    __slots__ = ("backend", "layout", "hvac", "crop_exchange", "parameters")

    def __init__(self, backend: str, layout: tuple[tuple[str, Any], ...], hvac: tuple[tuple[str, float], ...] = (), crop_exchange: bool = False, parameters: tuple[tuple[str, float], ...] = ()) -> None:
        self.backend, self.layout, self.hvac, self.crop_exchange, self.parameters = backend, layout, hvac, crop_exchange, parameters

    def to_dict(self) -> dict[str, Any]:
        return {"backend": self.backend, "layout": dict(self.layout), **({"hvac": dict(self.hvac)} if self.hvac else {}), **({"crop_exchange": True} if self.crop_exchange else {}), **({"parameters": dict(self.parameters)} if self.parameters else {})}  # no entry when absent: earlier requests keep their hashes

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GreenhouseBackendRequest) and (self.backend, self.layout, self.hvac, self.crop_exchange, self.parameters) == (other.backend, other.layout, other.hvac, other.crop_exchange, other.parameters)

    def __hash__(self) -> int:
        return hash((self.backend, self.layout, self.hvac, self.crop_exchange, self.parameters))


def _parameter_fields(parameters: Any) -> tuple[tuple[str, float], ...]:
    """Optional overrides of the lumped model's placeholder values (a working-twin variant). Names are fixed, values finite and positive; nothing is assumed for a name that is absent."""
    if parameters is None:
        return ()
    if not isinstance(parameters, Mapping):
        raise GreenhouseBackendError("greenhouse.parameters must be a mapping", "greenhouse.parameters", "INVALID_REQUEST")
    unknown = sorted(set(parameters) - set(PARAMETER_FIELDS))
    if unknown:
        raise GreenhouseBackendError(f"unknown parameters: {', '.join(unknown)}; allowed: {', '.join(PARAMETER_FIELDS)}", f"greenhouse.parameters.{unknown[0]}", "INVALID_REQUEST")
    values: dict[str, float] = {}
    for name, value in parameters.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) == float("inf") or value <= 0:
            raise GreenhouseBackendError(f"{name} must be a finite positive number", f"greenhouse.parameters.{name}", "INVALID_REQUEST")
        if name in ("cover_shgc", "cover_area_fraction") and value > 1.0:
            raise GreenhouseBackendError(f"{name} is a fraction and cannot exceed 1", f"greenhouse.parameters.{name}", "INVALID_REQUEST")
        values[name] = float(value)
    return tuple(sorted(values.items()))


def _parameter_specs(parameters: tuple[tuple[str, float], ...]) -> tuple[EnvelopeSpec | None, ThermalSpec | None]:
    """The envelope and thermal specs with the overrides applied (marked USER_SUPPLIED: a variant, not a source); ``(None, None)`` without overrides, so the nominal path is untouched."""
    if not parameters:
        return None, None
    changes: dict[str, dict[str, Sourced]] = {"envelope": {}, "thermal": {}}
    for name, value in parameters:
        spec, field = PARAMETER_FIELDS[name]
        changes[spec][field] = Sourced(value, EvidenceStatus.USER_SUPPLIED, f"working-twin variant of {name}")
    return replace(EnvelopeSpec(), **changes["envelope"]), replace(ThermalSpec(), **changes["thermal"])


def _simplified_request(layout: Any, crop_exchange: bool = False, parameters: tuple[tuple[str, float], ...] = ()) -> GreenhouseBackendRequest:
    """The simplified backend is a lumped model of the SAME greenhouse the EnergyPlus backend simulates, so it carries a layout too (default typology when omitted)."""
    fields = _layout_fields(layout)
    _spec(fields)
    return GreenhouseBackendRequest("SIMPLIFIED", tuple(sorted(fields.items())), crop_exchange=crop_exchange, parameters=parameters)


def parse_greenhouse_backend(document: Any, environment: str, runtime_event_types: tuple[str, ...] = ()) -> GreenhouseBackendRequest | None:
    if document is None:
        return _simplified_request(None) if environment == "greenhouse" else None
    if not isinstance(document, Mapping):
        raise GreenhouseBackendError("greenhouse must be a mapping", "greenhouse", "INVALID_REQUEST")
    unknown = sorted(set(document) - set(BACKEND_FIELDS))
    if unknown:
        raise GreenhouseBackendError(f"unknown greenhouse fields: {', '.join(unknown)}; allowed: {', '.join(BACKEND_FIELDS)}", f"greenhouse.{unknown[0]}", "INVALID_REQUEST")
    backend = str(document.get("backend", "SIMPLIFIED")).upper()
    if backend not in BACKENDS:
        raise GreenhouseBackendError(f"greenhouse backend {backend!r} is not available; choose one of {', '.join(BACKENDS)}", "greenhouse.backend", "INVALID_REQUEST")
    layout = document.get("layout")
    hvac = _hvac_fields(document.get("hvac"))
    crop_exchange = document.get("crop_exchange", False)
    if not isinstance(crop_exchange, bool):
        raise GreenhouseBackendError("greenhouse.crop_exchange must be true or false", "greenhouse.crop_exchange", "INVALID_REQUEST")
    if crop_exchange and (backend != "SIMPLIFIED" or environment != "greenhouse"):
        raise GreenhouseBackendError("crop_exchange (transpiration, latent and sensible heat, CO2 uptake) is modelled by the simplified greenhouse only; EnergyPlus runs as a precomputed timeline without the crop",
                                     "greenhouse.crop_exchange", "UNSUPPORTED_ENVIRONMENT")
    parameters = _parameter_fields(document.get("parameters"))
    if parameters and backend != "SIMPLIFIED":
        raise GreenhouseBackendError("greenhouse.parameters varies the lumped model of the simplified greenhouse (a working-twin variant); EnergyPlus always runs the nominal values", "greenhouse.parameters", "UNSUPPORTED_ENVIRONMENT")
    if hvac and backend != "ENERGYPLUS":
        raise GreenhouseBackendError("greenhouse.hvac configures the EnergyPlus ideal-loads cooling; the simplified model is cooled by the climate controller's equipment", "greenhouse.hvac", "UNSUPPORTED_ENVIRONMENT")
    if backend == "SIMPLIFIED":
        if environment != "greenhouse":
            if parameters:
                raise GreenhouseBackendError("parameters need the greenhouse environment (open-field runs have no greenhouse)", "greenhouse.parameters", "UNSUPPORTED_ENVIRONMENT")
            if layout is not None:
                raise GreenhouseBackendError("a layout needs the greenhouse environment (open-field runs have no greenhouse)", "greenhouse.layout", "UNSUPPORTED_ENVIRONMENT")
            return None
        return _simplified_request(layout, crop_exchange, parameters)
    if environment != "greenhouse":
        raise GreenhouseBackendError("the ENERGYPLUS backend needs the greenhouse environment (open-field runs never use EnergyPlus)", "greenhouse.backend", "UNSUPPORTED_ENVIRONMENT")
    spec_fields = _layout_fields(layout)
    _spec(spec_fields)  # validates the geometry now so the error carries the layout path
    for event_type in runtime_event_types:
        if event_type in UNSUPPORTED_EVENT_TYPES:
            raise GreenhouseBackendError(f"event {event_type} is not supported by the ENERGYPLUS backend: {UNSUPPORTED_EVENT_TYPES[event_type]}", "runtime_events", "INVALID_CONFIGURATION")
    try:
        require_energyplus()
    except EnergyPlusTimelineError as exc:
        raise GreenhouseBackendError(str(exc), "greenhouse.backend", "MODEL_NOT_READY") from None
    return GreenhouseBackendRequest("ENERGYPLUS", tuple(sorted(spec_fields.items())), hvac)


def _hvac_fields(hvac: Any) -> tuple[tuple[str, float], ...]:
    """Optional mechanical cooling of the EnergyPlus zone. Both values are the user's (no default exists): a set-point to hold and the installed capacity per m2 of floor."""
    if hvac is None:
        return ()
    if not isinstance(hvac, Mapping):
        raise GreenhouseBackendError("greenhouse.hvac must be a mapping", "greenhouse.hvac", "INVALID_REQUEST")
    unknown = sorted(set(hvac) - set(HVAC_FIELDS))
    if unknown:
        raise GreenhouseBackendError(f"unknown hvac fields: {', '.join(unknown)}; allowed: {', '.join(HVAC_FIELDS)}", f"greenhouse.hvac.{unknown[0]}", "INVALID_REQUEST")
    if set(hvac) != set(HVAC_FIELDS):
        raise GreenhouseBackendError("hvac needs both cooling_setpoint_c and cooling_capacity_w_m2: nothing is assumed", "greenhouse.hvac", "INVALID_REQUEST")
    values: dict[str, float] = {}
    for name in HVAC_FIELDS:
        value = hvac[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) == float("inf"):
            raise GreenhouseBackendError(f"{name} must be a finite number", f"greenhouse.hvac.{name}", "INVALID_REQUEST")
        values[name] = float(value)
    if not 5.0 <= values["cooling_setpoint_c"] <= 50.0:
        raise GreenhouseBackendError("cooling_setpoint_c must be between 5 and 50 degC", "greenhouse.hvac.cooling_setpoint_c", "INVALID_REQUEST")
    if not 0.0 < values["cooling_capacity_w_m2"] <= 1000.0:
        raise GreenhouseBackendError("cooling_capacity_w_m2 must be positive and at most 1000", "greenhouse.hvac.cooling_capacity_w_m2", "INVALID_REQUEST")
    return tuple(sorted(values.items()))


def thermal_spec(request: GreenhouseBackendRequest) -> ThermalSpec:
    hvac = dict(request.hvac)
    if not hvac:
        return ThermalSpec()
    return ThermalSpec(cooling_setpoint_c=Sourced(hvac["cooling_setpoint_c"], EvidenceStatus.USER_SUPPLIED, "user-supplied cooling set-point"),
                       cooling_capacity_w_m2=Sourced(hvac["cooling_capacity_w_m2"], EvidenceStatus.USER_SUPPLIED, "user-supplied installed cooling capacity"))


def _layout_fields(layout: Any) -> dict[str, Any]:
    if layout is None:
        layout = {}
    if not isinstance(layout, Mapping):
        raise GreenhouseBackendError("greenhouse.layout must be a mapping", "greenhouse.layout", "INVALID_REQUEST")
    unknown = sorted(set(layout) - set(LAYOUT_FIELDS))
    if unknown:
        raise GreenhouseBackendError(f"unknown layout fields: {', '.join(unknown)}; allowed: {', '.join(LAYOUT_FIELDS)}", f"greenhouse.layout.{unknown[0]}", "INVALID_REQUEST")
    fields: dict[str, Any] = {"typology": str(layout.get("typology", DEFAULT_TYPOLOGY)).upper()}
    for name in LAYOUT_FIELDS[1:]:
        if layout.get(name) is not None:
            value = layout[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise GreenhouseBackendError(f"{name} must be a number", f"greenhouse.layout.{name}", "INVALID_REQUEST")
            fields[name] = int(value) if name in {"n_spans", "n_bays"} else float(value)
    return fields


def _spec(fields: Mapping[str, Any]) -> GreenhouseGeometrySpec:
    try:
        typology = GreenhouseTypology(fields["typology"])
    except ValueError:
        raise GreenhouseBackendError(f"unknown typology {fields['typology']!r}; available: {', '.join(t.value for t in GreenhouseTypology)}", "greenhouse.layout.typology") from None
    try:
        return configure_greenhouse(typology, **{name: value for name, value in fields.items() if name != "typology"}).spec
    except GreenhouseTypologyError as exc:
        raise GreenhouseBackendError(str(exc), "greenhouse.layout") from None


def layout_spec(request: GreenhouseBackendRequest) -> GreenhouseGeometrySpec:
    return _spec(dict(request.layout))


def layout_floor_area_m2(layout: Any) -> float:
    """Floor area of a layout document (the ``greenhouse.layout`` block of a request; None: the default layout), without needing EnergyPlus."""
    from agri_twin.domain.greenhouse_typology import floor_area_m2

    return floor_area_m2(layout_spec(_simplified_request(layout)))


def simplified_configuration(request: GreenhouseBackendRequest):
    """(lumped configuration, description) of the greenhouse of this request: derived from the same geometry and envelope as the EnergyPlus model."""
    from agri_twin.application.consistent_greenhouse import reduced_configuration

    envelope, thermal = _parameter_specs(request.parameters)
    configuration, description = reduced_configuration(layout_spec(request), envelope, thermal)
    return configuration, ({**description, "parameter_overrides": dict(request.parameters)} if request.parameters else description)


def describe(request: GreenhouseBackendRequest, lockstep: bool = False) -> dict[str, Any]:
    """Effective configuration block (hashed with the rest of the effective configuration)."""
    spec = layout_spec(request)
    if request.backend == "SIMPLIFIED":
        configuration, description = simplified_configuration(request)
        if request.crop_exchange:
            description = {**description, "crop_exchange": True, "limits": ["crop exchange: transpiration (water balance of the indoor air, limited by its vapour deficit), latent and sensible heat and CO2 uptake from a growth carbon proxy, iterated "
                                                                           f"{3} times per step against the air it produces; engineering defaults, not calibrated", "no crop respiration or CO2 emission (needs a user-supplied rate: none is assumed)",
                                                                           "the climate controller's one-step forecast ignores the crop's transpiration cooling", *description["limits"][1:]]}
        return {"backend": "SIMPLIFIED", "layout": dict(request.layout), "geometry_provenance": spec.provenance.value, **description}
    install = find_energyplus()
    return {
        "backend": "ENERGYPLUS", "layout": dict(request.layout), "geometry_provenance": spec.provenance.value,
        "energyplus_version": install.version if install else None,
        "model": "single thermal zone, faceted cover, ideal-loads heater" + (" and ideal-loads cooling (user set-point and capacity)" if request.hvac else "") + ", temperature-controlled plus commanded natural ventilation",
        **({"hvac": dict(request.hvac)} if request.hvac else {}),
        **({"mode": "LOCK_STEP", "lock_step": "a climate controller drives EnergyPlus hour by hour through a Python Plugin bridge (vents, extra air changes, a signed power into the air, thermostat stand-down); "
                                              "the controller forecasts with the lumped model of the same greenhouse, corrected by its last error; the shade screen cannot be driven; a resume replays the run from its start"}
           if lockstep else {"mode": "TIMELINE"}),
        "limits": ["placeholder envelope/thermal values (PROVISIONAL_DEFAULT)", "no crop feedback (transpiration, CO2 uptake)", "CO2 not modelled",
                   "shading approximated as an external screen scaling the solar input", "software qualification only; not validated against a real greenhouse"],
    }


def _location(plot_id: str) -> EpwLocation:
    try:
        plot = next(p for p in FarmConfigRepository(FARM_CONFIG).plots if p.plot_id == plot_id)
        return EpwLocation(float(plot.latitude), float(plot.longitude), float(plot.elevation or 0.0), plot_id, "N/A")
    except (StopIteration, AttributeError, OSError, ValueError, TypeError):
        return DEFAULT_LOCATION


def _hourly_forcing(full_scenario: Scenario, base_factory: Callable[[Scenario], Any] | None, end: datetime) -> tuple[list[tuple[datetime, WeatherState]], list[float], list[float]]:
    """The hourly weather (events included), the commanded vent opening and the commanded shading the orchestrator would see from the campaign start to ``end`` (padded to whole days)."""
    provider = scenario_weather_provider(full_scenario, base_factory)
    start = full_scenario.start.astimezone(timezone.utc)
    midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
    first = midnight + timedelta(hours=1)
    last = end.astimezone(timezone.utc)
    if (last.hour, last.minute, last.second) != (0, 0, 0):
        last = last.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    series: list[tuple[datetime, WeatherState]] = []
    forced: list[float] = []
    shading: list[float] = []
    previous: WeatherState | None = None
    label = first
    while label <= last:
        try:
            state = provider.get(label)
        except Exception:  # rows outside the generated range only pad whole days; they are never read back
            if previous is None:
                raise
            state = previous
        previous = state
        # the runner applies the actuators active at the START of the step; the step ending at `label` started one hour earlier
        controls = actuator_controls([event for event in full_scenario.events if event.active(label - timedelta(hours=1))])
        forced.append(controls["ventilation"].actual if "ventilation" in controls else 0.0)
        shading.append(controls["shade"].actual if "shade" in controls else 0.0)
        series.append((label, state))
        label += timedelta(hours=1)
    return series, forced, shading


def build_timeline(request: GreenhouseBackendRequest, plot_id: str, full_scenario: Scenario, base_factory: Callable[[Scenario], Any] | None, end: datetime) -> EnergyPlusTimeline:
    """Run EnergyPlus from the campaign start to ``end`` with the weather and commanded actuators the orchestrator would see."""
    series, forced, shading = _hourly_forcing(full_scenario, base_factory, end)
    inputs = TimelineInputs(_location(plot_id), tuple(series), tuple(forced), tuple(shading), layout_spec(request), thermal=thermal_spec(request))
    return run_timeline(inputs)


def open_lockstep(request: GreenhouseBackendRequest, plot_id: str, full_scenario: Scenario, base_factory: Callable[[Scenario], Any] | None, end: datetime) -> tuple[LockstepSession, dict[str, Any]]:
    """Start EnergyPlus in lock-step from the campaign start with the weather the orchestrator would see; the caller owns (and must close) the session.

    Manual ventilation events are not written into the run: they reach EnergyPlus hour by hour through the actuators the runner passes, together with a controller's. Manual shading events are
    scaled into the weather file, as in the open-loop timeline (the screen cannot be driven in lock-step)."""
    series, _forced, shading = _hourly_forcing(full_scenario, base_factory, end)
    session = LockstepSession(layout_spec(request), series, shading, _location(plot_id), thermal=thermal_spec(request))
    provenance = {"backend": "ENERGYPLUS", "mode": "LOCK_STEP", "energyplus_version": session.install.version, "executable_source": session.install.source, "idf_hash": session.idf_hash,
                  "classification": "SOFTWARE_QUALIFICATION_ONLY (placeholder envelope properties; not validated against a real greenhouse)",
                  "feedback": "no crop feedback into EnergyPlus (no transpiration, no CO2 uptake)", "co2": "not modelled",
                  "control": "hour by hour through a Python Plugin bridge; shade screen not drivable; resuming from a checkpoint replays the run from its start"}
    return session, provenance


def lockstep_engine_factory(session: LockstepSession, request: GreenhouseBackendRequest) -> Callable[[Scenario, Any], LockstepMicroclimateEngine]:
    from agri_twin.application.consistent_greenhouse import GeometryGreenhouseEngine

    # one engine for every segment of a run (a resume replays the prefix and continues on the same session); the controller forecasts with the lumped model of the same greenhouse
    engine = LockstepMicroclimateEngine(session, GeometryGreenhouseEngine(simplified_configuration(request)[0]))
    return lambda _scenario, _provider: engine


def engine_factory(timeline: EnergyPlusTimeline) -> Callable[[Scenario, Any], EnergyPlusMicroclimateEngine]:
    return lambda _scenario, _provider: EnergyPlusMicroclimateEngine(timeline)


def with_runtime_events(scenario: Scenario, events: tuple[Any, ...]) -> Scenario:
    return replace(scenario, events=scenario.events + tuple(event.to_scenario_event() for event in events)) if events else scenario
