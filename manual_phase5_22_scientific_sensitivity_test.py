"""Manual delivery verification script for Phase 5.22.

Demonstrates:
- Deterministic baseline execution
- Parameter sensitivity perturbation (OAT negative & positive)
- Output deltas and sensitivity score calculation
- Zero-mutation verification of ParameterRegistry
- Annual (tomato) and Perennial (grape) evaluations
- Greenhouse and Outdoor physical evaluations
- Multivariable coupling analysis
- Robustness across 12 stress cases
- Explicit uncertainty propagation with deterministic bounds and reproducible Monte Carlo
- Synthetic provenance tracking
- Final conservative scientific banner
"""

from __future__ import annotations

import json
from pathlib import Path

from agri_twin.application.sensitivity import (
    ParameterSensitivityAnalyzer,
    RangeSourceType,
    SensitivityClassification,
    UncertaintyStatus,
)
from agri_twin.domain.parameter_audit import ParameterRegistry

ROOT = Path(__file__).resolve().parent


def main() -> None:
    print("=" * 80)
    print("PHASE 5.22 MANUAL DELIVERY VERIFICATION")
    print("Scientific Sensitivity, Robustness & Uncertainty Analysis")
    print("=" * 80)

    # 1. Initialize registry and analyzer
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    print(f"\n[1] ParameterRegistry loaded: {len(registry.records)} parameters audited.")

    # 2. Baseline and OAT sensitivity on representative parameter (radiation.rue)
    rec = registry.get("radiation.rue")
    baseline_val = rec.value
    neg, pos = analyzer.analyze_oat("radiation.rue", crop="tomato", perturbation_percent=10.0)

    print("\n[2] One-At-A-Time (OAT) Sensitivity on 'radiation.rue':")
    print(f"    Baseline value: {baseline_val:.4f} {rec.unit}")
    print(f"    Negative (-10%): perturbed={neg.perturbed_value:.4f}, output={neg.perturbed_output:.4f} (baseline={neg.baseline_output:.4f}, change={neg.absolute_change:.4f}, S_norm={neg.normalized_sensitivity:.4f}, class={neg.classification.value})")
    print(f"    Positive (+10%): perturbed={pos.perturbed_value:.4f}, output={pos.perturbed_output:.4f} (baseline={pos.baseline_output:.4f}, change={pos.absolute_change:.4f}, S_norm={pos.normalized_sensitivity:.4f}, class={pos.classification.value})")
    print(f"    Confounder groups: {list(pos.confounders)}")
    print(f"    Provenance: {pos.provenance}")

    assert neg.baseline_output > 0
    assert pos.perturbed_output != pos.baseline_output
    assert pos.provenance == "SIMULATED_REAL_DATA_SUBSTITUTE"

    # 3. Annual vs Perennial representative cases
    print("\n[3] Annual vs Perennial Crop Evaluations:")
    annual_res = analyzer.analyze_parameter("radiation.rue", crop="tomato", variety="RAF", environment="GREENHOUSE")
    print(f"    Annual (Tomato/RAF in GREENHOUSE): output={annual_res.perturbed_output:.4f}, classification={annual_res.classification.value}")

    perennial_res = analyzer.analyze_parameter("radiation.rue", crop="grape", variety="Monastrell", environment="OUTDOOR")
    print(f"    Perennial (Grape/Monastrell in OUTDOOR): output={perennial_res.perturbed_output:.4f}, classification={perennial_res.classification.value}")

    # 4. Greenhouse vs Outdoor evaluation
    print("\n[4] Greenhouse Microclimate Feedback vs Outdoor Evaluation:")
    gh_res = analyzer.analyze_parameter("greenhouse.cover_transmission", environment="GREENHOUSE")
    print(f"    Greenhouse (cover transmission): observable={gh_res.observable}, baseline={gh_res.baseline_output:.2f}, perturbed={gh_res.perturbed_output:.2f}, S_norm={gh_res.normalized_sensitivity:.4f}")

    # 5. Multivariable interaction analysis
    print("\n[5] Multivariable Coupled Analysis (RUE x Extinction Coefficient):")
    multi = analyzer.analyze_multivariable(("radiation.rue", "radiation.extinction_coefficient"), crop="tomato")
    print(f"    Interaction delta: {multi['interaction_delta']:.6f} (non-additive coupling: {multi['has_non_additive_coupling']})")
    print(f"    Warning: {multi['confounder_warning']}")

    # 6. Robustness evaluation across 12 cases
    print("\n[6] Robustness Analysis Across 12 Physical Stress Cases:")
    robustness_results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    all_passed = all(r.passed for r in robustness_results)
    for r in robustness_results:
        status_str = "PASS" if r.passed else "FAIL"
        print(f"    [{status_str}] {r.case_id:28s}: {r.description} (numerical_stability={r.numerical_stability}, feedback_converged={r.feedback_converged})")
    assert all_passed, "Not all robustness cases passed!"

    # 7. Uncertainty propagation (deterministic & Monte Carlo)
    print("\n[7] Uncertainty Propagation on 'radiation.rue':")
    uncert = analyzer.propagate_uncertainty("radiation.rue", crop="tomato", monte_carlo=True, seed=42, num_samples=30)
    print(f"    Range source: {uncert.range_source_type.value}, status={uncert.uncertainty_status.value}")
    print(f"    Nominal={uncert.nominal_value:.4f} -> output={uncert.nominal_output:.4f}")
    print(f"    Low={uncert.low_value:.4f} -> output={uncert.low_output:.4f}")
    print(f"    High={uncert.high_value:.4f} -> output={uncert.high_output:.4f}")
    print(f"    Output spread: {uncert.output_spread:.4f} ({uncert.output_spread_percent:.2f}%)")
    print(f"    Monte Carlo quantiles: p10={uncert.monte_carlo_quantiles['p10']:.4f}, p50={uncert.monte_carlo_quantiles['p50']:.4f}, p90={uncert.monte_carlo_quantiles['p90']:.4f}, std={uncert.monte_carlo_quantiles['std']:.4f}")

    # 8. Zero-mutation check
    rec_after = registry.get("radiation.rue")
    assert rec_after.value == baseline_val, "ParameterRegistry was mutated!"
    print("\n[8] Zero-mutation check passed: ParameterRegistry was not modified.")

    # 9. Full report generation & benchmark
    print("\n[9] Full Analysis Benchmark & Materialization:")
    report = analyzer.run_full_analysis(crops=("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"))
    bm = report.computational_benchmark
    print(f"    Total simulations: {bm['total_simulations']}")
    print(f"    Elapsed wall-clock: {bm['elapsed_wall_clock_seconds']:.4f} s")
    print(f"    Simulations/second: {bm['simulations_per_second']:.2f}")
    print(f"    Report ID: {report.report_id}")
    print(f"    Config hash: {report.configuration_hash[:16]}...")

    # 10. Conservative scientific banner
    print("\n" + "=" * 80)
    print("PHASE 5.22 COMPLETE")
    print("SCIENTIFIC SENSITIVITY / ROBUSTNESS / UNCERTAINTY FRAMEWORK READY")
    print("SYNTHETIC SENSITIVITY QUALIFIED")
    print("REAL AGRONOMIC DATA NOT VERIFIED")
    print("CALIBRATION NOT PERFORMED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("=" * 80)


if __name__ == "__main__":
    main()
