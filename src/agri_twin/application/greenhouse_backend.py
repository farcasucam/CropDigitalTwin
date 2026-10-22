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
from agri_twin.infrastructure.epw_weather import EpwLocation
from agri_twin.infrastructure.greenhouse_idf import ThermalSpec

BACKENDS = ("SIMPLIFIED", "ENERGYPLUS")
BACKEND_FIELDS = ("backend", "layout", "hvac")
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

    __slots__ = ("backend", "layout", "hvac")

    def __init__(self, backend: str, layout: tuple[tuple[str, Any], ...], hvac: tuple[tuple[str, float], ...] = ()) -> None:
        self.backend, self.layout, self.hvac = backend, layout, hvac

    def to_dict(self) -> dict[str, Any]:
        return {"backend": self.backend, "layout": dict(self.layout), **({"hvac": dict(self.hvac)} if self.hvac else {})}  # no block when absent: earlier requests keep their hashes

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GreenhouseBackendRequest) and (self.backend, self.layout, self.hvac) == (other.backend, other.layout, other.hvac)

    def __hash__(self) -> int:
        return hash((self.backend, self.layout, self.hvac))


def _simplified_request(layout: Any) -> GreenhouseBackendRequest:
    """The simplified backend is a lumped model of the SAME greenhouse the EnergyPlus backend simulates, so it carries a layout too (default typology when omitted)."""
    fields = _layout_fields(layout)
    _spec(fields)
    return GreenhouseBackendRequest("SIMPLIFIED", tuple(sorted(fields.items())))


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
    if hvac and backend != "ENERGYPLUS":
        raise GreenhouseBackendError("greenhouse.hvac configures the EnergyPlus ideal-loads cooling; the simplified model is cooled by the climate controller's equipment", "greenhouse.hvac", "UNSUPPORTED_ENVIRONMENT")
    if backend == "SIMPLIFIED":
        if environment != "greenhouse":
            if layout is not None:
                raise GreenhouseBackendError("a layout needs the greenhouse environment (open-field runs have no greenhouse)", "greenhouse.layout", "UNSUPPORTED_ENVIRONMENT")
            return None
        return _simplified_request(layout)
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


def simplified_configuration(request: GreenhouseBackendRequest):
    """(lumped configuration, description) of the greenhouse of this request: derived from the same geometry and envelope as the EnergyPlus model."""
    from agri_twin.application.consistent_greenhouse import reduced_configuration

    return reduced_configuration(layout_spec(request))


def describe(request: GreenhouseBackendRequest) -> dict[str, Any]:
    """Effective configuration block (hashed with the rest of the effective configuration)."""
    spec = layout_spec(request)
    if request.backend == "SIMPLIFIED":
        return {"backend": "SIMPLIFIED", "layout": dict(request.layout), "geometry_provenance": spec.provenance.value, **simplified_configuration(request)[1]}
    install = find_energyplus()
    return {
        "backend": "ENERGYPLUS", "layout": dict(request.layout), "geometry_provenance": spec.provenance.value,
        "energyplus_version": install.version if install else None,
        "model": "single thermal zone, faceted cover, ideal-loads heater" + (" and ideal-loads cooling (user set-point and capacity)" if request.hvac else "") + ", temperature-controlled plus commanded natural ventilation",
        **({"hvac": dict(request.hvac)} if request.hvac else {}),
        "limits": ["placeholder envelope/thermal values (PROVISIONAL_DEFAULT)", "no crop feedback (transpiration, CO2 uptake)", "CO2 not modelled",
                   "shading approximated as an external screen scaling the solar input", "software qualification only; not validated against a real greenhouse"],
    }


def _location(plot_id: str) -> EpwLocation:
    try:
        plot = next(p for p in FarmConfigRepository(FARM_CONFIG).plots if p.plot_id == plot_id)
        return EpwLocation(float(plot.latitude), float(plot.longitude), float(plot.elevation or 0.0), plot_id, "N/A")
    except (StopIteration, AttributeError, OSError, ValueError, TypeError):
        return DEFAULT_LOCATION


def build_timeline(request: GreenhouseBackendRequest, plot_id: str, full_scenario: Scenario, base_factory: Callable[[Scenario], Any] | None, end: datetime) -> EnergyPlusTimeline:
    """Run EnergyPlus from the campaign start to ``end`` with the weather and commanded actuators the orchestrator would see."""
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
    inputs = TimelineInputs(_location(plot_id), tuple(series), tuple(forced), tuple(shading), layout_spec(request), thermal=thermal_spec(request))
    return run_timeline(inputs)


def engine_factory(timeline: EnergyPlusTimeline) -> Callable[[Scenario, Any], EnergyPlusMicroclimateEngine]:
    return lambda _scenario, _provider: EnergyPlusMicroclimateEngine(timeline)


def with_runtime_events(scenario: Scenario, events: tuple[Any, ...]) -> Scenario:
    return replace(scenario, events=scenario.events + tuple(event.to_scenario_event() for event in events)) if events else scenario
