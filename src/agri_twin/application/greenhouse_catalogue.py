"""Greenhouse layout catalogue for the frontend scene.

Single source of truth for geometry: the browser receives manufacturer modularity options and ready-made roof
cross-sections computed by `greenhouse_typology` and never re-implements the geometry equations. The layout is a
presentation choice: the simplified greenhouse model has no geometry input, so it does not change simulation results.
"""

from __future__ import annotations

from typing import Any

from agri_twin.domain.greenhouse_modularity import CATALOGUE_RULES, MAX_SPANS, OpenFieldSpec, OptionSet, configure_greenhouse
from agri_twin.domain.greenhouse_typology import GreenhouseTypology, GreenhouseTypologyError, default_geometry, provisional, span_profile

CATALOGUE_VERSION = "1.0"
GEOMETRY_STATEMENT = (
    "Parametric schematic derived from the manufacturer's public catalogue. It is not a manufacturer drawing; "
    "values the catalogue does not publish are provisional. The layout does not alter the simplified greenhouse model."
)


def _samples(option_set: OptionSet, default: float) -> list[float]:
    values = list(option_set.values)
    if option_set.minimum is not None and option_set.maximum is not None:
        values += [option_set.minimum, round((option_set.minimum + option_set.maximum) / 2, 3), option_set.maximum]
    return sorted({round(v, 3) for v in values}) if values else [round(default, 3)]


def _listed(option_set: OptionSet) -> bool:
    return bool(option_set.values) or option_set.minimum is not None


def _key(span: float, rise: float) -> str:
    return f"{span:g}|{rise:g}"


def build_greenhouse_catalogue() -> dict[str, Any]:
    typologies: dict[str, Any] = {}
    for typology in GreenhouseTypology:
        rules = CATALOGUE_RULES[typology]
        base = default_geometry(typology)
        rises = _samples(rules.ridge_rise_m, base.ridge_rise_m.value)
        if not _listed(rules.ridge_rise_m):
            rises = sorted({round(base.ridge_rise_m.value * k, 3) for k in (0.5, 1.0, 1.5)})
        gutters = [4.0, 4.5, 5.0, 5.5, 6.0, 6.5] if rules.gutter_height_m.minimum is not None else _samples(rules.gutter_height_m, base.gutter_height_m.value)
        pillars = [2.0, 2.5] if rules.pillar_spacing_m.minimum is not None else _samples(rules.pillar_spacing_m, base.pillar_spacing_m.value)
        profiles: dict[str, Any] = {}
        for span in _samples(rules.span_m, base.span_m.value):
            for rise in rises:
                try:
                    configured = configure_greenhouse(typology, span_m=span, ridge_rise_m=rise)
                except GreenhouseTypologyError:
                    continue
                gutter = configured.spec.gutter_height_m.value
                profiles[_key(span, rise)] = {
                    "profile": [[round(y, 4), round(z - gutter, 4)] for y, z in span_profile(configured.spec)],
                    "kind": configured.spec.profile.value,
                    "off_catalogue": list(configured.off_catalogue),
                }
        typologies[typology.value] = {
            "default": {"span": base.span_m.value, "rise": base.ridge_rise_m.value, "gutter": base.gutter_height_m.value,
                        "pillar": base.pillar_spacing_m.value, "spans": base.spans, "bays": round(base.length_m.value / base.pillar_spacing_m.value)},
            "options": {"span": _samples(rules.span_m, base.span_m.value), "rise": rises, "gutter": gutters, "pillar": pillars},
            "listed": {"rise": _listed(rules.ridge_rise_m), "gutter": _listed(rules.gutter_height_m)},
            "sources": {"span": rules.span_m.source, "rise": rules.ridge_rise_m.source, "gutter": rules.gutter_height_m.source},
            "profiles": profiles,
        }
    # schematic plot sized so individual plants stay legible; every value is a provisional default
    field = OpenFieldSpec(plot_width_m=provisional(12.0), plot_length_m=provisional(12.0), row_spacing_m=provisional(0.75), plant_spacing_m=provisional(0.3))
    open_field = {"width": field.plot_width_m.value, "length": field.plot_length_m.value, "row_spacing": field.row_spacing_m.value,
                  "plant_spacing": field.plant_spacing_m.value, "evidence": field.plot_width_m.evidence.value, "uses_energyplus": field.uses_energyplus}
    return {"version": CATALOGUE_VERSION, "open_field": open_field, "geometry_provenance": "PARAMETRIC_SCHEMATIC", "statement": GEOMETRY_STATEMENT,
            "max_spans": MAX_SPANS, "typologies": typologies}
