# Phase 5.29 — Integrated Synthetic Validation with Plausible Agronomic Scenarios

## Current Result and Scientific Stance

```text
PHASE 5.29 COMPLETE
INTEGRATED SYNTHETIC VALIDATION READY
SYNTHETIC MODEL CONSISTENCY QUALIFIED
TEMPORAL CONTINUITY QUALIFIED
PERSISTENT STATE CONSISTENCY QUALIFIED
MULTI-PLOT / MULTI-CYCLE CONSISTENCY QUALIFIED
GREENHOUSE-CROP INTEGRATION NOT QUALIFIED (open finding, see section 18)
ROBUSTNESS SCENARIOS QUALIFIED
REAL AGRICULTURAL DATA NOT VERIFIED (REAL_VERIFIED = 0)
SCIENTIFIC EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE
BIOLOGICAL VALIDITY NOT CLAIMED
FIELD ACCURACY NOT CLAIMED
CALIBRATION NOT PERFORMED
DATA ASSIMILATION NOT IMPLEMENTED
```

`SYNTHETIC MODEL CONSISTENCY QUALIFIED` means only that the implemented software
and model passed the synthetic checks defined in this phase.

## 1. Objective

Advance the project without waiting for real agronomic data by verifying the
integrated behaviour of the digital twin under plausible, traceable synthetic
scenarios: subsystem integration, temporal coherence, stress and recovery,
persistent state, multi-plot and multi-cycle isolation, outdoor and greenhouse
behaviour, invariants and determinism.

## 2. What synthetic validation means

The validation kind is `SYNTHETIC_INTEGRATED_VALIDATION`. Two families of checks
are kept separate in every case and metric (`ValidationCategory`):

- **Software consistency**: determinism, finiteness, time continuity, persistence,
  restart equivalence, absence of mutation, state integrity.
- **Mechanistic consistency**: expected responses of the *implemented* equations
  (PAR → APAR → potential growth, water deficit → water stress → growth, heat →
  temperature factor, ventilation/shading → microclimate → crop, senescence,
  monotonic maturity, post-harvest representation).

The pipeline is `fixed model → synthetic scenario → evaluation`. No parameter is
tuned, no calibrator or optimizer runs, and model outputs are never turned into
observations (no `model output → observation → validation` circularity).

## 3. What it does NOT demonstrate

## Scientific limitation

> Synthetic integrated validation qualifies software and model consistency under
> controlled scenarios. It does not establish biological validity, field
> validity, experimental accuracy, or transferability to real agricultural
> systems. Those claims require independent real observations and will be
> evaluated in the final scientific validation stage.

`PASS` never means "scientifically validated", "biologically validated" or
"field validated".

## 4. Architecture

`src/agri_twin/application/integrated_synthetic_validation.py` is an
orchestration/evaluation layer with no growth, photosynthesis, water, thermal,
VPD, CO2 or phenology equations. It reuses:

| Concern | Reused component |
| --- | --- |
| time | `SimulationClock` (via `ScenarioRunner`), `SimulationScheduler` (via `MultiPlotSimulation`) |
| integrated step | `CropDigitalTwinOrchestrator` (Phenology, GreenhouseMicroclimate, RadiationGrowth, WaterBalance, NutrientBalance, ClimateStress engines) |
| scenarios/events | `Scenario`, `ScenarioEvent`, `ScenarioRunner` |
| weather | seeded, timestamp-pure `WeatherEngine` through `SyntheticWeatherProvider` |
| greenhouse loop | `CropGreenhouseFeedbackLoop`, `SimplifiedGreenhouseModel`, `CropGrowthEngine` |
| optional backend | `EnergyPlusGreenhouseModel` / `detect_energyplus` |
| state | `TwinState`, `TwinSnapshot`, `InMemoryTwinStateRepository` |
| plots/cycles | `MultiPlotSimulation`, `SyntheticReferenceDatasetGenerator` plots and cycles |
| parameters | `ParameterRegistry`, `ParameterSet` (read only, fingerprinted) |
| robustness | Phase 5.22 12 physical cases via Phase 5.28 `TransferabilityRobustnessSuite.evaluate_robustness_suite` |
| transferability/readiness | `TransferabilityRobustnessSuite.readiness`, `audit_sources` (Phase 5.25/5.28) |

The only change to existing code is backward compatible: `ScenarioRunner`
accepts an optional `base_weather_factory`, so scenario events can be applied on
top of time-varying seeded weather instead of the constant `Scenario.base_weather`.
Without the factory the behaviour and all existing hashes are unchanged.

Structures: `SyntheticValidationScenario`, `SyntheticValidationCase`,
`SyntheticValidationResult`, `SyntheticValidationMetric`,
`SyntheticValidationIssue`, `SyntheticValidationReport`,
`IntegratedValidationSummary`. Every result records `case_id`, crop, variety,
plot, cycle, environment, scenario, start/end, timestep, expected invariants and
behaviours, observed outputs, metrics, status, warnings, failures, provenance, a
configuration hash and a full trajectory hash.

