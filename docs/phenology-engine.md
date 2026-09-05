# Phase 4.7.3 Phenology Engine

`PhenologyEngine` is a pure domain service that converts supplied
`WeatherState`, explicit `simulation_time`, and `dt_seconds` into changes to
`CropGrowthState`. It owns neither a clock nor weather acquisition and does
not modify `CropEngine`.

## Thermal development

Annual crops (tomato, lettuce, pepper) use clipped daily degree days:
temperature is limited to `[Tbase, Tupper]`, then thermal time is scaled by
the explicit simulated duration. The three cumulative thresholds advance the
four existing project stages in order. `phenology_progress` is the continuous
progress inside the current stage; `maturity_index` is continuous `[0, 1]`.
Reaching maturity never sets `harvest_ready`: harvest remains an explicit
future business/agronomic rule.

Perennials (grape, peach, plum, apple) first accumulate simple chilling hours
when provided temperature is in `[0.0, 7.2]` degC. Until the profile's
requirement is met, GDD forcing and stage transition are gated. After release,
they use the same clipped thermal development. This is a deliberately simple
chilling/forcing infrastructure, not a Dynamic Model implementation.

## Evidence and calibration status

The built-in profiles are `ENGINEERING_APPROXIMATION`, are crop-level only,
and must not be interpreted as cultivar values or event dates. They do not
activate `src/crop_phenology.csv`: its values are external evidence marked
`NOT_ACTIVATED` and `UNMAPPED`; in particular, its FAO/GDD cycle values are
not promoted to exact biological transition dates.

`PhenologyProfile` exposes `SCIENTIFIC_BASE`, `ENGINEERING_APPROXIMATION`, and
`CALIBRATED` evidence levels. A later configuration/calibration phase may
inject a traceable profile with mapped observed events, but must retain the
same explicit input and deterministic replay contract.

## State fields

Phase 4.7.3 adds `gdd_accumulated`, `chilling_hours`, `dormancy_released`, and
`phenology_model` to `CropGrowthState`. They are non-negative or explicit
booleans, serialize with the existing state mapping, and preserve the Phase
4.7.2 timestamp invariant.