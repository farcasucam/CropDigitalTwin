"""Phase 6.3b: a development bank focused on the main context (greenhouse with the climate controller on, decisions D8-D11).

    python -u manual_phase6_3b_context_c_bank.py [N] [WORKERS]   # N scenarios sampled (default 90; the development partition is kept); writes data/xai/gctsb_c_dev/ and data/xai/gctsb_c_dev_report.json

The twin as a host of tsxai, with its factors restricted to the six exterior-forcing events (the explained object in this context is the controller's reaction to the exterior forcing), longer windows so that every
intervention has a week of context before it, and 2 to 4 interventions per scenario. Only the DEVELOPMENT partition is generated: the test partition is not touched before the freeze of the preregistration.
Scenarios are independent, so they are run in worker processes. Truth is the truth of the SIMULATED twin, whose crop model is not calibrated.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.bench import leakage_report, read_scenario, sample_scenarios, verify  # noqa: E402
from tsxai.bench.generator import FORMAT, ScenarioSpec, _write, run_scenario  # noqa: E402
from tsxai.core import content_hash  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, benchmark_design  # noqa: E402

EXTERIOR_FORCING = ("COLD_WAVE", "HEAT_WAVE", "LOW_RADIATION", "HIGH_RADIATION", "RAIN", "WIND")
SEED = 20261025
OUT = ROOT / "data" / "xai" / "gctsb_c_dev"


class FocusedTwin:
    """The twin, offering only the exterior-forcing factors and only the contexts of the main scenario (greenhouse, controller on). Everything else is delegated."""

    def __init__(self) -> None:
        self._twin = TwinSimulator()
        self.name = f"{self._twin.name}+focus-c"

    def catalogue(self):
        return self._twin.catalogue()

    def factors(self):
        return {name: spec for name, spec in self._twin.factors().items() if name in EXTERIOR_FORCING}

    def contexts(self):
        return [c for c in self._twin.contexts() if c.labels.get("environment") == "greenhouse" and c.labels.get("control") == "on"]

    def scenario_options(self, labels, season):
        return self._twin.scenario_options(labels, season)

    def run(self, scenario, interventions=()):
        return self._twin.run(scenario, interventions)


def _work(spec_document: dict) -> tuple[str, dict, float]:
    started = time.perf_counter()
    sim = FocusedTwin()
    spec = ScenarioSpec.from_dict(spec_document)
    record = run_scenario(sim, spec, sim.catalogue())
    _write(OUT / "scenarios" / f"{spec.scenario_id}.json.gz", record)
    return spec.scenario_id, {"id": spec.scenario_id, "group": spec.group, "split": spec.split, "labels": dict(spec.scenario.labels), "content_hash": record["content_hash"]}, time.perf_counter() - started


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    sim = FocusedTwin()
    base = benchmark_design()
    design = dataclasses.replace(base, window_days=(21, 28), interventions_per_scenario=(2, 4), duration_hours=(24, 72))
    specs = [s for s in sample_scenarios(sim, count, SEED, design) if s.split == "dev"]
    assert specs and all(s.split == "dev" for s in specs)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "scenarios").mkdir(parents=True)
    started = time.perf_counter()
    entries, seconds = [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for done, (scenario_id, entry, took) in enumerate(pool.map(_work, [s.to_dict() for s in specs]), 1):
            entries.append(entry)
            seconds.append(took)
            print(f"{done}/{len(specs)} {scenario_id} {entry['labels'].get('crop')} feedback={entry['labels'].get('feedback', 'off')} {took:.0f}s", flush=True)
    catalogue = sim.catalogue()
    manifest = {"format": FORMAT, "simulator": sim.name, "baseline_label": "c-bank-dev-1", "design_hash": design.content_hash, "catalogue_hash": catalogue.content_hash, "count": len(entries),
                "splits": {"dev": len(entries), "test": 0}, "scenarios": sorted(entries, key=lambda e: e["id"])}
    manifest["manifest_hash"] = content_hash({key: value for key, value in manifest.items() if key != "manifest_hash"})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    assert verify(OUT) == []
    leak = leakage_report(manifest)
    assert leak["status"] == "PASS", leak
    composition = {"factors": {}, "interventions": 0, "contexts": {}}
    for entry in manifest["scenarios"]:
        record = read_scenario(OUT / "scenarios" / f"{entry['id']}.json.gz")
        key = f"{record['spec']['labels']['crop']}|feedback={record['spec']['labels'].get('feedback', 'off')}"
        composition["contexts"][key] = composition["contexts"].get(key, 0) + 1
        for item in record["spec"]["interventions"]:
            composition["factors"][item["factor"]] = composition["factors"].get(item["factor"], 0) + 1
            composition["interventions"] += 1
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report = {"status": "PASS", "simulator": sim.name, "twin_git_head": head, "sampled": count, "kept_dev": len(entries), "manifest_hash": manifest["manifest_hash"], "design_hash": design.content_hash,
              "design": {"window_days": list(design.window_days), "interventions_per_scenario": list(design.interventions_per_scenario), "duration_hours": list(design.duration_hours), "seasons": design.seasons},
              "factors_offered": list(sim.factors()), "composition": composition, "leakage": leak, "seconds_total": round(time.perf_counter() - started, 1), "seconds_per_scenario_mean": round(sum(seconds) / len(seconds), 1),
              "statement": "development bank of the main context; truth is that of the SIMULATED twin (uncalibrated crop model); the test partition was not generated"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k not in ("statement", "seconds_total", "seconds_per_scenario_mean")})
    (ROOT / "data" / "xai" / "gctsb_c_dev_report.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("kept_dev", "manifest_hash", "composition", "seconds_total")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
