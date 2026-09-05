"""Offline delivery audit for Phase 4.7.6 nutrient availability."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import CropGrowthState, FertilizationRequest, NutrientBalanceEngine


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def state(**changes) -> CropGrowthState:
    values = dict(simulation_time=T0, crop_key="tomato", variety="unspecified", current_stage="vegetative_growth", nutrient_reserve_kg_ha=200.0, nutrient_available_kg_ha=50.0)
    values.update(changes)
    return CropGrowthState(**values)


def main() -> int:
    checks: list[tuple[str, str, str]] = []

    def run(name: str, function) -> None:
        try:
            checks.append((name, "PASS", str(function() or "verified")))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def contract() -> str:
        payload = json.loads((ROOT / "src" / "growth_model_config.json").read_text(encoding="utf-8"))
        model = payload["nutrient_model"]
        require(model["activation_status"] == "CONTRACT_ONLY", "nutrient model was activated")
        require(model["evidence_status"] == "ENGINEERING_APPROXIMATION" and model["requires_calibration"], "baseline status is not explicit")
        require(set(model["crop_profiles"]) == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}, "seven crop coverage is incomplete")
        return "reduced N baseline and calibration contract validate"

    def availability() -> str:
        engine = NutrientBalanceEngine()
        deficit = engine.advance(state(nutrient_available_kg_ha=0), growth_potential_g_m2=20, dt_seconds=86400)
        recovered = engine.advance(deficit.state, growth_potential_g_m2=0, dt_seconds=86400, fertilization=FertilizationRequest(100, 0.8, "manual"))
        require(deficit.nutrient_factor == 0 and recovered.nutrient_available_kg_ha > deficit.nutrient_available_kg_ha, "deficit/recovery behavior is invalid")
        require(0 <= recovered.nutrient_status <= 1 and 0 <= recovered.nutrient_stress <= 1, "nutrient indices exceed bounds")
        return "deficit, fertilization recovery and continuous factor validate"

    def growth_and_determinism() -> str:
        engine = NutrientBalanceEngine()
        first = engine.advance(state(), growth_potential_g_m2=25, dt_seconds=30 * 86400)
        second = engine.advance(state(), growth_potential_g_m2=25, dt_seconds=30 * 86400)
        require(first == second, "accelerated nutrient step is not deterministic")
        require(first.growth_actual_g_m2 == first.growth_potential_g_m2 * first.nutrient_factor, "growth limitation is not multiplicative")
        return "phase-aware extraction and large-step determinism validate"

    def separation() -> str:
        source = (ROOT / "src" / "agri_twin" / "domain" / "nutrient_balance.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source, "nutrient model reads real time")
        require("WeatherEngine" not in source and "WaterBalanceEngine" not in source, "nutrient model owns another subsystem")
        return "fertilization remains an input; no clock or controller was added"

    run("Nutrient configuration contract", contract)
    run("Availability and recovery", availability)
    run("Growth limitation and determinism", growth_and_determinism)
    run("Responsibility separation", separation)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.6 NUTRIENT BALANCE")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.6 STATUS: " + ("NUTRIENT CORE READY - CALIBRATION PENDING" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())