## 5. Scenarios

Hourly timestep. Synthetic climate profiles are scenario forcing, not crop
parameters: `warm_season` (12–30 °C, 900 W m-2) for tomato, pepper and the
perennial growing season; `cool_season` (7–21 °C, 650 W m-2) for lettuce, which
follows the winter/spring calendar of the Phase 5.9 synthetic cycles. Baseline
drip irrigation is 0.4 mm h-1.

| Kind | Event (existing `ScenarioEvent` types) | Checked behaviour |
| --- | --- | --- |
| `NORMAL_SEASON` | season irrigation | full stage sequence, maturity 1, harvest/post-harvest, biomass growth, post-harvest senescence |
| `WATER_STRESS_RECOVERY` | irrigation gap then irrigation | stress rises, growth falls, stress decreases after irrigation, gradual recovery, persistent biomass deficit |
| `HEAT_WAVE_RECOVERY` | `heat` +10 °C for 5 days | heat stress above existing `ClimateStressProfile.max_temp_c`, lower growth factor, heat damage decays |
| `LOW_RADIATION` | `low_radiation` ×0.3 | lower potential growth |
| `HIGH_RADIATION` | `high_radiation` ×1.4 (≤ 1400 W m-2) | higher potential growth; photoinhibition reported, actual growth not forced monotonic |
| `GREENHOUSE_VENTILATION` | `ventilation` 3 ACH | outdoor forcing unchanged, indoor RH down, VPD up, crop VPD stress follows |
| `GREENHOUSE_SHADING` | `shade` 50 % | indoor radiation exactly halved, lower potential growth |
| `GREENHOUSE_CO2` | `co2` +400 ppm | indoor CO2 up, returns after supply ends |
| `COMBINED_STRESS` | heat + deficit + high radiation + ventilation | valid states, growth below control |

Stress scenarios are paired with the `NORMAL_SEASON` control of the same crop and
environment; comparisons are controlled and isolated, never statistical causal
inference.

## 6. Invariants

Reusable `validate_trajectory` checks, each justified by the implemented code:
finite state; time continuity (`start + (i + 1) dt`); `0 ≤ LAI ≤ maximum_lai`;
non-decreasing total biomass (no explicit loss term; senescence moves leaf to
stem); maturity in [0, 1] and non-decreasing; non-decreasing stage (no
reactivated cycle); persistent `harvest_ready`; non-decreasing GDD and chilling;
`wilting_point ≤ VWC ≤ field_capacity`; growth factor in [0, 1] and actual ≤
potential growth; no growth during post-harvest; no GDD before perennial dormancy
release; microclimate RH/CO2/radiation contract. Unit tests inject violations
(biomass loss, NaN, time gap, stage regression) to prove detection.

## 7. Crops

All seven crops are covered: tomato, lettuce, pepper (annual; outdoor and
greenhouse) and grape, peach, plum, apple (perennial; outdoor). Greenhouse is
`NOT_APPLICABLE` for perennial crops, which the project configures as outdoor.

## 8. Varieties

RAF, Lamuyo, Monastrell and Suplum 26 are covered. The `ParameterRegistry` holds
only plot metadata for these varieties; every runtime engine uses species-level
profiles, so each case reports `SPECIES_FALLBACK` (engineering-default species
profile, future calibratable). No varietal coefficient was invented.

## 9. Outdoor and greenhouse

Outdoor: `WeatherState → CropDigitalTwinOrchestrator → state`. Greenhouse:
`WeatherState → GreenhouseMicroclimateEngine → microclimate → crop`. The actuator
causal-path check compares a 50 % shaded run under 800 W m-2 with an unshaded run
under 400 W m-2: identical microclimate yields an identical crop state, so the
actuator has no direct path to biomass. EnergyPlus is optional: without a runtime
and configured IDF/weather files the section is `NOT_APPLICABLE`; only the
adapter contract is checked with an explicitly labelled analytic fixture.

## 10. Temporal continuity

For three cases (tomato water stress, plum full perennial cycle, tomato greenhouse
CO2) the run is restored at 25 %, 50 % and 75 % of the season from a JSON
checkpoint of the full `CropGrowthState` and `SoilState`, then compared with the
continuous run at every later step. All nine checkpoints are exact
(`max_abs_difference = 0.0`, tolerance 1e-9 as `ENGINEERING_TEST_THRESHOLD`).

## 11. Persistence

Daily orchestrator snapshots are projected to `TwinState`, saved through
`TwinSnapshot` in an isolated `InMemoryTwinStateRepository`, read back and JSON
round-tripped. Persisted values equal computed values, re-saves are idempotent,
conflicting writes are rejected and `TwinState` is frozen. `TwinState` is an
observable projection and cannot serve as a restart checkpoint.

## 12. Multi-plot

