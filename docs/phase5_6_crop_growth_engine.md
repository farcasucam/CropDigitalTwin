# Phase 5.6 Crop Growth / Biomass and LAI Engine

## Objective and architecture

`CropGrowthEngine` is a deterministic, simplified mechanistic facade. It
consumes an environmental input and an existing `CropGrowthState`; it does not
generate weather, own water/nutrient balances, run phenology, or create a
clock. Outdoor and greenhouse callers provide the appropriate `WeatherState`
or `DerivedEnvironmentState`.

```text
Environment -> radiation -> PAR -> APAR -> potential growth
                                      -> stress factors
                                      -> actual growth -> biomass / LAI
                                      -> senescence / damage -> maturity state
```

## Equations and units

`WeatherState.solar_radiation_w_m2` is instantaneous global shortwave power.
For an explicit simulated interval:

`PAR_MJ_m-2 = 0.48 * radiation_W_m-2 * dt_s / 1e6`

The `0.48` PAR fraction is an engineering approximation. APAR uses
Beer-Lambert interception:

`APAR = PAR * (1 - exp(-k * LAI))`

`k` is dimensionless and LAI is `m2_leaf/m2_ground`. Potential biomass is
`APAR * RUE`, with RUE in `g_DM/MJ_PAR`. State biomass is `g_DM/m2_ground`.

Actual growth multiplies potential growth by bounded temperature, water, VPD,
radiation, nutrient, and CO2 factors. Nutrient and water factors can be
provided by Phases 4.7.5/4.7.6; CO2 defaults to the explicit engineering
value `1.0` until greenhouse data exists.

## LAI, senescence and damage

Leaf biomass is converted using SLA (`m2/g_DM`) and capped by the existing
profile maximum LAI. Dormancy applies the existing senescence rate. Frost,
heat, radiation and water damage reduce LAI through the persistent state
damage fields; tissue damage is not artificially recovered.

Maturity remains bounded in `[0,1]` and consumes existing phenology progress.
`maturity_index == 1` does not itself set `harvest_ready`.

## Parameter provenance

The radiation profiles reuse the existing Phase 4 defaults registered by
`ParameterRegistry` (`radiation.par_fraction`, `radiation.extinction_coefficient`,
`radiation.rue`, `radiation.sla`) and remain `engineering_default`,
`candidate_for_calibration`, and not calibrated. No variety-specific value is
introduced for RAF, Lamuyo, Monastrell or Suplum 26.

Temperature, VPD, radiation, water, nutrient and CO2 responses consume the
existing stage/configuration engines. This avoids a second registry, water
model, stress model or phenology model.

## Time, validation and limitations

`dt_seconds` is supplied by `SimulationClock`/`SimulationScheduler`; there is
no real-time access, IO, HTTP, ML, TimesFM, CFD, or internal wall clock. Large
simulated intervals are handled directly. Unit and integration tests establish
software correctness and determinism only. They are not scientific validation.

This is not DSSAT, APSIM, WOFOST, STICS, an FSPM, or a biochemical
photosynthesis model. Calibration-ready parameters must be fitted through the
existing Phase 5.5 protocol using real observations and then independently
validated.