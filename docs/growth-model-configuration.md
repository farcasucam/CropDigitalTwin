# Phase 4.7.1 Growth Model Configuration Contract

## Status and scope

`src/growth_model_config.json` freezes the input contract for a later
simplified crop-growth model. It is explicitly `CONTRACT_ONLY`: it neither
advances a crop stage nor owns weather generation, simulation time, or
actuator commands. `SimulationClock`, `SimulationScheduler`, Weather Engine,
and Crop Engine therefore retain their current responsibilities.

The contract covers outdoor, passive greenhouse, and actuated greenhouse
cases. A plot has no environment assignment yet because `farm_config.json`
does not provide one; it must be supplied explicitly in a later calibrated
plot configuration, never inferred from a plot code.

## Crop parameters

The crop parameter registry declares thermal base and upper temperatures,
chilling requirement, GDD transition target, VPD and radiation responses,
maximum LAI, RUE, biomass partitioning, root depth, and maturity response.
Every descriptor records its unit, plausible range, default, evidence status,
and crop/variety/plot specificity. All defaults are `null` and all statuses
are `CALIBRATION_REQUIRED`. The seven crop profiles cite
`src/crop_phenology.csv`; that file remains evidence only and does not
activate phenology.

No variety parameter has been invented for RAF, Lamuyo, Monastrell, or Suplum
26. Existing `crop_config.json` stage stress thresholds remain the Crop
Engine's current stress inputs and are not copied into this registry.

## Soil, greenhouse, and actuators

Soil profiles cover the three types used by `farm_config.json`. Field capacity
and wilting point are volumetric water content (fraction), and available water
capacity is mm per m of effective rooting depth. They are labelled
`engineering_approximation` and require plot calibration. Rooting depth,
infiltration, and drainage are intentionally unset.

Greenhouse profiles reserve floor area (m2), volume (m3), solar transmission
(fraction), thermal mass (kJ/K), ventilation (air changes/h), cover type,
shading (fraction), and heat loss (W/K). Apart from outdoor solar
transmission of 1.0 by definition, they remain unset and are marked
`PENDING_SITE_INVENTORY`. Actuator availability
and capacity are separate from crop parameters and remain unset for every
plot; the contract lists irrigation, heating, cooling, HVAC, ventilation,
shading, misting, and CO2 with their units.

## Deliberately unset

- Crop and variety thermal, chilling, GDD, LAI, RUE, SLA-equivalent, biomass,
  root, maturity, VPD, radiation, and stress-response values.
- Plot rooting depth, infiltration, drainage, and measured soil hydraulic
  properties.
- Plot environment assignment and all passive/actuated greenhouse properties.
- Actuator availability and capacity.

These require traceable scientific evidence, engineering design data, or
local calibration before a later phase may activate a growth model.