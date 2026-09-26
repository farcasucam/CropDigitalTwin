# Phase 5.30 — Greenhouse-Crop Physical Corrections and Microclimate Consistency

## Current Result and Scientific Stance

```text
PHASE 5.30 COMPLETE
GREENHOUSE PHYSICAL CONSISTENCY CORRECTED
GREENHOUSE-CROP INTEGRATION SYNTHETICALLY QUALIFIED
MICROCLIMATE-TO-CROP COUPLING SYNTHETICALLY QUALIFIED
TEMPORAL CONSISTENCY PRESERVED
FEEDBACK LOOP SYNTHETICALLY QUALIFIED
DORMANCY / PHENOLOGY CONSISTENCY QUALIFIED
REAL AGRICULTURAL DATA NOT VERIFIED (REAL_VERIFIED = 0)
SCIENTIFIC EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE
BIOLOGICAL VALIDITY NOT CLAIMED
FIELD ACCURACY NOT CLAIMED
CALIBRATION NOT PERFORMED
DATA ASSIMILATION NOT IMPLEMENTED
```

> The corrections in Phase 5.30 address internal physical consistency defects
> identified by synthetic integrated validation. They are not calibration and do
> not establish biological or experimental validity.

No parameter value was tuned. Every correction replaces an inconsistent
mechanism with a dimensionally consistent one that uses the parameters that
already existed; the only new named values are two physical constants and two
previously hard-coded 420 ppm values, all registered in `ParameterRegistry`.

## 1. Defects detected by Phase 5.29 (and by the 5.30 audit)

| # | Defect | Where |
| --- | --- | --- |
| 1 | Latent heat flux > 0 while indoor VPD = 0 (63 steps, closed greenhouse); indoor air drifted 33 °C below outdoor | `CropPhysicalExchangeModel`, `SimplifiedGreenhouseModel` |
| 2 | `GreenhouseConfiguration.ventilation_ach` never read; air exchange only via actuator ratio against a profile normaliser | `SimplifiedGreenhouseModel._compute_state` |
| 3 | Heat loss referenced to a fixed 20 °C (`weather.T − 20`, clipped ±10 K) instead of indoor − outdoor | `SimplifiedGreenhouseModel._compute_state` |
| 4 | Crop given outdoor temperature/RH (only radiation was indoor) in greenhouse; phenology used outdoor temperature | `CropDigitalTwinOrchestrator` |
| 5 | CO2 affected growth only in the feedback loop (inline `co2 / 420`); the orchestrator ignored it | `CropGreenhouseFeedbackLoop._grow`, orchestrator |
| 6 | Perennials gained biomass during endodormancy | `RadiationGrowthEngine`, `CropGrowthEngine` |
| 7 | Outdoor bypass reported `vpd_kpa = 0.0`, so outdoor crops in the orchestrator never had VPD stress | `SimplifiedGreenhouseModel` (outdoor mode) |
| 8 | Outdoor rain reached the greenhouse soil water balance | orchestrator |
| 9 | Misting lowered humidity (`transpiration − misting`) | `SimplifiedGreenhouseModel` |
| 10 | Transpiration computed from outdoor weather, not the microclimate | `CropPhysicalExchangeModel` |
| 11 | Feedback iteration 1 integrated from the already advanced candidate (`prior=current`), later ones from it too: double integration within a step | `CropGreenhouseFeedbackLoop.step` |
| 12 | Orchestrator greenhouse step reset to outdoor air each step (no prior), so `thermal_mass_kj_k` had no effect | orchestrator |
| 13 | RH mixed linearly in RH space plus an arbitrary `−10 % × ventilation ratio` drying term and a `×4` conversion | `SimplifiedGreenhouseModel` |

## 2. Corrections and equations

### 2.1 Lumped, well-mixed greenhouse (`SimplifiedGreenhouseModel._compute_state`)

Every balance is a linear first-order ODE integrated **exactly** over `dt`
(unconditionally stable, no overshoot for any step):

```text
dX/dt = S + k (X_out − X)            k = ACH / 3600   [s-1]
X(dt) = X_eq + (X0 − X_eq) e^(−k dt),   X_eq = X_out + S / k      (k > 0)
X(dt) = X0 + S dt                                                 (k = 0)
ACH   = GreenhouseConfiguration.ventilation_ach + actuator ventilation_ach
ventilation_fraction = 1 − e^(−ACH dt / 3600)   (air fraction exchanged in the step)
```

**Energy** (`C dT/dt = Q + G (T_out − T)`):

```text
C = thermal_mass_kj_k × 1000                                 [J K-1]
G = heat_loss_w_k + ρ_air c_p V ACH / 3600                   [W K-1]
Q = I_in A + 1000 (heating_kw − cooling_kw) + (H_crop − λE_crop) A − λ E_mist / dt   [W]
I_in = I_out × solar_transmission × (1 − shading)            [W m-2]
A = thermal_exchange_area_m2,  V = volume_m3
```

