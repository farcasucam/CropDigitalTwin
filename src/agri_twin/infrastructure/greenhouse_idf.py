"""Deterministic EnergyPlus 26.1 IDF text for the parametric greenhouse typologies.

Single thermal zone. The roof is faceted (EnergyPlus surfaces are planar). Cover glazing is a Window sub-surface
on every facet because sub-surfaces are limited to 3-4 vertices; non-rectangular end walls are therefore split
into triangles. Optical/thermal values are provisional unless the caller supplies sourced ones.
No weather location is written: the EPW supplies it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Sequence

from agri_twin.domain.greenhouse_typology import (
    EvidenceStatus,
    GreenhouseGeometrySpec,
    Sourced,
    floor_area_m2,
    provisional,
    span_profile,
    volume_m3,
)

Point = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class EnvelopeSpec:
    cover_u_w_m2k: Sourced = field(default_factory=lambda: provisional(5.8))
    cover_shgc: Sourced = field(default_factory=lambda: provisional(0.80))
    cover_visible_transmittance: Sourced = field(default_factory=lambda: provisional(0.85))
    cover_area_fraction: Sourced = field(default_factory=lambda: provisional(0.90, "glazed share of each facet; rest is structure"))
    frame_conductivity_w_mk: Sourced = field(default_factory=lambda: provisional(50.0))
    frame_thickness_m: Sourced = field(default_factory=lambda: provisional(0.05))


@dataclass(frozen=True, slots=True)
class ThermalSpec:
    infiltration_ach: Sourced = field(default_factory=lambda: provisional(0.5))
    max_ventilation_ach: Sourced = field(default_factory=lambda: provisional(30.0, "design ACH with vents fully open"))
    vent_open_above_c: Sourced = field(default_factory=lambda: provisional(24.0, "indoor temperature above which the vents open (only while the outdoor air is cooler)"))
    heating_setpoint_c: Sourced = field(default_factory=lambda: provisional(12.0))
    heater_capacity_w_m2: Sourced = field(default_factory=lambda: provisional(100.0))
    ground_temperature_c: Sourced = field(default_factory=lambda: provisional(15.0, "constant ground temperature"))


@dataclass(frozen=True, slots=True)
class RunSpec:
    begin_month: int = 1
    begin_day: int = 1
    end_month: int = 12
    end_day: int = 31
    timesteps_per_hour: int = 4
    forced_ventilation_file: str | None = None  # CSV (8760 hourly rows, fraction 0..1) with the commanded vent opening; None: always 0
    python_plugin_module: str | None = None  # set to enable the interactive bridge (see docs/phase5_41)
    python_plugin_class: str | None = None


@dataclass(frozen=True, slots=True)
class BuiltGreenhouseIdf:
    text: str
    idf_hash: str
    floor_area_m2: float
    volume_m3: float
    surface_count: int
    window_count: int
    provenance: dict[str, str]


# The floor layer written into the IDF below (Material, Floor Soil): the reduced model reads the same numbers.
FLOOR_MATERIAL = {"thickness_m": 0.20, "conductivity_w_mk": 1.40, "density_kg_m3": 1800.0, "specific_heat_j_kgk": 800.0}


@dataclass(frozen=True, slots=True)
class _Poly:
    name: str
    kind: str  # Floor | Wall | Roof
    points: tuple[Point, ...]
    inward: Point


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normal(points: Sequence[Point]) -> Point:
    nx = ny = nz = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    return (nx, ny, nz)


def _outward(points: Sequence[Point], inward: Point) -> tuple[Point, ...]:
    n = _normal(points)
    if n[0] * inward[0] + n[1] * inward[1] + n[2] * inward[2] > 0:
        return tuple(reversed(points))
    return tuple(points)


def _centroid(points: Sequence[Point]) -> Point:
    k = len(points)
    return (sum(p[0] for p in points) / k, sum(p[1] for p in points) / k, sum(p[2] for p in points) / k)


def _scaled(points: Sequence[Point], fraction: float) -> tuple[Point, ...]:
    """Shrink a convex polygon towards its vertex centroid so its area is `fraction` of the original."""
    scale = fraction ** 0.5
    c = _centroid(points)
    return tuple(tuple(c[i] + (p[i] - c[i]) * scale for i in range(3)) for p in points)  # type: ignore[misc]


def _triangles(points: Sequence[Point]) -> list[tuple[Point, Point, Point]]:
    c = _centroid(points)
    return [(points[i], points[(i + 1) % len(points)], c) for i in range(len(points))]


def _dedupe(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for p in points:
        if not result or abs(p[0] - result[-1][0]) > 1e-9 or abs(p[1] - result[-1][1]) > 1e-9:
            result.append(p)
    if len(result) > 1 and abs(result[0][0] - result[-1][0]) < 1e-9 and abs(result[0][1] - result[-1][1]) < 1e-9:
        result.pop()
    return result


def _surfaces(spec: GreenhouseGeometrySpec) -> list[_Poly]:
    length = spec.length_m.value
    width = spec.width_m
    zg = spec.gutter_height_m.value
    span = spec.span_m.value
    profile = span_profile(spec)
    polys: list[_Poly] = []
    polys.append(_Poly("Floor", "Floor", ((0.0, 0.0, 0.0), (length, 0.0, 0.0), (length, width, 0.0), (0.0, width, 0.0)), (0.0, 0.0, 1.0)))
    if zg > 1e-9:
        polys.append(_Poly("Side South", "Wall", ((0.0, 0.0, 0.0), (length, 0.0, 0.0), (length, 0.0, zg), (0.0, 0.0, zg)), (0.0, 1.0, 0.0)))
        polys.append(_Poly("Side North", "Wall", ((0.0, width, 0.0), (length, width, 0.0), (length, width, zg), (0.0, width, zg)), (0.0, -1.0, 0.0)))
    for s in range(spec.spans):
        y0 = s * span
        shifted = [(y0 + y, z) for y, z in profile]
        for i in range(len(shifted) - 1):
            (ya, za), (yb, zb) = shifted[i], shifted[i + 1]
            polys.append(_Poly(f"Roof S{s + 1} F{i + 1}", "Roof", ((0.0, ya, za), (length, ya, za), (length, yb, zb), (0.0, yb, zb)), (0.0, 0.0, -1.0)))
        outline = _dedupe([(y0, 0.0), (y0 + span, 0.0)] + list(reversed(shifted)))
        for end, x, inward in (("West", 0.0, (1.0, 0.0, 0.0)), ("East", length, (-1.0, 0.0, 0.0))):
            ring = tuple((x, y, z) for y, z in outline)
            for t, tri in enumerate(_triangles(ring)):
                polys.append(_Poly(f"End {end} S{s + 1} T{t + 1}", "Wall", tri, inward))
    return polys


def cover_area_m2(spec: GreenhouseGeometrySpec) -> float:
    """Total area of the walls and roof facets (the cover, glazing plus frame) of the greenhouse."""
    total = 0.0
    for poly in _surfaces(spec):
        if poly.kind != "Floor":
            n = _normal(poly.points)
            total += 0.5 * (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5
    return total


def _num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _vertices(points: Sequence[Point]) -> str:
    return ",\n".join("  " + ", ".join(_num(c) for c in p) for p in points)


def _obj(kind: str, *fields: object, body: str | None = None) -> str:
    head = ", ".join("" if f is None else str(f) for f in fields)
    return f"{kind}, {head}" + (f",\n{body}" if body else "") + ";"


def build_greenhouse_idf(
    geometry: GreenhouseGeometrySpec,
    envelope: EnvelopeSpec | None = None,
    thermal: ThermalSpec | None = None,
    run: RunSpec | None = None,
) -> BuiltGreenhouseIdf:
    envelope = envelope or EnvelopeSpec()
    thermal = thermal or ThermalSpec()
    run = run or RunSpec()
    area = floor_area_m2(geometry)
    lines: list[str] = []
    add = lines.append
    add("! Generated by agri_twin.infrastructure.greenhouse_idf. Schematic geometry, provisional properties.")
    add(f"! Typology: {geometry.typology.value}; geometry provenance: {geometry.provenance.value}")
    add("Version, 26.1;")
    add("Building, Greenhouse, 0, Country, 0.04, 0.4, FullExterior, 25;")
    add("SimulationControl, No, No, No, No, Yes;")
    add(f"Timestep, {run.timesteps_per_hour};")
    add(f"RunPeriod, Run Period, {run.begin_month}, {run.begin_day}, , {run.end_month}, {run.end_day}, , Monday, Yes, Yes, No, Yes, Yes;")
    add("GlobalGeometryRules, UpperLeftCorner, CounterClockWise, World;")
    # shadows at every timestep: the default periodic average over a block of days made results depend on the run length
    add("ShadowCalculation, PolygonClipping, Timestep, 20;")
    add(f"Site:GroundTemperature:BuildingSurface, {', '.join([_num(thermal.ground_temperature_c.value)] * 12)};")
    add("Zone, Greenhouse Zone, 0, 0, 0, 0, 1, 1, autocalculate, autocalculate;")
    add("Material, Floor Soil, MediumSmooth, 0.20, 1.40, 1800, 800, 0.90, 0.70, 0.70;")
    add(_obj("Material", "Frame", "Smooth", _num(envelope.frame_thickness_m.value), _num(envelope.frame_conductivity_w_mk.value), 7800, 500, 0.90, 0.60, 0.60))
    add(_obj("WindowMaterial:SimpleGlazingSystem", "Cover Film", _num(envelope.cover_u_w_m2k.value), _num(envelope.cover_shgc.value), _num(envelope.cover_visible_transmittance.value)))
    add("Construction, Floor Construction, Floor Soil;")
    add("Construction, Frame Construction, Frame;")
    add("Construction, Cover Construction, Cover Film;")

    polys = _surfaces(geometry)
    windows = 0
    for p in polys:
        pts = _outward(p.points, p.inward)
        construction = "Floor Construction" if p.kind == "Floor" else "Frame Construction"
        boundary = ("Ground", "NoSun", "NoWind", 0.0) if p.kind == "Floor" else ("Outdoors", "SunExposed", "WindExposed", 0.5 if p.kind == "Wall" else 0.0)
        add(_obj("BuildingSurface:Detailed", p.name, p.kind, construction, "Greenhouse Zone", None, boundary[0], None, boundary[1], boundary[2], boundary[3], len(pts), body=_vertices(pts)))
        if p.kind == "Floor":
            continue
        window = _scaled(pts, envelope.cover_area_fraction.value)
        add(_obj("FenestrationSurface:Detailed", f"{p.name} Cover", "Window", "Cover Construction", p.name, None, 0.5, None, 1, len(window), body=_vertices(window)))
        windows += 1

    add("ScheduleTypeLimits, Fraction, 0.0, 1.0, Continuous;")
    add("ScheduleTypeLimits, Temperature, -60, 200, Continuous;")
    add("ScheduleTypeLimits, Mode, 0, 4, Discrete;")
    add("Schedule:Constant, Always On, Fraction, 1.0;")
    if run.forced_ventilation_file:
        add(f"Schedule:File, Forced Vent Opening, Fraction, {run.forced_ventilation_file}, 1, 0, 8760, Comma, No, 60, No;")
    else:
        add("Schedule:Constant, Forced Vent Opening, Fraction, 0.0;")
    add(_obj("Schedule:Constant", "Heating Setpoint", "Temperature", _num(thermal.heating_setpoint_c.value)))
    add("Schedule:Constant, Cooling Setpoint, Temperature, 60.0;")
    add("Schedule:Constant, Thermostat Type, Mode, 4;")
    add(_obj("ZoneInfiltration:DesignFlowRate", "Cover Infiltration", "Greenhouse Zone", "Always On", "AirChanges/Hour", None, None, None, _num(thermal.infiltration_ach.value), 1, 0, 0, 0))
    # Two vent objects: temperature-controlled passive venting (EnergyPlus native limits) and commanded venting from the schedule.
    add(_obj("ZoneVentilation:DesignFlowRate", "Auto Ventilation", "Greenhouse Zone", "Always On", "AirChanges/Hour", None, None, None, _num(thermal.max_ventilation_ach.value), "Natural", 0, 1, 1, 0, 0, 0,
             _num(thermal.vent_open_above_c.value), None, 100, None, 0))
    add(_obj("ZoneVentilation:DesignFlowRate", "Forced Ventilation", "Greenhouse Zone", "Forced Vent Opening", "AirChanges/Hour", None, None, None, _num(thermal.max_ventilation_ach.value), "Natural", 0, 1, 1, 0, 0, 0))
    add("ThermostatSetpoint:DualSetpoint, Dual SP, Heating Setpoint, Cooling Setpoint;")
    add("ZoneControl:Thermostat, Zone Thermostat, Greenhouse Zone, Thermostat Type, ThermostatSetpoint:DualSetpoint, Dual SP;")
    capacity = thermal.heater_capacity_w_m2.value * area
    add(_obj("ZoneHVAC:IdealLoadsAirSystem", "Heater", None, "Heater Supply Node", None, None, 45.0, 12.0, 0.015, 0.009, "LimitCapacity", None, _num(capacity), "NoLimit", None, None, None, None, "ConstantSensibleHeatRatio", 0.7, "None"))
    add("ZoneHVAC:EquipmentList, Zone Equipment, SequentialLoad, ZoneHVAC:IdealLoadsAirSystem, Heater, 1, 1, , ;")
    add("ZoneHVAC:EquipmentConnections, Greenhouse Zone, Zone Equipment, Heater Supply Node, , Zone Air Node, Zone Return Node;")
    if run.python_plugin_module and run.python_plugin_class:
        add("PythonPlugin:SearchPaths, Plugin Paths, Yes, Yes, Yes;")
        add(f"PythonPlugin:Instance, Interactive Bridge, No, {run.python_plugin_module}, {run.python_plugin_class};")
    for key, name in (
        ("Environment", "Site Outdoor Air Drybulb Temperature"),
        ("Greenhouse Zone", "Zone Mean Air Temperature"),
        ("Greenhouse Zone", "Zone Air Relative Humidity"),
        ("Greenhouse Zone", "Enclosure Windows Total Transmitted Solar Radiation Rate"),
        ("Greenhouse Zone", "Zone Ventilation Standard Density Air Change Rate"),
        ("Greenhouse Zone", "Zone Infiltration Standard Density Air Change Rate"),
        ("Heater", "Zone Ideal Loads Zone Total Heating Rate"),
        ("Heater", "Zone Ideal Loads Zone Total Cooling Rate"),
    ):
        add(f"Output:Variable, {key}, {name}, Timestep;")
    add("Output:SQLite, SimpleAndTabular;")

    text = "\n".join(lines) + "\n"
    provenance = {
        f"geometry.{name}": f"{getattr(geometry, name).evidence.value}: {getattr(geometry, name).source}"
        for name in ("span_m", "n_spans", "length_m", "gutter_height_m", "ridge_rise_m", "pillar_spacing_m", "apex_position_fraction")
    }
    for group, spec in (("envelope", envelope), ("thermal", thermal)):
        for name in spec.__slots__:  # type: ignore[attr-defined]
            value = getattr(spec, name)
            provenance[f"{group}.{name}"] = f"{value.evidence.value}: {value.source}"
    return BuiltGreenhouseIdf(
        text=text,
        idf_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        floor_area_m2=area,
        volume_m3=volume_m3(geometry),
        surface_count=len(polys),
        window_count=windows,
        provenance=provenance,
    )


__all__ = ["BuiltGreenhouseIdf", "EnvelopeSpec", "EvidenceStatus", "RunSpec", "ThermalSpec", "build_greenhouse_idf"]
