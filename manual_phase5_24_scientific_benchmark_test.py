"""Offline representative delivery check for Phase 5.24."""

from __future__ import annotations

from pathlib import Path

from agri_twin.application.scientific_benchmark import BenchmarkDefinition, ScientificBenchmarkSuite

ROOT = Path(__file__).resolve().parent


def main() -> None:
    suite = ScientificBenchmarkSuite(ROOT)
    definition = suite.default_definition()
    representative = BenchmarkDefinition("phase5_24_manual", (definition.cases[0], definition.cases[-1]))

    first = suite.run(representative)
    second = suite.run(representative)
    assert first.to_json() == second.to_json()
    assert first.summary.successful_cases == 2
    assert first.summary.valid_ensemble_members == 12
    assert first.summary.classification == "SYNTHETIC_SOFTWARE_BENCHMARK"
    assert all(result.sensitivity and result.uncertainty and result.ensemble for result in first.results)
    assert all(result.result_hash for result in first.results)
    paths = suite.write_artifacts(first, ROOT / "data" / "benchmarks" / "manual")
    assert all(path.exists() for path in paths)

    print("=" * 80)
    print("PHASE 5.24 MANUAL DELIVERY VERIFICATION")
    print("INTEGRATED SCIENTIFIC BENCHMARK FRAMEWORK READY")
    print(f"cases={first.summary.total_cases} successful={first.summary.successful_cases}")
    print(f"valid_ensemble_members={first.summary.valid_ensemble_members}")
    print(f"configuration_hash={first.configuration_hash[:16]}...")
    print("determinism=PASS")
    print("scenario_sensitivity_uncertainty_ensemble=PASS")
    print("REAL AGRONOMIC DATA NOT VERIFIED")
    print("CALIBRATION NOT PERFORMED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("=" * 80)


if __name__ == "__main__":
    main()