The exchange term has the sign of `T_out − T`: equal temperatures exchange
nothing, a warmer interior loses heat, a colder one gains heat, and a closed
greenhouse (0 ACH) still couples to outdoor through `heat_loss_w_k`.

**Water vapour** (density ρ_v, kg m-3), mixing on vapour content, not RH:

```text
ρ_v,sat(T) = e_s(T) [Pa] / (R_v (T + 273.15)),   e_s = Tetens (project formula)
S_v = (E_crop A / 3600 + E_mist / dt) / V
ρ_v ≤ ρ_v,sat(T_new)   (excess condenses);   RH = 100 ρ_v / ρ_v,sat(T_new)
```

Misting evaporates at most the start-of-step vapour deficit of the air volume,
humidifies the air and removes its latent heat (defect 9).

**CO2** (ppm): the same exchange toward `OUTDOOR_CO2_PPM`, with supply and crop
uptake as per-timestep increments, exactly as their contracts state.

**Outdoor mode**: unchanged bypass, but VPD is now `e_s (1 − RH/100)` (defect 7).

### 2.2 Saturation-consistent transpiration (`CropPhysicalExchangeModel`)

Demand is still `WaterBalanceEngine` transpiration (no second VPD correction),
now evaluated with the **indoor** microclimate (defect 10). Mass conservation
caps the flux to what the air can take up in one step:

```text
E ≤ Δρ_v × air_volume_m3 / Δt_h,   Δρ_v = VPD [Pa] / (R_v T_K)   [mm h-1]
λE = E × λ / 3600                                                [W m-2]
```

At VPD = 0 transpiration and latent heat are exactly zero (defect 1).

### 2.3 The crop consumes the microclimate (`CropDigitalTwinOrchestrator`)

- Outdoor: crop environment = `WeatherState`.
- Greenhouse: crop environment = indoor air temperature, RH, radiation and
  pressure, with **no rain** (defects 4, 8); phenology, water balance, radiation
  growth and climate stress all use it. `CropGrowthEngine` does not know about
  greenhouses: the dependency is resolved in the integration layer.
- The greenhouse microclimate is persistent orchestrator state carried between
  steps (defect 12). Snapshots add `outdoor_weather` and `co2_factor`.
- `Scenario.initial_microclimate` (optional; hashed only when set) allows exact
  restarts from a checkpoint that includes the microclimate.

### 2.4 One CO2 pathway

`CropGrowthEngine.co2_response(co2_ppm) = min(1, CO2 / CO2_REFERENCE_PPM)` is the
single responsibility for the CO2 growth effect (the same response previously
inline in the feedback loop). `CropGrowthInput.co2_ppm` feeds it; supplying both
`co2_ppm` and an explicit `co2_factor` raises `CropGrowthError` (no double
application). The feedback loop passes the microclimate CO2; the orchestrator
multiplies its limitation product by the same function (defect 5).

### 2.5 Dormancy

`PhenologyEngine.endodormant(state)` (dormancy not released by chilling) and
`PhenologyEngine.growth_active(state)` are the single definitions. During
endodormancy `RadiationGrowthEngine` returns the state unchanged and
`CropGrowthEngine` freezes growth, LAI and maturity (defect 6). Chilling
accumulation, release and GDD forcing are unchanged. The model has no distinct
budburst stage: growth becomes possible at chilling release and the first GDD
stage target (`establishment → vegetative_growth`) marks leaf-out.

### 2.6 Feedback loop

Every iteration integrates the greenhouse from the same start-of-step state
(explicit `prior`, else the last converged state, else outdoor air at the
configured CO2 baseline); relaxation and independent tolerances are unchanged;
only the converged state (`last_converged`) is carried to the next timestep
(defect 11).

## 3. Units

| Quantity | Unit | Note |
| --- | --- | --- |
| temperature | °C (K offset 273.15 only inside ρ_v) | |
| RH | % | |
| VPD | kPa (Pa inside ρ_v) | explicit ×1000 |
| radiation | W m-2 | |
| CO2 | ppm; supply/uptake ppm per timestep | contract unchanged |
| ventilation | ACH (h-1) → k = ACH/3600 s-1 | explicit |
| heating/cooling | kW → W (×1000) | explicit |
| crop sensible/latent | W m-2 × A → W | |
| transpiration/misting | mm h-1 = kg m-2 h-1 | ×A/3600 → kg s-1 |
| thermal mass | kJ K-1 → J K-1 (×1000) | explicit |
| timestep | s | |

## 4. Parameters

Reused, unchanged: `volume_m3`, `solar_transmission`, `ventilation_ach`,
`heat_loss_w_k` (cover conductance), `thermal_mass_kj_k`,
`thermal_exchange_area_m2`, `co2_ppm_baseline`, feedback `air_volume_m3`,
`latent_heat_j_kg`, `air_density_kg_m3`.

