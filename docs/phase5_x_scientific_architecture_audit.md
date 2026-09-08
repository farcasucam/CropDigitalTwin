# Transversal scientific architecture audit: Phases 5.1-5.7.4

## 1. Scope

This audit checks the existing Phase 5.1 scientific parameter audit, 5.2
calibration framework, 5.3 validation framework, 5.4 scenarios, 5.5
crop/variety calibration protocol, 5.6 crop growth, and 5.7.1-5.7.4 greenhouse
work. It does not add calibration, experimental validation, prediction, or
EnergyPlus benchmarking.

## 2. Initial commit

The repository state audited was commit `59785c39cbfdf3de3b967913fcb74326e3381c7d`
(`feat(greenhouse_feedback): enhance documentation and tests for CO2 and
thermal dynamics in greenhouse model`). The requested reference commit
`48164f7b9730a8f7cc8b556be44aaaa4dbaf211` is an ancestor, not the current HEAD.
The initial worktree was clean.

## 3. Baseline

`python -m pytest`: **450 passed, 0 failed, 12 skipped**, 7.09 seconds.
`git diff --check`: PASS. The skips are the existing optional eppy/IDD tests.
The working tree had no source changes at baseline. Pytest-generated `.pyc`
files are present/versioned in this repository and are identified as generated
artifacts rather than scientific inputs.

## 4. Architecture map

```text
ParameterRegistry
      -> crop/farm/growth configuration and evidence
WeatherState + SimulationClock/Scheduler
      -> GreenhousePhysicalModel
      -> MicroclimateState
      -> CropGrowthEngine
      -> CropPhysicalExchange / CropMicroclimateFeedback
      -> GreenhousePhysicalModel fixed-point evaluation
      -> ScenarioRunner or calibration/validation runner
```

The producer/consumer boundaries are explicit:

| Boundary | Producer | Consumer | Units/sign/time |
|---|---|---|---|
| parameters | `ParameterRegistry` and typed configuration | engines | parameter-specific; provenance and status recorded |
| forcing | `WeatherState` | greenhouse/crop/water | weather rates at one explicit timestep |
| radiation | `RadiationGrowthEngine` | crop growth | PAR/APAR energy, positive input |
| stress | `ClimateStressEngine` | `CropGrowthEngine` | bounded factors 0..1 |
| water | `WaterBalanceEngine` | orchestrator/exchange | soil state and interval mm; evaluation is pure |
| microclimate | greenhouse backend | crop growth/exchange | temperature, RH, VPD, radiation, CO2 |
| crop exchange | `CropPhysicalExchangeModel` | greenhouse | fluxes/increments with explicit signs |
| calibration | `GridSearchCalibrator` | `CalibrationResult` | calibration dataset only |
| validation | `ValidationEngine` | `ValidationResult` | independent dataset or explicit insufficiency |
| scenarios | `ScenarioRunner` | synthetic scenario snapshots | injected simulation clock and reproducible hash |

No second clock, scheduler, parameter registry, calibration engine, water
engine, VPD engine, stress engine, or phenology engine was found.

## 5. Parameter audit

`ParameterRegistry` enforces unique IDs, units, ranges, source/evidence,
calibration status, calibration permission, crop/stage scope, and observational
requirements. Literature records require references. Calibrated records require
both calibrated source and status. Current crop configuration values are mostly
unknown or engineering defaults, and phenology evidence remains unactivated.

The audit now registers the effective 5.7.4 engineering defaults in the same
registry: thermal exchange area, latent heat, sensible coefficient, leaf-air
proxy, carbon fraction, air density, air volume, and fixed-point relaxation.
They remain `engineering_default`, low/no evidence, and candidates for future
calibration. No new registry was created.

## 6. Growth audit

The chain is `PAR -> APAR -> RUE potential -> climate/water/nutrient/CO2 factors
-> actual growth -> partitioned biomass/LAI -> senescence/damage/maturity`.
`RadiationGrowthEngine` owns the Beer-Lambert/RUE biomass update. `ClimateStressEngine`
owns bounded environmental factors and damage. `CropGrowthEngine` is a facade
that calculates the reported APAR/potential/actual values and delegates the
state biomass update to the radiation engine. The repeated APAR expression is a
reported calculation matching the delegated engine, not a second state update.

The feedback fixed-point uses the same initial crop state in every iteration;
it does not commit growth repeatedly. Radiation, RUE, temperature, water, VPD,
nutrients, and CO2 are each applied through their existing boundary once per
crop evaluation.

## 7. Water audit

