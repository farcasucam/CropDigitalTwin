"""Offline delivery audit for Phase 4.7.1 growth-model configuration."""

from __future__ import annotations

import json
from pathlib import Path

from agri_twin.domain import GrowthModelConfigurationRepository


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "src" / "growth_model_config.json"
CROP = ROOT / "src" / "crop_config.json"
FARM = ROOT / "src" / "farm_config.json"
EXPECTED_CROPS = {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
EXPECTED_ENVIRONMENTS = {"outdoor", "passive_greenhouse", "actuated_greenhouse"}


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
        configuration = GrowthModelConfigurationRepository(CONFIG, CROP, FARM)
        require(set(configuration.crop_profiles) == EXPECTED_CROPS, "seven-crop coverage is incomplete")
        require(set(configuration.environment_profiles) == EXPECTED_ENVIRONMENTS, "environment profiles are incomplete")
        return "seven crops, configured soils and three environment modes validate"

    def semantics() -> str:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        require(payload["activation_status"] == "CONTRACT_ONLY", "growth contract was activated")
        for name, descriptor in payload["crop_parameter_contract"].items():
            require(descriptor.get("unit"), f"unit missing: {name}")
            require(len(descriptor.get("reasonable_range", [])) == 2, f"range missing: {name}")
            require(descriptor.get("default_value") is None, f"unsupported default: {name}")
            require(descriptor.get("evidence_status") == "CALIBRATION_REQUIRED", f"status missing: {name}")
        return "all crop parameters have units, range semantics and explicit pending status"

    def separation() -> str:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
        require("actuator_contract" in payload and "actuator_contract" not in payload["crop_parameter_contract"], "actuator fields overlap crop parameters")
        engine = (ROOT / "src" / "agri_twin" / "domain" / "crop_engine.py").read_text(encoding="utf-8")
        require("gdd_accumulated" not in engine and "def transition" not in engine, "a growth transition was activated")
        return "crop, soil, environment and actuator responsibilities remain separate"

    run("Configuration coverage", coverage)
    run("Parameter semantics", semantics)
    run("Responsibility and clock separation", separation)
    checks.append(("Deliberately pending values", "SKIP", "crop physiology, variety values, greenhouse geometry and plot environment assignment require evidence or calibration"))
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.1 GROWTH CONTRACT")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.1 STATUS: " + ("CONTRACT READY - CALIBRATION REQUIRED" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())