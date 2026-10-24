"""Phase 6.1 verification: multivariate frames of the twin with roles, provenance, data-quality facts and stable hashes.

    python -u manual_phase6_1_frames_test.py     # writes data/xai/frames_report.json

Frames of tomato and pepper in the open field, in the greenhouse, in the greenhouse with the climate controller and with the controller plus the crop's feedback (and in EnergyPlus when it is installed).
Needs the framework: pip install -e ../tsxai (https://github.com/farcasucam/tsxai). The data are synthetic; the exogenous weather is forcing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash, paired_frames  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, twin_series_source  # noqa: E402

CASES = (
    ("tomato", {"environment": "outdoor", "control": "off"}),
    ("tomato", {"environment": "greenhouse", "control": "off"}),
    ("pepper", {"environment": "greenhouse", "control": "on"}),
    ("pepper", {"environment": "greenhouse", "control": "on", "feedback": "on"}),
)


def build(source, simulator, crop, extra, length=168, start=480):
    labels = {"crop": crop, **extra}
    return source.frame(ScenarioDescriptor(labels, 1, start, length, simulator.scenario_options(labels, 1)))


def main() -> int:
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    rows = []
    for crop, extra in CASES:
        frame, again = build(source, simulator, crop, extra), build(source, simulator, crop, extra)
        assert frame.content_hash == again.content_hash, "a frame must be reproducible"
        view = frame.forecast_view(120, 48)
        roles = frame.catalogue.variables
        assert set(view.future_covariates) == {n for n in frame.series if roles[n].role == "known_future_covariate"}, "only known-future covariates may be exposed"
        assert view.past_time[-1] == frame.time[119] and view.future_time[0] == frame.time[120]
        assert "REAL_VERIFIED" not in frame.provenance.values()
        facts = [fact.to_dict() for fact in frame.quality()]
        rows.append({"crop": crop, "labels": extra, "samples": len(frame), "variables": len(frame.series), "frame_hash": frame.content_hash,
                     "future_covariates": sorted(view.future_covariates), "targets": sorted(view.truth), "data_quality": facts})
    labels = {"crop": "tomato", "environment": "greenhouse", "control": "off"}
    scenario = ScenarioDescriptor(labels, 1, 480, 168, simulator.scenario_options(labels, 1))
    pair = paired_frames(source, scenario, [Intervention("HEAT_WAVE", 48, 24, 8.0)])
    assert pair.first_changed_sample == 49, pair.first_changed_sample
    report = {"status": "PASS", "simulator": simulator.name, "rows": rows, "paired": {"first_changed_sample": pair.first_changed_sample, "baseline": pair.baseline.content_hash,
              "intervened": pair.intervened.content_hash}, "statement": "frames of the simulated twin: synthetic data, exogenous weather as forcing, no REAL_VERIFIED data", "report_hash": content_hash(rows)}
    out = ROOT / "data" / "xai" / "frames_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "PASS", "cases": len(rows), "report_hash": report["report_hash"], "quality_facts": sum(len(r["data_quality"]) for r in rows)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