`WaterBalanceEngine` computes ET0 from solar radiation, temperature, a fixed
engineering temperature-range approximation, timestep, LAI/canopy factor, crop
stage, soil storage, precipitation, and irrigation. Its current transpiration
path does **not** use VPD. The feedback layer converts its interval
`transpiration_mm` into `mm h-1` and deliberately applies no second VPD
multiplier.

The fixed-point passes the original soil state to every exchange evaluation.
`WaterBalanceEngine` is pure and returns a new soil state; it is not committed
inside the iteration. The humidity conversion in the simplified greenhouse is
an engineering approximation, not a complete psychrometric balance.

## 8. VPD audit

| Component | Use | Type | Applied twice? |
|---|---|---|---|
| `ClimateStressEngine` | yes | bounded VPD growth factor/stress | no |
| `WaterBalanceEngine` | no | no VPD physiology in current ET path | no |
| `CropGrowthEngine` | via climate result | growth factor | no |
| feedback loop with soil | diagnostic/input state | converts WaterBalance rate only | no |
| feedback fallback without soil | yes | engineering canopy-demand approximation | no second soil correction |
| greenhouse backend | derives VPD | microclimate output | not a growth factor |

The fallback canopy demand uses VPD explicitly and is documented as an
engineering default. A calibrated VPD-to-transpiration physiology is not
claimed.

## 9. Greenhouse audit

`GreenhousePhysicalModel` is the common contract. `SimplifiedGreenhouseModel`
implements the deterministic lumped model. `EnergyPlusGreenhouseModel` is an
optional adapter using the EnergyPlus Python API boundary. `EppyGreenhouseBuilder`
only creates/validates IDF variants and is not a dynamic simulation engine.
EnergyPlus/eppy remain optional and unavailable in the baseline environment;
the core suite does not depend on them. EnergyPlus does not own the clock and
is not treated as ground truth. Unverified EnergyPlus actuator handles are not
invented.

## 10. Crop-greenhouse feedback audit

The loop is:

`microclimate_n -> CropGrowthEngine -> CropPhysicalExchange -> greenhouse -> candidate -> relaxation`.

Channels are explicit: radiation and LAI, transpiration `mm h-1`, latent and
sensible heat `W m-2`, and CO2 uptake `ppm timestep-1`. Positive sensible heat
warms; positive latent heat cools; transpiration adds bounded humidity; uptake
reduces CO2; intercepted radiation drives crop growth.

## 11. CO2 audit

The simplified balance is:

`CO2_candidate = CO2_previous + supply + ventilation_fraction * (420 - CO2_previous) - uptake`.

Supply and uptake are concentration increments/decrements for one external
Digital Twin timestep, not absolute concentrations or mass flow rates. The
previous state is used, ventilation depends on the previous concentration, and
fixed-point iterations use the timestep-start state. The candidate is returned
once for the caller to commit.

## 12. Thermal audit

The crop thermal term is:

`Q_crop = (sensible_heat_w_m2 - latent_heat_w_m2) * thermal_exchange_area_m2`.

`W m-2 * m2 = W`, and the temperature contribution uses `Q * dt / (thermal_mass_kj_k * 1000)`.
The default `thermal_exchange_area_m2=1.0` is a provisional engineering
normalization because the zone thermal mass and surface flux do not currently
come from a measured site geometry. It is not calibrated or measured. The
manual/test audit demonstrates latent cooling and sensible warming with no
iteration accumulation.

## 13. Temporal audit

`SimulationClock` is the only simulated-time owner and `SimulationScheduler`
drives scheduled work. The domain engines receive explicit timestamps and
`dt_seconds`. Fixed-point iterations do not advance time. `datetime.now()`
occurs only in message-envelope and weather-acquisition metadata, not in
simulation dynamics. No `sleep()` or `time.time()` was found in simulation code.

## 14. Calibration/validation audit

Calibration uses `CalibrationCase`, a calibration-role dataset, `ParameterSet`,
`GridSearchCalibrator`, comparator and `CalibrationResult`. Validation uses an
independent-role `ValidationCase`, alignment/comparator, metrics and
`ValidationResult`. Validation rejects calibration datasets; in-sample and
insufficient-data states are explicit. Synthetic framework tests do not
constitute scientific validation.

## 15. Crop/variety data readiness

The supported crop set is tomato, lettuce, pepper, grape, peach, plum and apple.
Project varieties include tomato/RAF, pepper/Lamuyo, grape/Monastrell and
plum/Suplum 26. Variety names are configuration scope, not variety-specific
calibration. RUE, SLA, LAI limits, stress thresholds, phenology and yield values
remain engineering/literature priors or candidates for calibration. The
repository has no sufficient local observations to claim crop/variety
calibration. Phenology evidence is retained as literature evidence and remains
not activated.

