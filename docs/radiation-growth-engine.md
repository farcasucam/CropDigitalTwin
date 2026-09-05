# Phase 4.7.4 Radiation, LAI and Biomass Engine

`RadiationGrowthEngine` is a deterministic domain service for a crop interval
whose end time has already been set by `PhenologyEngine` and
`SimulationClock`. It changes only the biomass partition and LAI fields in
`CropGrowthState`; it does not own time, weather acquisition, soil water,
nutrients, irrigation, HVAC, or complex climate damage.

## Radiation and biomass units

`WeatherState.solar_radiation_w_m2` is global shortwave power. It is converted
for an explicit interval as:

$$PAR_{MJ/m^2}=0.48\times R_{W/m^2}\times dt_s/10^6$$

The 0.48 fraction is an engineering approximation for the PAR share of global
shortwave radiation. The model then calculates intercepted PAR with
Beer-Lambert:

$$PAR_i=PAR\times(1-e^{-k\times LAI})$$

Potential dry matter is $PAR_i \times RUE$. Biomass state fields are now
defined as $g$ dry matter per $m^2$ ground, consistent with RUE in
`g_DM/MJ_PAR`. Actual growth is potential growth multiplied by the explicit
`limitation_factor` in `[0,1]`; later water, nutrient, and climate models will
supply that factor without being implemented here.

## Approximate profiles and phase behavior

The built-in crop profiles use crop-level `ENGINEERING_APPROXIMATION` values:
$k=0.6$, RUE $=2.0\ g_DM/MJ_PAR$, SLA $=0.02\ m^2/g_DM$, and crop-level maximum
LAI. They are not cultivar parameters and do not activate pending values in
`growth_model_config.json` or phenology evidence. Calibrated profiles can be
injected through `RadiationGrowthProfile` in a later phase.

Phenology advances first; radiation growth reads its resulting `current_stage`.
Partition fractions allocate new biomass to leaf, stem, root and fruit. Leaf
allocation above the LAI cap is reassigned to stem to retain the explicit mass
balance. In `post_harvest_dormancy`, no new radiation growth is produced;
leaf biomass decreases with a bounded linear senescence rate and is accounted
as stem biomass. This is a bookkeeping proxy, not a litter or respiration
model.

With zero radiation or zero LAI, intercepted PAR and growth are zero. Large
explicit `dt` values remain bounded by LAI caps and do not cause internal
timestep subdivision.