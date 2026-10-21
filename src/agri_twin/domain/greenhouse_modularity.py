"""Manufacturer modularity rules, configurable greenhouses and the open-field alternative.

`CATALOGUE_RULES` records which dimension options the Novagric public pages list for each typology. A request that
uses a listed option is tagged DOCUMENTED_COMMERCIAL; any other value is accepted (the pages say more combinations
exist) but is tagged USER_SUPPLIED and reported as off-catalogue. Number of modules, length and maximum size are not
published: spans, bays and the limit below are structural assumptions or user choices, never manufacturer facts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum

from agri_twin.domain.greenhouse_typology import (
    EvidenceStatus,
    GeometryProvenance,
    GreenhouseGeometrySpec,
    GreenhouseTypology,
    GreenhouseTypologyError,
    RoofProfile,
    Sourced,
    default_geometry,
    documented,
    provisional,
)

MAX_SPANS = 20  # provisional sanity limit; the manufacturer publishes none
_CATALOGUE = "https://novagric.com/invernaderos/tipos-de-invernaderos/"


@dataclass(frozen=True, slots=True)
class OptionSet:
    """Listed discrete options and/or a listed continuous range for one dimension."""

    values: tuple[float, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    source: str = "not published"

    def contains(self, value: float) -> bool:
        if any(math.isclose(value, v, abs_tol=1e-9) for v in self.values):
            return True
        return self.minimum is not None and self.maximum is not None and self.minimum - 1e-9 <= value <= self.maximum + 1e-9


@dataclass(frozen=True, slots=True)
class ModularityRules:
    typology: GreenhouseTypology
    span_m: OptionSet
    gutter_height_m: OptionSet
    ridge_rise_m: OptionSet
    pillar_spacing_m: OptionSet


def _rules() -> dict[GreenhouseTypology, ModularityRules]:
    cap, got, tro = _CATALOGUE + "invernadero-capilla/", _CATALOGUE + "invernadero-gotico/", _CATALOGUE + "invernadero-asimetrico-o-tropical/"
    lux, ras, tun = _CATALOGUE + "invernadero-lux/", _CATALOGUE + "invernadero-raspa-y-amagado/", _CATALOGUE + "invernadero-tipo-tunel/"
    return {
        GreenhouseTypology.MULTITUNEL_CAPILLA: ModularityRules(
            GreenhouseTypology.MULTITUNEL_CAPILLA,
            OptionSet((8.0, 9.6), source=cap), OptionSet((4.0, 4.5, 5.0, 5.5), source=cap),
            OptionSet(minimum=1.8, maximum=2.2, source=cap), OptionSet((2.5, 5.0), source=cap)),
        GreenhouseTypology.MULTITUNEL_GOTICO: ModularityRules(
            GreenhouseTypology.MULTITUNEL_GOTICO,
            OptionSet((8.0, 9.6, 12.8, 14.4, 16.0), source=got), OptionSet(minimum=4.0, maximum=6.5, source=got),
            OptionSet((2.5, 3.0), source=got), OptionSet((2.5, 3.0), source=got)),
        GreenhouseTypology.MULTITUNEL_TROPICAL_ASIMETRICO: ModularityRules(
            GreenhouseTypology.MULTITUNEL_TROPICAL_ASIMETRICO,
            OptionSet((9.6,), source=tro), OptionSet(minimum=4.0, maximum=6.5, source=tro),
            OptionSet(source=tro + " (ridge height not published)"), OptionSet(minimum=2.0, maximum=2.5, source=tro)),
        GreenhouseTypology.MULTITUNEL_GRANDE_LUX: ModularityRules(
            GreenhouseTypology.MULTITUNEL_GRANDE_LUX,
            OptionSet((12.8, 14.4, 16.0), source=lux), OptionSet(minimum=4.0, maximum=6.5, source=lux),
            OptionSet((2.5, 3.0), source=lux), OptionSet((3.0,), source=lux)),
        GreenhouseTypology.RASPA_Y_AMAGADO: ModularityRules(
            GreenhouseTypology.RASPA_Y_AMAGADO,
            OptionSet((8.0, 9.6, 10.0), source=ras), OptionSet(source=ras + " (eave height not published)"),
            OptionSet(source=ras + " (raspa/amagado heights not published)"), OptionSet((5.0, 9.6, 10.0), source=ras)),
        GreenhouseTypology.TUNEL: ModularityRules(
            GreenhouseTypology.TUNEL,
            OptionSet((8.0, 9.6), source=tun), OptionSet((0.0,), source=tun + " (arches spring from the ground)"),
            OptionSet((4.0, 5.0), source=tun + " (height 4 or 5 m)"), OptionSet((2.5,), source=tun)),
    }


CATALOGUE_RULES: dict[GreenhouseTypology, ModularityRules] = _rules()


@dataclass(frozen=True, slots=True)
class ConfiguredGreenhouse:
    spec: GreenhouseGeometrySpec
    off_catalogue: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def is_catalogue_configuration(self) -> bool:
        return not self.off_catalogue


def configure_greenhouse(
    typology: GreenhouseTypology,
    *,
    span_m: float | None = None,
    n_spans: int | None = None,
    n_bays: int | None = None,
    gutter_height_m: float | None = None,
    ridge_rise_m: float | None = None,
    pillar_spacing_m: float | None = None,
    apex_position_fraction: float | None = None,
    allow_off_catalogue: bool = True,
) -> ConfiguredGreenhouse:
    """Build a spec from user dimensions, tagging each field by whether the manufacturer lists that option.

    Length is `n_bays x pillar_spacing` (a structural assumption: bays follow the pillar grid).
    """
    rules = CATALOGUE_RULES[typology]
    base = default_geometry(typology)
    changes: dict[str, object] = {}
    off: list[str] = []
    notes: list[str] = []

    def apply(field_name: str, value: float | None, option_set: OptionSet) -> None:
        if value is None:
            return
        if option_set.contains(value):
            changes[field_name] = documented(float(value), f"{option_set.source} (catalogue option)")
        else:
            if not allow_off_catalogue:
                raise GreenhouseTypologyError(f"{field_name}={value} is not a listed {typology.value} option")
            changes[field_name] = Sourced(float(value), EvidenceStatus.USER_SUPPLIED, f"off-catalogue; manufacturer lists: {option_set.source}")
            off.append(field_name)

    if typology is GreenhouseTypology.TUNEL and gutter_height_m not in (None, 0.0):
        raise GreenhouseTypologyError("tunnel arches spring from the ground; gutter height must be 0")
    apply("span_m", span_m, rules.span_m)
    apply("gutter_height_m", None if typology is GreenhouseTypology.TUNEL else gutter_height_m, rules.gutter_height_m)
    apply("ridge_rise_m", ridge_rise_m, rules.ridge_rise_m)
    apply("pillar_spacing_m", pillar_spacing_m, rules.pillar_spacing_m)
    if n_spans is not None:
        if n_spans < 1 or n_spans > MAX_SPANS:
            raise GreenhouseTypologyError(f"n_spans must be in 1..{MAX_SPANS} (provisional limit)")
        changes["n_spans"] = Sourced(float(n_spans), EvidenceStatus.USER_SUPPLIED, "user-chosen number of modules; not published")
    if apex_position_fraction is not None:
        changes["apex_position_fraction"] = Sourced(apex_position_fraction, EvidenceStatus.USER_SUPPLIED, "user-chosen apex position")
    if typology is GreenhouseTypology.TUNEL:
        final_span = changes["span_m"].value if "span_m" in changes else base.span_m.value  # type: ignore[union-attr]
        final_rise = changes["ridge_rise_m"].value if "ridge_rise_m" in changes else base.ridge_rise_m.value  # type: ignore[union-attr]
        changes["profile"] = RoofProfile.POINTED_ARCH if final_rise > final_span / 2 else RoofProfile.SEGMENTAL_ARCH
        if changes["profile"] is RoofProfile.POINTED_ARCH:
            notes.append("tunnel taller than half its span is drawn as an ogival arch (the page says curved or ogival)")
    spec = replace(base, **changes) if changes else base
    if n_bays is not None:
        if n_bays < 1:
            raise GreenhouseTypologyError("n_bays must be at least 1")
        length = n_bays * spec.pillar_spacing_m.value
        spec = replace(spec, length_m=Sourced(length, EvidenceStatus.USER_SUPPLIED, f"{n_bays} bays x {spec.pillar_spacing_m.value} m pillar spacing"))
        notes.append("length follows the pillar grid (structural assumption)")
    spec = replace(spec, provenance=GeometryProvenance.PARAMETRIC_SCHEMATIC)
    # replace() re-runs __post_init__, so impossible geometry (e.g. a segmental arch above half its span) raises here
    return ConfiguredGreenhouse(spec, tuple(off), tuple(notes))


class CultivationSystem(str, Enum):
    GREENHOUSE = "GREENHOUSE"  # microclimate from a greenhouse backend (simplified or EnergyPlus)
    OPEN_FIELD = "OPEN_FIELD"  # crop sees outdoor weather directly; no thermal backend


@dataclass(frozen=True, slots=True)
class OpenFieldSpec:
    """Schematic open-air plot. No envelope, no EnergyPlus; the orchestrator's outdoor mode drives the crop."""

    plot_width_m: Sourced = field(default_factory=lambda: provisional(30.0))
    plot_length_m: Sourced = field(default_factory=lambda: provisional(30.0))
    row_spacing_m: Sourced = field(default_factory=lambda: provisional(1.5))
    plant_spacing_m: Sourced = field(default_factory=lambda: provisional(0.5))
    row_azimuth_deg: Sourced = field(default_factory=lambda: provisional(0.0, "rows run along the plot length"))
    system: CultivationSystem = CultivationSystem.OPEN_FIELD
    provenance: GeometryProvenance = GeometryProvenance.PARAMETRIC_SCHEMATIC

    def __post_init__(self) -> None:
        for name in ("plot_width_m", "plot_length_m", "row_spacing_m", "plant_spacing_m"):
            if getattr(self, name).value <= 0:
                raise GreenhouseTypologyError(f"{name} must be positive")
        if self.row_spacing_m.value > self.plot_width_m.value:
            raise GreenhouseTypologyError("row spacing cannot exceed the plot width")
        if self.plant_spacing_m.value > self.plot_length_m.value:
            raise GreenhouseTypologyError("plant spacing cannot exceed the plot length")
        if self.system is not CultivationSystem.OPEN_FIELD:
            raise GreenhouseTypologyError("OpenFieldSpec describes the OPEN_FIELD system")

    @property
    def uses_energyplus(self) -> bool:
        return False

    @property
    def rows(self) -> int:
        return max(1, int(self.plot_width_m.value // self.row_spacing_m.value))

    @property
    def plants_per_row(self) -> int:
        return max(1, int(self.plot_length_m.value // self.plant_spacing_m.value))

    @property
    def plant_count(self) -> int:
        return self.rows * self.plants_per_row
