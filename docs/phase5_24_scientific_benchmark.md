# Phase 5.24 - Integrated Scientific Benchmark & Reproducible Evaluation

## Objective

Phase 5.24 composes the existing scenario, sensitivity, uncertainty, ensemble and diagnostic contracts into one deterministic software benchmark. It measures what the Crop Digital Twin can demonstrate mechanically and keeps unknown agronomic claims explicit.

The benchmark does not perform calibration, optimization, data assimilation, ML/TimesFM, or experimental validation.

## Reused architecture

`ScientificBenchmarkSuite` is an orchestration layer only. It reuses:

- `ScenarioRunner` and `Scenario` for isolated scenario execution and simulated time;
- `ParameterRegistry` for parameter configuration identity;
- `ParameterSensitivityAnalyzer` for OAT and multivariable analysis;
- `ScenarioEnsembleGenerator` for seeded corners/grid/Monte Carlo uncertainty;
- the existing crop and greenhouse engines through `ScenarioRunner`;
- existing observation, alignment and diagnostics contracts when a verified observation dataset is explicitly supplied.

No second clock, scheduler, model engine, registry, sensitivity system or uncertainty system is introduced.

## Benchmark contracts

- `BenchmarkDefinition`: immutable benchmark case collection and configuration hash.
- `BenchmarkCase`: scenario, crop/variety, plot, cycle, environment, seed and ensemble settings.
- `BenchmarkRun`: reproducible result identity with simulation times, configuration/input/result hashes and status.
- `BenchmarkMetric`: metric value with an explicit `software_metric`, `scientific_metric`, or `robustness_metric` category.
- `BenchmarkComparison`: model versus persistence-style baseline, explicitly labelled `SYNTHETIC_SOFTWARE_BENCHMARK`.
- `BenchmarkSummary`: deterministic counts and matrix coverage.
- `ScientificBenchmarkReport`: serializable report with limitations and conservative scientific status.

## Matrix

The default definition covers all seven configured crops, outdoor and greenhouse environments, the four registered plots where applicable, known varieties (tomato RAF, pepper Lamuyo, grape Monastrell, plum Suplum 26), unspecified varieties without invented parameters, and three annual lettuce cycles. Additional representative tomato scenarios cover control, heat, drought, reduced radiation, high VPD, CO2, ventilation, recovery and combined stress.

Unregistered crop/plot combinations use `plot_id: null`; no plot is fabricated in the farm catalog.

## Reproducibility and hashes

All scientific times are fixed simulation timestamps. Result identity excludes process duration and wall-clock measurements. Hashes are computed from sorted JSON representations of:

- benchmark definition;
- scenario/model configuration;
- registry parameter configuration;
- input case and seed;
- scientific outputs and ensemble statistics.

Running the same definition twice produces equal serialized results, classifications, member counts and hashes. Runtime performance is intentionally not part of the scientific artifact.

## Metrics and interpretation

Software metrics describe deterministic execution and contract behavior. Robustness metrics describe valid/invalid ensemble members and convergence/failure classification. Scientific metrics are unavailable without a verified independent observation dataset. A synthetic model-versus-baseline difference is not a biological improvement claim.

Ensemble results include valid and invalid member counts, failures, mean, median, minimum, maximum, standard deviation and percentiles when members are available.

## EnergyPlus

EnergyPlus remains optional. The report records `ENERGYPLUS_AVAILABLE` or `ENERGYPLUS_UNAVAILABLE`; it is not treated as ground truth or as a prerequisite for the benchmark.

## Artifacts and verification

The deterministic artifact is written to `data/benchmarks/scientific_benchmark_report.json` with its scope note in `data/benchmarks/README.md`. Automated tests are in `tests/test_scientific_benchmark.py`, and the offline representative acceptance check is `manual_phase5_24_scientific_benchmark_test.py`.

## Scientific status and limitations

```text
PHASE 5.24 COMPLETE
INTEGRATED SCIENTIFIC BENCHMARK FRAMEWORK READY
SYNTHETIC SOFTWARE BENCHMARKS QUALIFIED
SYNTHETIC UNCERTAINTY / ENSEMBLE BENCHMARKS QUALIFIED
REAL AGRONOMIC DATA NOT VERIFIED
CALIBRATION NOT PERFORMED
EXPERIMENTAL VALIDATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

These benchmarks demonstrate software reproducibility, deterministic orchestration, explicit provenance and robustness handling. They do not demonstrate biological realism, parameter truth, field transferability, calibration quality or experimental validity.
