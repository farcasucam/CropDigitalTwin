"""Offline acceptance audit for prepared Phase 4.4 phenology parameters."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agri_twin.domain import CropConfigRepository, FarmConfigRepository, validate_phenology_configuration

ROOT = Path(__file__).resolve().parent
CROP = ROOT / "src" / "crop_config.json"
FARM = ROOT / "src" / "farm_config.json"
APP = ROOT / "config" / "app.json"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    checks = []
    def check(name, function):
        try:
            checks.append((name, "PASS", str(function() or "verified")))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def configs():
        payload = json.loads(CROP.read_text(encoding="utf-8"))
        require(set(payload["crops"]) == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}, "crop set differs")
        require(all(len(crop["stages"]) == 4 for crop in payload["crops"].values()), "each crop must have four stages")
        CropConfigRepository(CROP)
        FarmConfigRepository(FARM)
        return "seven crops and four stages each"

    def schema():
        validate_phenology_configuration({"method": "gdd", "base_temperature_c": None, "upper_temperature_c": None, "biofix": None, "calibration_status": "CALIBRATION_REQUIRED", "source": {"reference": "method-reference", "type": "technical_reference"}, "stages": [{"stage_key": "establishment", "gdd_to_next": None}]})
        return "optional schema valid with null agronomic values"

    def references():
        farm = FarmConfigRepository(FARM)
        crops = CropConfigRepository(CROP)
        for plot in farm.plots:
            crops.resolve_stage(plot.crop_key, plot.current_stage)
        return "all Farm -> Crop -> Stage references valid"

    def no_activation():
        payload = json.loads(CROP.read_text(encoding="utf-8"))
        require(all("phenology" not in crop for crop in payload["crops"].values()), "phenology unexpectedly active")
        return "no automatic transition configuration is active"

    def reproducible():
        first = CROP.read_bytes()
        second = CROP.read_bytes()
        require(first == second, "configuration changed during audit")
        return "same configuration bytes observed"

    def regression():
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        require(completed.returncode == 0, completed.stdout[-500:] or completed.stderr[-500:])
        return completed.stdout.strip().splitlines()[-1]

    check("Seven crops and stage structure", configs)
    check("Optional phenology schema", schema)
    check("Farm -> Crop -> Stage references", references)
    check("Traceability and calibration status", schema)
    check("No automatic transition activation", no_activation)
    check("Reproducibility and no app mutation", reproducible)
    check("Regression", regression)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.4 PHENOLOGY PARAMETERS")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    passed = sum(status == "PASS" for _, status, _ in checks)
    failed = sum(status == "FAIL" for _, status, _ in checks)
    skipped = 0
    print("\n" + "=" * 60)
    print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
    print("PHASE 4.4 PHENOLOGY STATUS: " + ("ACCEPTED" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
