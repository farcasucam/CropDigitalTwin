# Phase 5.31 — Greenhouse-Crop Physical Benchmark and Energy-Balance Consistency

## Current Result and Scientific Stance

```text
PHASE 5.31 COMPLETE
GREENHOUSE PHYSICAL BENCHMARKS QUALIFIED
GREENHOUSE ENERGY-BALANCE SOFTWARE CONSISTENCY QUALIFIED
MICROCLIMATE TRANSFER QUALIFIED
VENTILATION / HUMIDITY / CO2 RELATIONSHIPS QUALIFIED
GREENHOUSE-CROP FEEDBACK PHYSICALLY CONSISTENT UNDER SYNTHETIC BENCHMARKS
DETERMINISTIC REPLAY QUALIFIED
REAL AGRICULTURAL DATA NOT VERIFIED
CALIBRATION NOT PERFORMED
EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE
BIOLOGICAL VALIDITY NOT CLAIMED
FIELD ACCURACY NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

**"QUALIFIED" means only that the implementation passes the synthetic physical
benchmarks defined in this phase. It is not validation against a real greenhouse.**

## 1. Objective

Demonstrate, with reproducible analytical benchmarks and controlled cases, that
the physical relations implemented by the greenhouse-crop model after Phase 5.30
are internally coherent, without real agronomic data, calibration or new
equations.

## 2. Baseline

Phase 5.30 baseline: **731 passed, 12 skipped, 0 failed**. The Phase 5.31
baseline run at HEAD `6f55074` (clean tree, Python 3.13.9) reproduced it; the
later redundant notification of Phase 5.30 was not treated as a second run.

## 3. Architecture under test

`src/agri_twin/application/greenhouse_physical_benchmark.py`
(`GreenhousePhysicalBenchmarkSuite`) only calls existing components:
`SimplifiedGreenhouseModel`, `CropPhysicalExchangeModel`,
`CropGreenhouseFeedbackLoop`, `CropGrowthEngine`, `RadiationGrowthEngine`,
`ClimateStressEngine`, `WaterBalanceEngine`, `CropDigitalTwinOrchestrator`,
`ScenarioRunner`/`SimulationClock` and `ParameterRegistry`. It contains no energy,
humidity, VPD, CO2 or growth equation. Expected values are closed-form special
cases of the relations already implemented (sealed adiabatic box, pure decay,
translation invariance, exact transmission products, analytic equilibria), never
fitted numbers.

Each case separates **software correctness** (determinism, units, single paths,
state persistence) from **physical consistency** (energy, ventilation,
humidity/VPD, latent flux, radiation, CO2). Biological validity and experimental
validation are out of scope and remain unclaimed.

## 4. Relations used (all pre-existing, Phase 5.30)

```text
C dT/dt = Q + G (T_out − T),   G = heat_loss_w_k + ρ c_p V ACH/3600
ρ_v, CO2:  dX/dt = S + k (X_out − X),  k = ACH/3600   (exact over dt)
I_in = I_out × solar_transmission × (1 − shading)
E ≤ Δρ_v × air_volume / Δt  (0 at VPD = 0),   λE = E λ / 3600
potential growth = PAR(I_crop) × (1 − e^(−k LAI)) × RUE
CO2 factor = CropGrowthEngine.co2_response(CO2) = min(1, CO2 / 420)
```

## 5. Benchmarks (47 cases)

| Group | Cases | Expected relation |
| --- | --- | --- |
| Energy (A, B) | identical ambient; radiation energy closure; exchange sign; linearity in ΔT; no hidden reference temperature; thermal half-life; outdoor-temperature monotonicity | no drift without sources; `C ΔT = I_in A Δt` in a sealed adiabatic box; sign of `T_out − T_in`; doubling ΔT doubles the change; translation invariant across 20 °C; difference halves after `ln2·C/G` |
| Ventilation (C) | exchanged fraction; T, vapour, CO2 toward outdoor; configured + actuator ACH; no direct biomass path | fraction `1 − e^(−ACH Δt/3600)`; monotonic approach to outdoor, none at 0 ACH; additive ACH; unchanged microclimate ⇒ unchanged crop |
| Humidity/VPD | RH/VPD bounds (dry, humid, saturated grid); sealed-air vapour conservation; condensation bound; **5.29 closed saturated greenhouse regression**; no double VPD correction; VPD in kPa | RH ∈ [0,100], VPD ≥ 0 and 0 at saturation; vapour gain = transpired mass; RH = 100 after cooling; 0 latent steps at VPD = 0; one VPD ramp |
| Latent | no crop; crop without transpiration (night); dry-air cooling applied once; saturated air; capacity monotonicity | no flux without canopy or demand; `λE = Eλ/3600` and `ΔT = −λE A Δt / C`; no cooling at VPD = 0; flux non-decreasing with capacity, bounded by demand |
| Radiation | cover transmission; shading; zero radiation; single path to crop | exact transmission products; no growth in the dark; potential growth from indoor radiation, applied once |
| CO2 | sealed bookkeeping; ventilated equilibrium; supply monotonicity; crop uptake; single path to growth | ±exact increments; `C_out + S/k`; more supply ⇒ more CO2; canopy lowers CO2; one response, double input rejected |
| Crop microclimate | outdoor temperature; greenhouse temperature; greenhouse RH/VPD/radiation/CO2, no rain | outdoor: crop = WeatherState; greenhouse: crop = indoor microclimate |
| Feedback | none; thermal, latent, CO2 isolated; relaxation once; only converged state persists; combined convergence/determinism | exact reproduction without exchanges; each term changes only its balance; one blend per iteration; loop and backend hold the converged state; converged, replayed, no oscillation |
| Determinism, units, mutation | scenario replay; heating kW→J; misting mm→kg; no mutation | identical trajectories; `ΔT = 3.6e6 / C`; 0.36 kg evaporated; registry/config/state unchanged |

Invariant validators run over every evaluated state (461 microclimate states,
400 crop states): finite values, VPD ≥ 0, RH range, radiation ≥ 0, CO2 ≥ 0,
biomass ≥ 0, LAI ≥ 0, maturity ∈ [0, 1].

## 6. Issues found and corrected (demonstrated by a failing benchmark first)

| Classification | Finding | Correction |
| --- | --- | --- |
| `SOFTWARE_BUG` | `feedback.only_converged_state_persists` failed: after a loop step the greenhouse backend cache (`SimplifiedGreenhouseModel.state()`) held the last unconverged candidate | `GreenhousePhysicalModel.commit(state)`; the loop commits the converged state; regression test `test_backend_commit_regression` |
| `TRACEABILITY_GAP` | `volume_m3`, `ventilation_ach`, `heat_loss_w_k`, `thermal_mass_kj_k`, `co2_ppm_baseline` are physically active since 5.30 but were not in `ParameterRegistry` | registered as `engineering_default`, `candidate_for_calibration` (values unchanged) |
| `TRACEABILITY_GAP` | the Tetens saturation vapour pressure was duplicated inline in 9 places (`greenhouse.py` environment builders, `climate_stress.py`, feedback loop, EnergyPlus adapter, Phase 3 `physical.py`) | all use `greenhouse.saturation_vapour_pressure_kpa` / `vapour_pressure_deficit_kpa`; the static audit now requires a single definition |
| `SCENARIO_DESIGN_ISSUE` (benchmark) | `feedback.none` first compared with exact equality; the relaxation blend `αx + (1−α)x` differs from `x` by 1 ulp | comparison at 1e-12 relative plus an explicit all-exchanges-zero check |

No physical equation or parameter value changed; the psychrometric refactor is
the same expression (bitwise identical results; the EnergyPlus adapter moved from
`pow(e, x)` to `math.exp(x)`). No `OPEN_PHYSICAL_ISSUE` remains.

## 7. Parameters

All 16 parameters exercised by the benchmark are traced to `ParameterRegistry`
with matching values and none is `calibrated`: greenhouse volume, cover
transmission, ventilation ACH, cover conductance, thermal mass, exchange area,
CO2 baseline, air density, air specific heat, latent heat, water-vapour gas
constant, outdoor CO2, CO2 response reference, feedback air volume, relaxation
factor, leaf sensible-heat coefficient. Engineering values remain
`engineering_default`; physical constants are `fixed`.

## 8. EnergyPlus

`UNAVAILABLE` in this environment. The optional backend tests remain skipped and
the phase does not depend on it; EnergyPlus is never ground truth.

## 9. Determinism

No wall clock, sleep or network participates (static audit). Two complete builds
produce byte-identical JSON; the scenario replay and the 48 h feedback runs hash
identically. The artifact contains no wall-clock data.

## 10. Tests and artifacts

- `tests/test_greenhouse_physical_benchmark.py`: 56 tests (energy, ventilation,
  humidity/VPD, latent, radiation, CO2, crop microclimate, feedback, determinism,
  units, mutation, traceability, static audit, EnergyPlus, scientific stance).
- `manual_phase5_31_greenhouse_physical_benchmark_test.py`: representative subset;
  exit 0 only if every mandatory benchmark passes.
- `data/benchmarks/greenhouse_physical_benchmark_report.json` and
  `greenhouse_physical_benchmark_README.md`: cases, inputs, outputs, expected and
  actual relations, status, per-case hashes, registry and configuration hashes,
  test count, EnergyPlus availability and limitations.

## 11. What is demonstrated

Internal physical consistency of the implemented greenhouse-crop chain under
controlled synthetic cases: energy closure and correct exchange signs, ventilation
effects, bounded humidity/VPD with no evaporation into saturated air, single
radiation, VPD and CO2 paths, the crop consuming the indoor microclimate, a
convergent deterministic feedback loop, and parameter traceability.

## 12. What is NOT demonstrated

That any magnitude matches a real greenhouse; biological validity; field accuracy;
calibrated parameters; transferability. The default geometry (1000 m3 with a 1 m2
exchange area) is an engineering placeholder, only directions and closures are
benchmarked, and the limitations of Phase 5.30 (lumped air, no longwave exchange,
condensation without latent release, capped CO2 response) still apply.

## Usage

```powershell
python -m pytest tests/test_greenhouse_physical_benchmark.py
python -u manual_phase5_31_greenhouse_physical_benchmark_test.py
```