Registered in `ParameterRegistry` (`_code_defaults`):

| parameter_id | value | status |
| --- | --- | --- |
| `physics.air_specific_heat` | 1013 J kg-1 K-1 | literature (FAO-56), `fixed`, not calibratable |
| `physics.water_vapour_gas_constant` | 461.5 J kg-1 K-1 | literature (standard), `fixed`, not calibratable |
| `greenhouse.outdoor_co2` | 420 ppm | engineering default (previously hard-coded) |
| `crop.co2_response_reference` | 420 ppm | engineering default (previously hard-coded) |

Air density (1.2 kg m-3) and latent heat (2.45 MJ kg-1) are now single module
constants in `greenhouse.py` also used as feedback-configuration defaults.

## 5. What was not modified

RUE, SLA, extinction coefficient, Tbase/Tupper, GDD targets, chilling
requirements, stress thresholds, Kc/ET formulation, soil parameters, greenhouse
parameter values, the MicroclimateState/actuator contracts, the EnergyPlus
backend, the phenology state machine and the CO2 response shape.

## 6. Tests

- `tests/test_greenhouse_physical_corrections.py` — 41 tests: saturation, VPD
  zero, high RH, ACH on T/vapour/CO2, zero ventilation, exact exchange fraction,
  configured ventilation, thermal exchange signs and reference, large-step
  stability, outdoor heat, misting, outdoor VPD, condensation bound, indoor
  temperature/RH/VPD/radiation/CO2 consumed by the crop, no indoor rain,
  persistent orchestrator greenhouse state, CO2 levels and single application,
  dormancy gating, chilling → release → forcing → leaf-out, iteration start
  state, converged-state carry-over, convergence at 0/0.3/3 ACH, no NaN/Inf,
  registry traceability, no parameter/TwinState mutation, determinism, no
  parallel physical systems.
- Two existing tests encoded the defective behaviour and were corrected with
  justification: ventilation now moves RH *toward outdoor RH* (the old
  expectation relied on the artificial drying term), and CO2 uptake bookkeeping
  is isolated with `ventilation_ach = 0` (the configured 3 ACH now exchanges air).
- Phase 5.29 re-run as integrated regression (`tests/test_integrated_synthetic_validation.py`,
  manual script): all 30 cases `PASS`, feedback loop without saturation
  violations, greenhouse-crop integration qualified.
- `manual_phase5_30_greenhouse_physical_corrections_test.py`: scenarios A–G.

## 7. Impact on previous outputs

Outputs change wherever the defects acted: all greenhouse trajectories (indoor
temperature/RH/CO2 dynamics, crop temperature, no indoor rain, CO2 factor),
outdoor trajectories through the restored VPD stress, perennial trajectories
before dormancy release, and the Phase 5.22/5.24/5.28/5.29 artifacts derived
from them, which were regenerated. Unaffected contracts and hashes (for example
`Scenario.config_hash` without an initial microclimate) are unchanged.

## 8. Limitations

- Lumped single-zone air; no longwave radiative exchange (night radiative
  cooling only through `heat_loss_w_k`); condensation releases no latent heat to
  the air; no canopy energy balance or stomatal conductance model.
- Crop sensible heat is an existing engineering proxy added on top of the full
  transmitted solar gain (small possible double counting).
- The default configuration pairs 1000 m3 with a 1 m2 exchange area (and the
  feedback `air_volume_m3` is per m2); the equations are dimensionally consistent,
  but the default geometry remains an engineering placeholder pending site data.
- The orchestrator greenhouse receives only LAI feedback; transpiration/CO2
  uptake coupling is iterated only in `CropGreenhouseFeedbackLoop`.
- The CO2 response gives no enrichment benefit above 420 ppm (existing response).
- No next-campaign transition for perennials (post-harvest back to dormancy).
- Closed-greenhouse runs keep a `PLAUSIBILITY_REVIEW` warning (indoor up to
  ~6 °C below outdoor in the afternoon), explained by thermal inertia
  (τ = C/G ≈ 8.7 h) plus canopy latent cooling; it is not a conservation violation.

## 9. Relation to future real validation

The corrected model remains uncalibrated. Real greenhouse inventory (areas,
volume, cover conductance, thermal mass) and microclimate observations will be
needed to replace the engineering placeholders and to evaluate the model in the
final calibration (5.26) and independent validation (5.27/5.28) stages.

## Usage

```powershell
python -m pytest tests/test_greenhouse_physical_corrections.py
python -m pytest tests/test_integrated_synthetic_validation.py
python -u manual_phase5_30_greenhouse_physical_corrections_test.py
python -u manual_phase5_29_integrated_synthetic_validation_test.py
```
