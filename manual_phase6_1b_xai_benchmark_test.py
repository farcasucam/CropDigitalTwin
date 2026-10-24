"""Phase 6.1b verification: the twin, as a host of tsxai, builds a small deterministic benchmark with exactly known truth.

    python -u manual_phase6_1b_xai_benchmark_test.py [N]     # N scenarios (default 12); writes data/xai/gctsb_pilot/ and data/xai/gctsb_pilot_report.json

Needs the framework: pip install -e ../tsxai (https://github.com/farcasucam/tsxai). A pilot only; measured cost about 15 s per scenario on the development machine.
Truth is the truth of the SIMULATED twin, whose crop model is not calibrated.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.bench import generate, leakage_report, read_scenario, sample_scenarios, verify  # noqa: E402
from tsxai.core import content_hash  # noqa: E402
from tsxai.testing import check_simulator  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, benchmark_design  # noqa: E402


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    sim, design = TwinSimulator(), benchmark_design()
    problems = check_simulator(sim)
    assert problems == [], problems
    specs = sample_scenarios(sim, count, 20261024, design)
    out = ROOT / "data" / "xai" / "gctsb_pilot"
    if out.exists():
        shutil.rmtree(out)
    started = time.perf_counter()
    manifest = generate(sim, specs, out, design, baseline_label="pilot")
    seconds = time.perf_counter() - started
    assert verify(out) == []
    leak = leakage_report(manifest)
    assert leak["status"] == "PASS", leak
    rows = []
    for entry in manifest["scenarios"]:
        record = read_scenario(out / "scenarios" / f"{entry['id']}.json.gz")
        rows.append({"id": entry["id"], "labels": record["spec"]["labels"], "split": entry["split"], "content_hash": entry["content_hash"]})
    report = {"status": "PASS", "scenarios": count, "manifest_hash": manifest["manifest_hash"], "splits": manifest["splits"], "leakage": leak, "rows": rows,
              "simulator": sim.name, "statement": "pilot of a benchmark whose truth is the truth of the simulated twin (uncalibrated crop model)", "report_hash": content_hash(rows)}
    (ROOT / "data" / "xai" / "gctsb_pilot_report.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "PASS", "scenarios": count, "manifest_hash": manifest["manifest_hash"], "splits": manifest["splits"], "seconds_per_scenario": round(seconds / count, 2)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
