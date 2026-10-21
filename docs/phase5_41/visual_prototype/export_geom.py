import json, sys
from agri_twin.domain.greenhouse_typology import all_typologies, default_geometry, span_profile
out = {}
for t in all_typologies():
    g = default_geometry(t)
    out[t.value] = {
        "span": g.span_m.value, "spans": g.spans, "length": g.length_m.value, "gutter": g.gutter_height_m.value,
        "pillar_spacing": g.pillar_spacing_m.value, "profile": [list(p) for p in span_profile(g)],
        "evidence": {k: getattr(g, k).evidence.value for k in ("span_m", "length_m", "gutter_height_m", "ridge_rise_m")},
    }
json.dump(out, open(sys.argv[1], "w"), indent=1)
