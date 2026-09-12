# Phase 5.23 - Scientific Uncertainty & Scenario Ensemble Framework

## 1. Objective and scope

Phase 5.23 adds an explicit uncertainty-definition and scenario-ensemble layer on top of the existing sensitivity and scenario contracts. It is intended to answer:

> How do explicitly documented parameter ranges affect reproducible synthetic scenario outputs?

It does not estimate agronomic truth, fit parameters, assimilate observations, or validate the model against field measurements.

## 2. Scientific status

```text
SOFTWARE READY
SYNTHETIC DATA AVAILABLE
SYNTHETIC UNCERTAINTY ENSEMBLE QUALIFIED
REAL AGRONOMIC DATA NOT VERIFIED
CALIBRATION NOT PERFORMED
EXPERIMENTAL VALIDATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

Every generated ensemble is labelled `SIMULATED_REAL_DATA_SUBSTITUTE`. Unknown ranges remain `UNCERTAINTY_NOT_SPECIFIED`; the generator does not fabricate a confidence interval for them.

## 3. Reused architecture

The implementation is in `agri_twin.application.uncertainty_ensemble` and reuses the existing `ParameterRegistry` and synthetic-data provenance contract. It does not create a second observation system, parameter registry, calibration path, or validation path.

### Contracts

- `UncertaintyDefinition`: immutable nominal value, bounds, source, provenance, distribution, and documentation status.
- `UncertaintySource`: explicit source classification such as scientific, measured, engineering, synthetic, or unknown.
- `UncertaintyDistribution`: bounded, uniform, normal, log-normal, empirical, or unspecified semantics.
- `EnsembleMember`: immutable member identifier, parameter realizations, outputs, validity, and seed.
- `ScenarioEnsemble`: reproducible member collection, summary, provenance, and configuration hash.
- `ScenarioEnsembleGenerator`: deterministic `corners`, `grid`, and seeded `monte_carlo` generation.

## 4. Sampling semantics

- `corners`: evaluates low, nominal, and high values for each requested parameter independently.
- `grid`: produces deterministic low/mid/high level selections within the requested member budget.
- `monte_carlo`: uses a local `random.Random(seed)` instance, so global random state and the registry remain unchanged.
- Missing or unknown uncertainty: uses the nominal value only and preserves `UNCERTAINTY_NOT_SPECIFIED`.

The current ensemble outputs are deterministic synthetic response proxies. They are suitable for contract, reproducibility, and software robustness checks, not for agronomic prediction claims.

## 5. Reporting and reproducibility

`build_report()` includes:

- ensemble summary and serialized members;
- seed, method, crop, and configuration hash;
- valid and failed member counts;
- explicit real-data, calibration, validation, and assimilation status;
- limitations concerning structural uncertainty and engineering assumptions.

Repeated generation with the same registry, inputs, method, and seed produces identical serialized output.

## 6. Limitations and non-decisions

1. No real agronomic dataset has been verified.
2. No calibration or optimization is performed.
3. No experimental validation is claimed.
4. Structural model uncertainty is not quantified by this phase.
5. Unknown uncertainty is reported, not invented.
6. Ensemble spread is not parameter identifiability and cannot resolve confounding.

## 7. Verification

Automated coverage is provided by `tests/test_uncertainty_ensemble.py`. The offline delivery check is `manual_phase5_23_uncertainty_ensemble_test.py`.
