"""Parametric greenhouse typologies and their cross-section geometry.

Geometry is schematic: it is derived from published commercial dimensions (Novagric public catalogue) and from
explicitly provisional defaults. Nothing here is a manufacturer drawing, and no thermal property is inferred
from a typology name. Every numeric field carries its evidence status.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum


class GreenhouseTypologyError(ValueError):
    """Raised for an invalid typology configuration."""


class EvidenceStatus(str, Enum):
    DOCUMENTED_COMMERCIAL = "DOCUMENTED_COMMERCIAL"  # stated on a public marketing page, not a datasheet
    PROVISIONAL_DEFAULT = "PROVISIONAL_DEFAULT"  # placeholder chosen here; replace with a sourced value
    USER_SUPPLIED = "USER_SUPPLIED"


class GeometryProvenance(str, Enum):
    PARAMETRIC_SCHEMATIC = "PARAMETRIC_SCHEMATIC"
    DOCUMENTATION_BASED = "DOCUMENTATION_BASED"
    CAD_MODEL = "CAD_MODEL"


class GreenhouseTypology(str, Enum):
    MULTITUNEL_CAPILLA = "MULTITUNEL_CAPILLA"
    MULTITUNEL_GOTICO = "MULTITUNEL_GOTICO"
    MULTITUNEL_TROPICAL_ASIMETRICO = "MULTITUNEL_TROPICAL_ASIMETRICO"
    MULTITUNEL_GRANDE_LUX = "MULTITUNEL_GRANDE_LUX"
    RASPA_Y_AMAGADO = "RASPA_Y_AMAGADO"
    TUNEL = "TUNEL"


class RoofProfile(str, Enum):
    SEGMENTAL_ARCH = "SEGMENTAL_ARCH"
    POINTED_ARCH = "POINTED_ARCH"
    GABLE = "GABLE"


@dataclass(frozen=True, slots=True)
class Sourced:
    value: float
    evidence: EvidenceStatus
    source: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise GreenhouseTypologyError("sourced value must be finite")


def documented(value: float, source: str) -> Sourced:
    return Sourced(value, EvidenceStatus.DOCUMENTED_COMMERCIAL, source)


def provisional(value: float, source: str = "provisional default; replace with a sourced value") -> Sourced:
    return Sourced(value, EvidenceStatus.PROVISIONAL_DEFAULT, source)


_CATALOGUE = "https://novagric.com/invernaderos/tipos-de-invernaderos/"


@dataclass(frozen=True, slots=True)
class GreenhouseGeometrySpec:
    """Ridges run along x, spans are laid side by side along y, z is up (metres)."""

    typology: GreenhouseTypology
    profile: RoofProfile
    span_m: Sourced
    n_spans: Sourced
    length_m: Sourced
    gutter_height_m: Sourced  # height of the eaves/gutter line; 0 for arches springing from the ground
    ridge_rise_m: Sourced  # rise of the roof above the gutter line
    pillar_spacing_m: Sourced  # structural, not used by the thermal model
    apex_position_fraction: Sourced  # 0.5 = symmetric; only meaningful for GABLE
    arch_radius_span_ratio: Sourced = field(default_factory=lambda: provisional(1.0, "radius of each pointed-arch half / span; not published"))
    segments_per_span: int = 8
    provenance: GeometryProvenance = GeometryProvenance.PARAMETRIC_SCHEMATIC

    def __post_init__(self) -> None:
        if self.span_m.value <= 0 or self.length_m.value <= 0 or self.ridge_rise_m.value <= 0:
            raise GreenhouseTypologyError("span, length and ridge rise must be positive")
        if self.gutter_height_m.value < 0:
            raise GreenhouseTypologyError("gutter height cannot be negative")
        n = self.n_spans.value
        if n < 1 or n != int(n):
            raise GreenhouseTypologyError("n_spans must be a positive integer")
        if self.segments_per_span < 2 or self.segments_per_span % 2:
            raise GreenhouseTypologyError("segments_per_span must be an even integer >= 2")
        if not 0.05 <= self.apex_position_fraction.value <= 0.95:
            raise GreenhouseTypologyError("apex_position_fraction must be within [0.05, 0.95]")
        if self.profile is RoofProfile.SEGMENTAL_ARCH and self.ridge_rise_m.value > self.span_m.value / 2:
            raise GreenhouseTypologyError("a segmental arch cannot rise more than half its span")
        if self.profile is RoofProfile.POINTED_ARCH:
            _pointed_half(self)  # raises if the radius cannot produce a rising arc

    @property
    def spans(self) -> int:
        return int(self.n_spans.value)

    @property
    def width_m(self) -> float:
        return self.span_m.value * self.spans

    def with_values(self, **overrides: Sourced) -> "GreenhouseGeometrySpec":
        """Replace sourced fields (mark them USER_SUPPLIED with a source when you know them)."""
        return replace(self, **overrides)


def default_geometry(typology: GreenhouseTypology) -> GreenhouseGeometrySpec:
    """Catalogue-derived geometry. Values not published by the manufacturer are PROVISIONAL_DEFAULT."""
    length = provisional(30.0)
    spans = provisional(3)
    if typology is GreenhouseTypology.MULTITUNEL_CAPILLA:
        src = _CATALOGUE + "invernadero-capilla/"
        return GreenhouseGeometrySpec(
            typology, RoofProfile.SEGMENTAL_ARCH,
            documented(9.60, src + " (width 8 or 9.60 m)"), spans, length,
            documented(4.0, src + " (height under gutter 4 to 5.50 m)"),
            documented(2.0, src + " (apex 1.80 to 2.20 m above gutter)"),
            documented(5.0, src + " (interior pillar spacing 5 m)"),
            provisional(0.5),
        )
    if typology is GreenhouseTypology.MULTITUNEL_GOTICO:
        src = _CATALOGUE + "invernadero-gotico/"
        return GreenhouseGeometrySpec(
            typology, RoofProfile.POINTED_ARCH,
            documented(9.60, src + " (standard width 8 or 9.60 m)"), spans, length,
            documented(4.0, src + " (height under gutter 4 to 6.50 m)"),
            documented(2.5, src + " (apex +2.50 to 3 m depending on model)"),
            documented(3.0, src + " (every 2.50 or 3 m)"),
            provisional(0.5),
        )
    if typology is GreenhouseTypology.MULTITUNEL_TROPICAL_ASIMETRICO:
        src = _CATALOGUE + "invernadero-asimetrico-o-tropical/"
        return GreenhouseGeometrySpec(
            typology, RoofProfile.GABLE,
            documented(9.60, src + " (standard width 9.60 m)"), spans, length,
            documented(4.0, src + " (height under gutter 4 to 6.50 m)"),
            provisional(2.0, "ridge height not published"),
            documented(2.5, src + " (every 2 to 2.50 m)"),
            provisional(0.35, "one roof side steeper than the other; angles not published"),
        )
    if typology is GreenhouseTypology.MULTITUNEL_GRANDE_LUX:
        src = _CATALOGUE + "invernadero-lux/"
        return GreenhouseGeometrySpec(
            typology, RoofProfile.POINTED_ARCH,
            documented(12.80, src + " (width 12.80, 14.40 or 16 m)"), spans, length,
            documented(4.0, src + " (height under gutter 4 to 6.50 m)"),
            documented(2.5, src + " (apex +2.50 to 3 m; page wording unclear)"),
            documented(3.0, src + " (every 3 m)"),
            provisional(0.5),
        )
    if typology is GreenhouseTypology.RASPA_Y_AMAGADO:
        src = _CATALOGUE + "invernadero-raspa-y-amagado/"
        return GreenhouseGeometrySpec(
            typology, RoofProfile.GABLE,
            documented(10.0, src + " (width 8, 9.60 or 10 m)"), spans, length,
            provisional(3.5, "eave height not published; the 7 m pillar figure is ambiguous and is not used"),
            provisional(1.0, "raspa/amagado heights not published"),
            documented(5.0, src + " (interior pillar spacing 5, 9.60 or 10 m)"),
            provisional(0.5),
        )
    if typology is GreenhouseTypology.TUNEL:
        src = _CATALOGUE + "invernadero-tipo-tunel/"
        return GreenhouseGeometrySpec(
            typology, RoofProfile.SEGMENTAL_ARCH,
            documented(8.0, src + " (width 8 or 9.60 m)"), provisional(1), length,
            documented(0.0, src + " (arches spring from the ground; no straight walls)"),
            documented(4.0, src + " (height 4 or 5 m)"),
            documented(2.5, src + " (arch spacing 2.50 m)"),
            provisional(0.5),
        )
    raise GreenhouseTypologyError(f"unknown typology: {typology!r}")


def _pointed_half(spec: GreenhouseGeometrySpec) -> list[tuple[float, float]]:
    """Left half of a pointed arch: a circular arc of radius ratio*span from the springer to the apex.

    The centre lies on the lower-right side of the chord, so the arc bulges outwards and the two halves meet at a
    point. The arc must rise monotonically (centre not left of the apex), otherwise the profile would overshoot.
    """
    w = spec.span_m.value
    r = spec.ridge_rise_m.value
    zg = spec.gutter_height_m.value
    radius = spec.arch_radius_span_ratio.value * w
    chord = math.hypot(w / 2.0, r)
    if radius < chord / 2.0:
        raise GreenhouseTypologyError("arch radius is too small to join springer and apex")
    offset = math.sqrt(radius * radius - chord * chord / 4.0)
    centre_y = w / 4.0 + offset * r / chord
    centre_z = r / 2.0 - offset * (w / 2.0) / chord
    if centre_y < w / 2.0:
        raise GreenhouseTypologyError("arch radius too small: the arc would overshoot the apex; increase arch_radius_span_ratio")
    a0 = math.atan2(0.0 - centre_z, 0.0 - centre_y)
    a1 = math.atan2(r - centre_z, w / 2.0 - centre_y)
    n = spec.segments_per_span // 2
    return [
        (centre_y + radius * math.cos(a0 + (a1 - a0) * i / n), zg + centre_z + radius * math.sin(a0 + (a1 - a0) * i / n))
        for i in range(n + 1)
    ]


def span_profile(spec: GreenhouseGeometrySpec) -> tuple[tuple[float, float], ...]:
    """Roof cross-section of ONE span as (y, z) points from y=0 to y=span, z absolute above the floor."""
    w = spec.span_m.value
    r = spec.ridge_rise_m.value
    zg = spec.gutter_height_m.value
    n = spec.segments_per_span
    if spec.profile is RoofProfile.SEGMENTAL_ARCH:
        radius = (w * w / 4.0 + r * r) / (2.0 * r)
        centre_z = zg + r - radius
        return tuple(
            (w * i / n, centre_z + math.sqrt(max(0.0, radius * radius - (w * i / n - w / 2.0) ** 2)))
            for i in range(n + 1)
        )
    if spec.profile is RoofProfile.POINTED_ARCH:
        half = _pointed_half(spec)
        return tuple(half + [(w - y, z) for y, z in reversed(half[:-1])])
    apex_y = spec.apex_position_fraction.value * w
    return ((0.0, zg), (apex_y, zg + r), (w, zg))


def span_end_area_m2(spec: GreenhouseGeometrySpec) -> float:
    """Area under the schematic profile of one span (trapezoid rule on the actual facets)."""
    pts = span_profile(spec)
    return sum((pts[i + 1][0] - pts[i][0]) * (pts[i + 1][1] + pts[i][1]) / 2.0 for i in range(len(pts) - 1))


def floor_area_m2(spec: GreenhouseGeometrySpec) -> float:
    return spec.width_m * spec.length_m.value


def volume_m3(spec: GreenhouseGeometrySpec) -> float:
    return span_end_area_m2(spec) * spec.spans * spec.length_m.value


def all_typologies() -> tuple[GreenhouseTypology, ...]:
    return tuple(GreenhouseTypology)
