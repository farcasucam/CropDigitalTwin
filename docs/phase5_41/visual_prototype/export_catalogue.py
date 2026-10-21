"""Export manufacturer modularity rules and pre-baked cross-section profiles for the visual prototype.

Geometry stays in Python (single source of truth). Profiles are stored relative to the gutter line, so the browser
only adds the chosen gutter height; spans, bays and gutter are applied in the scene.
"""
import json
import sys

from agri_twin.domain.greenhouse_modularity import CATALOGUE_RULES, configure_greenhouse
from agri_twin.domain.greenhouse_typology import all_typologies, default_geometry, span_profile


def samples(option_set, default):
    values = list(option_set.values)
    if option_set.minimum is not None and option_set.maximum is not None:
        mid = round((option_set.minimum + option_set.maximum) / 2, 3)
        values += [option_set.minimum, mid, option_set.maximum]
    if not values:
        values = [default]
    return sorted(set(round(v, 3) for v in values))


out = {}
for typology in all_typologies():
    rules = CATALOGUE_RULES[typology]
    base = default_geometry(typology)
    rises = samples(rules.ridge_rise_m, base.ridge_rise_m.value)
    if not rules.ridge_rise_m.values and rules.ridge_rise_m.minimum is None:
        rises = sorted(set([round(base.ridge_rise_m.value * k, 3) for k in (0.5, 1.0, 1.5)]))
    spans = samples(rules.span_m, base.span_m.value)
    gutters = samples(rules.gutter_height_m, base.gutter_height_m.value)
    if rules.gutter_height_m.minimum is not None:
        gutters = [4.0, 4.5, 5.0, 5.5, 6.0, 6.5]
    if not rules.gutter_height_m.values and rules.gutter_height_m.minimum is None:
        gutters = [base.gutter_height_m.value]
    pillars = samples(rules.pillar_spacing_m, base.pillar_spacing_m.value)
    if rules.pillar_spacing_m.minimum is not None:
        pillars = [2.0, 2.5]
    profiles = {}
    for span in spans:
        for rise in rises:
            try:
                configured = configure_greenhouse(typology, span_m=span, ridge_rise_m=rise)
            except Exception:
                continue
            spec = configured.spec
            zg = spec.gutter_height_m.value
            profiles[f"{span:g}|{rise:g}"] = {
                "profile": [[round(y, 4), round(z - zg, 4)] for y, z in span_profile(spec)],
                "kind": spec.profile.value,
                "off_catalogue": list(configured.off_catalogue),
            }
    out[typology.value] = {
        "default": {"span": base.span_m.value, "rise": base.ridge_rise_m.value, "gutter": base.gutter_height_m.value,
                    "pillar": base.pillar_spacing_m.value, "spans": base.spans, "bays": round(base.length_m.value / base.pillar_spacing_m.value)},
        "options": {"span": spans, "rise": rises, "gutter": gutters, "pillar": pillars},
        "sources": {"span": rules.span_m.source, "rise": rules.ridge_rise_m.source, "gutter": rules.gutter_height_m.source},
        "listed": {"rise": bool(rules.ridge_rise_m.values or rules.ridge_rise_m.minimum is not None),
                   "gutter": bool(rules.gutter_height_m.values or rules.gutter_height_m.minimum is not None)},
        "profiles": profiles,
    }
json.dump(out, open(sys.argv[1], "w"), separators=(",", ":"))
print({k: len(v["profiles"]) for k, v in out.items()})