Tomato (greenhouse), pepper and grape plots run for 30 days from one
`SimulationClock`/`SimulationScheduler` in `MultiPlotSimulation`. The combined run
equals each plot run alone, removing irrigation from one plot changes only that
plot, repeated runs are identical, and repository histories are isolated.

## 13. Multi-cycle

Lettuce `lettuce_001` and `lettuce_002` are stepped only within their dates, are
never reactivated after harvest, and the second cycle starts from a fresh initial
state (bitwise equal to an independent orchestrator). The plum campaign follows
`POST_HARVEST → ACTIVE → HARVEST_READY → POST_HARVEST`. A next-campaign restart is
`NOT_SUPPORTED` by the existing engines (no transition from
`post_harvest_dormancy` back to dormancy) and is recorded, not failed.

## 14. Robustness

The Phase 5.22 twelve physical robustness cases are reused through Phase 5.28 for
tomato in `GREENHOUSE` and `OUTDOOR`: 24/24 pass.

## 15. Determinism

Every case runs twice and full trajectory hashes are compared; two complete
report builds produce byte-identical JSON. No wall clock participates in
simulation or hashes; `time.perf_counter` durations are execution metadata only
and are excluded from the canonical artifact.

## 16. Metrics

Metrics are counts, fractions and differences with explicit definitions and units
(`steps_completed`, `valid_step_fraction`, invariant violation counts, behaviour
differences versus control, restart `max_abs_difference`, feedback convergence and
iterations). Software thresholds are labelled `ENGINEERING_TEST_THRESHOLD`
(gradual recovery ≥ 50 % of peak one day after irrigation, radiation ≤ 1400 W m-2,
restart tolerance 1e-9, indoor cooling review at 5 °C); none is a biological
threshold.

## 17. Results

Canonical artifact: `data/validation/integrated_synthetic_validation_report.json`
with `data/validation/integrated_synthetic_validation_README.md` (the directory's
`README.md` belongs to the Phase 5.25 validation report and is regenerated by it).

- 30 cases: 25 `PASS`, 5 `PASS_WITH_WARNINGS`, 0 failures.
- determinism, restart, persistence, multi-plot, invariants, robustness, static
  audit and mutation guard: `PASS`; multi-cycle: `PASS_WITH_WARNINGS`
  (next-campaign transition not supported); transferability: `DATA_INSUFFICIENT`.
- crop-greenhouse feedback: `INVARIANT_VIOLATION` in the closed-greenhouse run.

## 18. Limitations and open findings

| Code | Severity | Finding |
| --- | --- | --- |
| `INVARIANT_VIOLATION` (closed greenhouse) | FAILURE | In `CropGreenhouseFeedbackLoop` with 0 ACH, latent heat flux stays positive while indoor VPD = 0 (63 of 168 steps) and indoor air drifts up to ~33 °C below outdoor. `CropPhysicalExchangeModel` takes transpiration from `WaterBalanceEngine` without an indoor saturation limit, and `SimplifiedGreenhouseModel` has no infiltration/conduction path when closed. |
| `PLAUSIBILITY_REVIEW` | WARNING | With 0.3 ACH the indoor air is up to 8.8 °C below outdoor without a cooling actuator. |
| `GREENHOUSE_CONFIGURATION_VENTILATION_UNUSED` | WARNING | `GreenhouseConfiguration.ventilation_ach` is not read; heat loss is referenced to a fixed 20 °C. |
| `GREENHOUSE_TEMPERATURE_NOT_USED_BY_CROP` | WARNING | The orchestrator passes outdoor air temperature (with indoor radiation) to phenology, water balance and climate stress. |
| `CO2_NOT_CONSUMED_BY_ORCHESTRATOR_GROWTH` | WARNING | The orchestrator growth product has no CO2 factor; only the feedback loop applies one. |
| `DORMANCY_GROWTH_NOT_SUPPRESSED` | WARNING | Perennials gain biomass before dormancy release; dormancy only gates GDD. |
| `ORCHESTRATOR_GREENHOUSE_STEP_MEMORYLESS` | INFO | The orchestrator greenhouse step carries no thermal/CO2 memory between steps. |

None was "fixed" by tuning parameters or tests. Correcting the greenhouse and
orchestrator findings changes model equations and is a scientific decision left
for an explicit follow-up.

Other limitations: the synthetic weather has no seasonal trend (diurnal and
day-to-day variation only); perennial phases are mapped onto the generic
`establishment → vegetative_growth → yield_maturation → post_harvest_dormancy`
stages (flowering is not a distinct stage); all parameters are species-level
engineering approximations.

## 19. Future validation with real data

When independent real observations exist they will enter through the Phase 5.19
ingestion and 5.25 source audit (`REAL_VERIFIED`), followed by 5.26 calibration,
5.27 independent post-calibration validation and 5.28 transferability. This phase
does not anticipate that final block.

## Usage

```powershell
python -m pytest tests/test_integrated_synthetic_validation.py
python -u manual_phase5_29_integrated_synthetic_validation_test.py
```
