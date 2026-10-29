"""PT-11: the deterministic narrative (ES and EN) over real effect reports of both domains. No language model.

    TEP_SRC=<tep source directory> python -u manual_phase7_pt11_narrative.py

Cases: (1) tomato outdoors, the nutrient-line design of PT-7a (heat wave and two equal doses, reduced single-pool model, DEV season 34); (2) Tennessee Eastman, the design of PT-10a (season 1), reactive against replayed actuation.
Each narrative is re-read with `check_narrative` (every number traced to a claim, no forbidden wording) and the problems found are part of the report. The wording is the framework's (`tsxai.report.effects_narrative`);
the human names are this script's glossary. DEVELOPMENT: the text is a rendering of the numbers; it adds no analysis.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine  # noqa: E402
from tsxai.report import Glossary, check_narrative, narrate_effects  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402
from process_twins.tennessee_eastman import TennesseeEastman  # noqa: E402

REPORT = ROOT / "data" / "xai" / "narrative_pt11.json"
GLOSSARY = Glossary(
    {"heat_wave": {"en": "the heat wave", "es": "la ola de calor"}, "fert_early": {"en": "the early dose", "es": "la dosis temprana"}, "fert_late": {"en": "the late dose", "es": "la dosis tardía"},
     "idv1": {"en": "the A/C feed ratio step (IDV1)", "es": "el escalón de la relación de alimentación A/C (IDV1)"}, "idv4": {"en": "the reactor cooling water temperature step (IDV4)", "es": "el escalón de temperatura del agua de refrigeración del reactor (IDV4)"},
     "idv5": {"en": "the condenser cooling water temperature step (IDV5)", "es": "el escalón de temperatura del agua del condensador (IDV5)"}},
    {"biomass_total_end": {"en": "the final total biomass", "es": "la biomasa total final"}, "reactor_pressure_max": {"en": "the maximum reactor pressure", "es": "la presión máxima del reactor"},
     "reactor_temperature_mean": {"en": "the mean reactor temperature", "es": "la temperatura media del reactor"}, "reactor_cooling_valve_mean": {"en": "the mean reactor cooling valve opening", "es": "la apertura media de la válvula de refrigeración del reactor"}})


MATERIAL = {"biomass_total_end": 1.0, "reactor_pressure_max": 1.0, "reactor_temperature_mean": 0.1, "reactor_cooling_valve_mean": 0.1}  # smallest effect that matters, declared here (the host's call)


def narratives(report, other=None, outcomes=None):
    out = {}
    for language in ("en", "es"):
        n = narrate_effects(report, language, GLOSSARY, other, outcomes=outcomes, material=MATERIAL)
        out[language] = {"text": n.text, "narrative_hash": n.narrative_hash, "source_report_hash": n.source_report_hash, "problems": check_narrative(n, GLOSSARY, report), "claims": [c.kind for c in n.claims]}
    return out


def main() -> int:
    result = {}
    agri = TwinSimulator()
    labels = {"crop": "tomato", "environment": "outdoor", "control": "off"}
    options = dict(agri.scenario_options(labels, 34))
    desc = ScenarioDescriptor(labels, 34, 1500, 336, options)
    players = (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 96, 6.0),)), Player("fert_early", (Intervention("FERTILIZATION", 20, 24, 24.0),)), Player("fert_late", (Intervention("FERTILIZATION", 280, 24, 24.0),)))
    report = ResimulationEngine(agri).evaluate(EffectQuery(desc, (Outcome("biomass_total_end", "biomass_total_g_m2", "max", "g/m2"),), players, policy=Policy("reactive")))
    report["simulator"] = agri.name
    result["tomato_outdoor_nutrients"] = narratives(report)
    if os.environ.get("TEP_SRC"):
        te = TennesseeEastman()
        d = ScenarioDescriptor({"plant": "tennessee_eastman_base_case"}, 1, 600, 1800, {})
        tp = (Player("idv1", (Intervention("IDV1", 100, 1200),)), Player("idv4", (Intervention("IDV4", 300, 1200),)), Player("idv5", (Intervention("IDV5", 200, 1200),)))
        outs = (Outcome("reactor_temperature_mean", "xmeas_09", "mean", "C"), Outcome("reactor_pressure_max", "xmeas_07", "max", "kPa"))
        engine = ResimulationEngine(te)
        reactive = engine.evaluate(EffectQuery(d, outs, tp, policy=Policy("reactive")))
        replayed = engine.evaluate(EffectQuery(d, outs, tp, policy=Policy("replayed")))
        for r in (reactive, replayed):
            r["simulator"] = te.name
        result["tennessee_eastman"] = narratives(reactive, ("replayed", replayed))
    out = {"status": "DEVELOPMENT: deterministic rendering of effect reports, no language model", "cases": result}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    for case, langs in result.items():
        for lang, v in langs.items():
            print(f"=== {case} [{lang}] problems: {v['problems']}\n{v['text']}\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
