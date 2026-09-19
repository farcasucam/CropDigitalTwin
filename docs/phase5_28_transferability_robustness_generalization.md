# Phase 5.28 — Transferability, Robustness and Scientific Generalization

## Current Result and Scientific Stance

The repository remains on the strict, conservative scientific stance:

```text
PHASE 5.28 COMPLETE
TRANSFERABILITY PIPELINE READY
ROBUSTNESS PIPELINE READY
GENERALIZATION PIPELINE READY
SCIENTIFIC TRANSFERABILITY NOT ASSESSED — INSUFFICIENT REAL DATA
SYNTHETIC TRANSFERABILITY TESTS QUALIFIED AS SOFTWARE TESTS ONLY
REAL AGRICULTURAL DATA NOT VERIFIED
BIOLOGICAL ROBUSTNESS NOT CLAIMED
EXPERIMENTAL GENERALIZATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

The source audit confirms `real_data_verified = 0`. No `REAL_VERIFIED` agronomic observations exist in the codebase, and Phase 5.26 reports `calibration_performed = false`. Consequently, no scientific transferability or biological generalization is claimed.

All transferability cases and scenario sweeps executed on synthetic fixtures operate strictly under the `QUALIFIED_SYNTHETIC` and `SOFTWARE_TEST_ONLY` contracts.

---

## 1. Transferability Architecture

The `TransferabilityRobustnessSuite` provides an evaluation and orchestration layer across multi-dimensional contexts without introducing secondary physiological engines or duplicate clock authorities.

### 1.1 Evaluated Dimensions

1. **Temporal / Cycle Transfer (`TEMPORAL_CYCLE`)**: Evaluates model transfer between independent growing cycles (e.g., season-to-season, year-to-year).
2. **Spatial / Plot Transfer (`SPATIAL_PLOT`)**: Evaluates transfer from a calibration plot to an independent plot with potentially distinct soil, micro-topography, or configuration.
3. **Varietal Transfer (`VARIETAL`)**: Tests transfer between distinct cultivars (e.g., tomato RAF vs Marmande, pepper Lamuyo).
4. **Environmental Transfer (`ENVIRONMENTAL`)**: Evaluates transfer across production systems (`OUTDOOR` ↔ `GREENHOUSE`).
5. **Climatic Transfer (`CLIMATIC`)**: Tests response under altered weather regimes (heat, frost, high/low VPD, extreme radiation).
6. **Agronomic Management Transfer (`AGRONOMIC_MANAGEMENT`)**: Evaluates response across irrigation, soil, and nutrient management variations.
7. **Cross-Species Transfer (`CROSS_SPECIES`)**: Explicitly flags any attempt to apply crop-specific parameter sets across distinct botanical species (e.g., tomato → pepper).

### 1.2 Transferability Levels

- **Level 0**: `LEVEL_0_SAME_CONTEXT` (baseline / reference context).
- **Level 1**: `LEVEL_1_NEW_TIME_CYCLE` (same plot/variety, new cycle).
- **Level 2**: `LEVEL_2_NEW_PLOT` (same variety/cycle, new plot).
- **Level 3**: `LEVEL_3_NEW_VARIETY` (same species/plot, new variety).
- **Level 4**: `LEVEL_4_NEW_ENVIRONMENT` (outdoor ↔ greenhouse).
- **Level 5**: `LEVEL_5_NEW_CROP_SPECIES` (cross-species transfer).

---

## 2. Robustness Framework

Robustness evaluation separates software numerical stability from biological robustness:

- **Parametric Robustness**: Perturbations within allowed parameter bounds.
- **Input Forcing Robustness**: Evaluates model stability under extreme environmental forcing (temperature -10 °C to 55 °C, solar radiation up to 1500 W/m², extreme VPD, saturation, wilting point soil water).
- **Scenario Stress Robustness**: Reuses the 12 physical robustness cases from `ParameterSensitivityAnalyzer`, verifying physical bounds, numerical finiteness, and feedback loop convergence.
- **Uncertainty Ensemble Propagation**: Integrates with `ScenarioEnsembleGenerator` for deterministic Monte Carlo and corner sampling without fabricating measured uncertainty.

---

## 3. Generalization & Diagnostic Signals

### 3.1 Baseline vs Calibrated Comparison

When evaluated on independent target datasets, the suite compares baseline parameters against calibrated parameters to assess whether calibration improves, maintains, or degrades performance outside the calibration domain.

### 3.2 Overfit & Context Dependence Diagnostics

- **`POTENTIAL_OVERFIT`**: Triggered when a parameter set exhibits improved fit on the calibration source dataset but degraded fit on the independent target holdout.
- **`POTENTIAL_CONTEXT_DEPENDENCE`**: Triggered when performance significantly degrades upon transferring across plots or environments.

Both signals are descriptive diagnostic indicators and are not treated as definitive causal proof.

---

## 4. Independence and Leakage Prevention

All transferability assessments enforce strict dataset independence via `ValidationIndependence`. If source and target datasets share observation identifiers, overlapping records, or concurrent timestamps, `DATA_LEAKAGE` is raised and scientific evaluation is blocked.

---

## 5. Artifacts and Verification

- **Module**: `src/agri_twin/application/transferability_robustness.py`
- **Unit & Integration Tests**: `tests/test_transferability_robustness.py` (18 passed)
- **Manual Verification**: `manual_phase5_28_transferability_robustness_test.py`
- **Canonical JSON Report**: `data/transferability/transferability_robustness_report.json`
- **Artifact Readme**: `data/transferability/README.md`
- **Configuration Hash**: Deterministic SHA-256 hash excluding machine paths and timestamps.