## 16. Scientific maturity matrix

| Capability | Implemented | Traceable | Calibrated | Validated | Real data |
|---|---|---|---|---|---|
| Radiation interception | YES | YES | NO | NO | INSUFFICIENT_DATA |
| Biomass/RUE/LAI | YES | YES | NO | NO | INSUFFICIENT_DATA |
| Water balance | YES | YES | NO | NO | INSUFFICIENT_DATA |
| VPD/temperature stress | YES | YES | NO | NO | INSUFFICIENT_DATA |
| Nutrient factor | YES | PARTIAL | NO | NO | INSUFFICIENT_DATA |
| CO2 exchange | PARTIAL | YES | NO | NO | INSUFFICIENT_DATA |
| Greenhouse climate | YES | PARTIAL | NO | NO | INSUFFICIENT_DATA |
| Crop-greenhouse feedback | YES | YES | NO | NO | INSUFFICIENT_DATA |
| Phenology | PARTIAL | YES | NO | NO | INSUFFICIENT_DATA |
| Yield | PARTIAL | PARTIAL | NO | NO | INSUFFICIENT_DATA |
| Variety calibration | PARTIAL | YES | NO | NO | INSUFFICIENT_DATA |
| EnergyPlus backend | PARTIAL | YES | NO | NO | INSUFFICIENT_DATA |
| Prediction/ML | NO | NO | NO | NO | INSUFFICIENT_DATA |

## 17. Problems found

### A — Scientific errors

No new formula/sign error was found in the audited current state. The test
claiming direct soil-path VPD response was scientifically misleading and was
corrected before this audit close; the implementation correctly has no second
VPD correction.

### B — Architectural contradictions

None found. The existing backends, clocks, registries and calibration/validation
frameworks preserve their boundaries.

### C — Traceability insufficiencies

The effective feedback engineering defaults were previously absent from the
central registry. They are now registered with units, source detail, engineering
source type, low/none evidence, and candidate-for-calibration status.

### D — Correctly declared simplifications

The lumped greenhouse model, humidity conversion, leaf-air sensible proxy,
CO2 concentration proxy, WaterBalance ET approximation, and EnergyPlus optional
boundary are explicitly simplified or pending calibration. These were retained.

### E — Obsolete documentation

The 5.7.4 documentation was incomplete about the explicit humidity limitation
and CO2 increment semantics. It is updated in this audit.

## 18. Corrections applied

- Added the effective 5.7.4 defaults to `ParameterRegistry._code_defaults`.
- Updated 5.7.4 documentation with CO2 temporal semantics, humidity limitation,
  and audited VPD semantics.
- Added the compact cross-phase manual audit.
- Added this audit report and updated `PHASES.md`.
- No new physical engine, calibrator, registry, clock, or EnergyPlus dependency
  was introduced.

## 19. Follow-up items

Bugs: none remaining from this audit.

Improvements deliberately deferred: a psychrometric humidity balance; measured
canopy/zone exchange area; calibrated VPD-to-transpiration physiology; measured
leaf temperature and canopy energy balance; site CO2 mass-flow actuators;
EnergyPlus runtime integration with verified actuator handles; independent
experimental validation; parameter fitting and uncertainty propagation;
systematic Simplified-versus-EnergyPlus benchmarks; ML/predictive models.

## 20. Tests

Before changes: 450 passed, 0 failed, 12 skipped in 7.09 seconds.
Focused audit tests: `python -m pytest tests/test_parameter_audit.py
tests/test_crop_greenhouse_feedback.py tests/test_greenhouse_physical_model.py
tests/test_water_balance.py tests/test_crop_growth.py`.
Final full regression and focused results are reported with the delivery of
this audit. Optional skips remain tied to eppy/IDD availability.

## 21. Manual verification

`manual_phase5_x_scientific_audit.py` prints the temporal chain, registry
provenance summary, temperature, radiation, APAR, growth, LAI, transpiration,
VPD, humidity, latent/sensible heat, CO2, fixed-point diagnostics, backend,
calibration/validation status, and the synthetic-output disclaimer.

## 22. Final scientific status

**MECHANISTIC SIMPLIFIED MODEL — NOT CALIBRATED / NOT EXPERIMENTALLY VALIDATED**

The system is structurally prepared for future calibration and validation but
is not ready for productive agronomic prediction. No synthetic value in this
report is an observation.
