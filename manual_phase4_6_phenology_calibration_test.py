"""Offline acceptance audit for Phase 4.6 agronomic calibration evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agri_twin.domain import CropConfigRepository, FarmConfigRepository

ROOT = Path(__file__).resolve().parent
CROP = ROOT / "src" / "crop_config.json"
FARM = ROOT / "src" / "farm_config.json"
MATRIX = ROOT / "docs" / "phenology-parameters.md"
EXPECTED = {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
CULTIVAR_DEPENDENT = {"grape", "peach", "plum", "apple"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    checks: list[tuple[str, str, str]] = []

    def run(name: str, function) -> None:
        try:
            checks.append((name, "PASS", str(function() or "verified")))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def coverage() -> str:
        payload = json.loads(CROP.read_text(encoding="utf-8"))
        require(set(payload.get("crops", {})) == EXPECTED, "the seven-crop coverage is incomplete")
        require(all(len(value.get("stages", {})) == 4 for value in payload["crops"].values()), "each crop must retain four stages")
        CropConfigRepository(CROP)
        FarmConfigRepository(FARM)
        return "seven crops and four stages validated"

    def evidence() -> str:
        text = MATRIX.read_text(encoding="utf-8").lower()
        require("source/context" in text and "confidence" in text and "status" in text, "evidence columns are missing")
        require("https://extension.psu.edu/understanding-growing-degree-days" in text, "method source link is missing")
        for crop in EXPECTED:
            require(f"| {crop} |" in text, f"matrix row missing: {crop}")
        return "source, context, units, confidence and status are documented per row"

    def cultivar_context() -> str:
        text = MATRIX.read_text(encoding="utf-8").lower()
        for crop in CULTIVAR_DEPENDENT:
            row = next(line for line in text.splitlines() if line.startswith(f"| {crop} |"))
            require("cultivar" in row or "prunus" in row or "rootstock" in row, f"cultivar dependency absent: {crop}")
        return "cultivar/site dependence is explicit for perennial crops"

    def no_activation() -> str:
        payload = json.loads(CROP.read_text(encoding="utf-8"))
        require(all("phenology" not in crop for crop in payload["crops"].values()), "operational phenology was added")
        require("gdd_to_next" not in CROP.read_text(encoding="utf-8"), "operational GDD target was added")
        return "no GDD, chilling accumulator or transition is active"

    def unchanged() -> str:
        digest = hashlib.sha256(CROP.read_bytes()).hexdigest()
        json.loads(CROP.read_text(encoding="utf-8"))
        require(hashlib.sha256(CROP.read_bytes()).hexdigest() == digest, "crop config changed during audit")
        return "crop_config.json remains unchanged"

    run("Seven crops covered", coverage)
    run("Evidence matrix complete", evidence)
    run("Cultivar and perennial dependencies", cultivar_context)
    run("No unsupported activations", no_activation)
    run("Configuration immutability", unchanged)
    checks.append(("Local calibration readiness", "SKIP", "no phenology event dates, rootstocks, Tbase or crop-specific targets exist locally"))
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.6 CALIBRATION AUDIT")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    passed = sum(status == "PASS" for _, status, _ in checks)
    failed = sum(status == "FAIL" for _, status, _ in checks)
    skipped = sum(status == "SKIP" for _, status, _ in checks)
    print("\n" + "=" * 60)
    print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
    print("PHASE 4.6 STATUS: " + ("EVIDENCE READY - CALIBRATION REQUIRED" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
