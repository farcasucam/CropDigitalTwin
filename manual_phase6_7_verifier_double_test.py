"""Phases 6.6-6.8 with a language-model DOUBLE: the verifier and the minimal pipeline on the four scenarios of the twin, in Spanish and English.

    python -u manual_phase6_7_verifier_double_test.py     # writes data/xai/verifier_double_report.json

No real language model is used (the double reads the facts in its prompt). What this measures, and what it cannot:
* a faithful writer must pass the verifier with no violation (false positives would make the verifier useless);
* each planted defect (a claim without facts, an invented fact id, a distorted number, a wrong unit, causal wording, confirmation wording, a forbidden claim, a claim of validation in the real system, a recommendation resting
  on an unconfirmed estimate) must be caught on its claim, with the expected rule, with nothing else flagged, and the correction must pass the verifier again.
The planted defects are the verifier's KNOWN classes: this is a coverage test of the rules, not an estimate of how a real model fails (its errors are subtler) and not a quality result. The scenario with the heat wave also carries a
what-if effect CONFIRMED by seven variants of the working twin (small mismatch), so the twin level and the recommendation rule are exercised on real twin output.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import ScenarioDescriptor, content_hash, paired_frames  # noqa: E402
from tsxai.forecast import LaggedRegressionBackend  # noqa: E402
from tsxai.report import explain  # noqa: E402
from tsxai.semantics import SemanticEnricher, ordered  # noqa: E402
from tsxai.testing.llm_doubles import ERROR_CLASSES, EXPECTED_RULES, FaithfulWriter, PlantedErrorWriter  # noqa: E402
from tsxai.verify import verify  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, twin_series_source  # noqa: E402
from agri_twin.interfaces.xai_double_twin import load_design, variants, working_scenario  # noqa: E402
from manual_phase6_4_semantics_test import CASES, HEAT_WAVE, HORIZON, LENGTH, START, build  # noqa: E402

ACTION = {"untraced": "REMOVED", "phantom_fact": "REMOVED", "forbidden": "REMOVED", "real_world": "REMOVED", "number": "REWRITTEN", "unit": "REWRITTEN", "causal": "REWRITTEN", "confirmed": "REWRITTEN", "recommendation": "BLOCKED"}


def twin_confirmation(simulator, source, facts, pack):
    """Replace the what-if fact of the heat-wave scenario by one with the working twin's variants (small mismatch): the peak effect on the indoor temperature of each variant."""
    labels = {**CASES[1][1], "crop": CASES[1][0]}
    base = ScenarioDescriptor(labels, 1, 480, LENGTH, simulator.scenario_options(labels, 1))
    peaks = []
    for parameters in variants("small", load_design()):
        pair = paired_frames(source, working_scenario(base, parameters), [HEAT_WAVE])
        cut = pair.first_changed_sample
        peaks.append(max(pair.effect("temperature_c")[cut:cut + HORIZON], key=abs))
    old = next(f for f in facts if f.kind == "COUNTERFACTUAL")
    new = SemanticEnricher(pack, 1.0, "SYNTHETIC").counterfactual("temperature_c", "the heat wave", old.window, "degC", forecaster_effect=old.value, twin_effects=peaks, ref="working-twin-ensemble")
    return ordered([*(f for f in facts if f.fact_id != old.fact_id), *new]), peaks


def main() -> int:
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    backend = LaggedRegressionBackend()
    rows, detection = [], {c: [0, 0] for c in ERROR_CLASSES}
    false_positives = faithful_runs = 0
    for index, (crop, extra) in enumerate(CASES):
        _, _, facts, pack, _ = build(index, simulator, source, backend)
        peaks = None
        if index == 1:
            facts, peaks = twin_confirmation(simulator, source, facts, pack)
            assert any(f.evidence_level == "TWIN_CONFIRMED" and f.kind == "COUNTERFACTUAL" for f in facts), "the heat-wave scenario must carry a twin-confirmed effect"
        for language in ("en", "es"):
            bundle = explain(facts, pack, FaithfulWriter(facts, pack), language)
            faithful_runs += 1
            false_positives += len(bundle.report.violations)
            assert bundle.status == "OK" and bundle.report.clean and bundle.final == bundle.raw, (index, language, bundle.report.to_dict())
            assert bundle.content_hash == explain(facts, pack, FaithfulWriter(facts, pack), language).content_hash
            if any(f.evidence_level == "TWIN_CONFIRMED" for f in facts):
                assert len(bundle.final.recommendations) == 1 and bundle.final.recommendations[0].blocked_by == ()
            for error_class in ERROR_CLASSES:
                writer = PlantedErrorWriter(facts, pack, error_class)
                planted = explain(facts, pack, writer, language)
                if not writer.planted:
                    continue  # nothing eligible in this scenario (counted as not planted, not as caught)
                detection[error_class][1] += 1
                ids = {c for c, _ in writer.planted}
                rules = {v.rule for v in planted.report.violations}
                caught = {v.claim_id for v in planted.report.violations} == ids and rules == EXPECTED_RULES[error_class] and {c.action for c in planted.report.corrections} == {ACTION[error_class]}
                caught = caught and verify(planted.final, facts, pack, language).clean
                detection[error_class][0] += caught
                assert caught, (index, language, error_class, planted.report.to_dict())
            rows.append({"case": f"{index}_{crop}_{'_'.join(extra.values())}", "language": language, "facts": len(facts), "claims": len(bundle.raw.claims), "bundle_hash": bundle.content_hash,
                         "by_level": dict(Counter(f.evidence_level for f in facts)), **({"twin_variant_peaks_c": peaks} if peaks else {})})
    report = {"status": "PASS", "llm": "DOUBLE (no real model)", "faithful_runs": faithful_runs, "faithful_violations": false_positives,
              "planted": {c: {"caught": got, "planted": total} for c, (got, total) in detection.items()}, "rows": rows,
              "statement": "coverage of the verifier's known rule classes with a double; not an estimate of a real model's errors; no quality claim; synthetic data"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    out = ROOT / "data" / "xai" / "verifier_double_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"faithful_runs": faithful_runs, "faithful_violations": false_positives, "planted": report["planted"], "report_hash": report["report_hash"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
