# Phase 5.45: optional FAO-56 Penman-Monteith evapotranspiration and optional CO2 growth response

Status: **COMPLETE (software qualification)**. A published equation implemented and checked against its paper's worked examples; **not** calibrated or validated against lysimeter or station data.

## Why

Audit finding 5 (`docs/auditoria_modelos_prediccion.md`): the model's ET0 is a Hargreaves-like estimate with a fixed temperature range of 10 degC (`0.0023 (T + 17.8) sqrt(10) Rs`): no wind, humidity or pressure term.
A WIND event or a dry-air event could not change evapotranspiration, and ET0 was 30-40 % above what the FAO-56 equation gives for the same spring weather.

## What it is

`domain/evapotranspiration.py` implements the FAO-56 hourly Penman-Monteith equation (Allen et al., 1998: eq. 53 with 28, 37, 39-40, 45-47, 7, 12, 13 and the wind conversion 47). Every constant is the paper's.

* **Inputs:** temperature, relative humidity, wind speed, pressure and solar radiation of the step; the site (latitude, longitude, elevation).
* **Site:** never a default. A local-archive run uses its weather location (`src/weather_locations.json`, coordinates still pending the user's confirmation); otherwise the plot of `src/farm_config.json`. A crop whose plot has no coordinates
  (lettuce, peach, apple) is refused with a structured error unless the local archive is used. Elevation is the plot's, or is derived from the station pressure (eq. 7 inverted).
* **Wind height:** the local archive stores Open-Meteo `wind_speed_10m`, converted to 2 m (eq. 47); the synthetic generator defines no height and is taken as 2 m (no conversion).
* **Sky clearness (Rs/Rso):** from the outdoor radiation of the step, clipped to 0.3-1.0 as in the paper; at night, as the paper prescribes, the value two hours before the last sunlit hour. The outdoor radiation of a past step comes
  from the weather engine itself (a pure function of time), so what-if branches stay exact.
* **Soil heat flux:** 0.1 Rn by day, 0.5 Rn at night (eq. 45-46).
* **Inside a greenhouse:** the equation is applied with the crop's indoor microclimate and the **user's air speed** (`indoor_wind_m_s`, default 0: the outdoor wind does not reach the crop). It is outside the equation's validated open-field domain and is flagged as such.
* **Crop coefficient:** unchanged (the model's LAI and stage factor), not FAO Kc.

## How to use it

`"model_options": {"et0_method": "PENMAN_MONTEITH_FAO56", "indoor_wind_m_s": 0.3}` (selector "Reference evapotranspiration" in the bench's group 5). Default `HARGREAVES_HISTORICAL`: a request without the block is unchanged (same hashes, checkpoints and results); the block is part of the request,
the resume identity and the effective configuration (`evapotranspiration`) only when present. With the crop-feedback option of phase 5.44 the crop's transpiration into the air uses the same engine, so the air and the soil see one evapotranspiration.

## Result (tomato, 15 Feb-12 Apr, synthetic Murcia-like season)

ET0 summed over the window: 196 mm (historical) against 147 mm (FAO-56) outdoors, 195 against 114 mm in the greenhouse with still air. With FAO-56 a WIND event changes evapotranspiration (it does not with the historical estimate, which the audit's strict xfail still documents).

## Tests

`tests/test_evapotranspiration.py`: FAO-56 example 19 (0.63 mm/h) and the daily extraterrestrial radiation of example 8 (32.2 MJ m-2 day-1) reproduced; wind conversion and elevation round trip; wind and dryness raise demand; night clearness taken before sunset;
default request unchanged; validation paths; missing coordinates; identity and determinism; wind effect only with the option; greenhouse air speed; exact what-if.

## Limits

Reference grass ET0 only; not calibrated. Coordinates of the weather locations are approximate and pending confirmation. The synthetic generator's wind height is an assumption. Inside greenhouses the equation is applied outside its domain with the user's air speed.

## Optional growth response to CO2 (audit finding 6)

The historical response is `min(1, CO2 / 420)`: depletion limits growth and enrichment gives nothing, so a CO2 event raised the greenhouse's CO2 but never the crop's growth. `model_options.co2_response = "LOG_RELATIVE_GAIN"`
(selector "Growth response to CO2" in the bench) applies `factor(C) = 1 + gain / ln 2 * ln(C / 420)` (1 at 420 ppm, `1 + gain` at 840 ppm, never negative). Default `HISTORICAL_CAPPED`: unchanged hashes and results.

* **The parameter has a source** (`src/co2_response.json`, status `LITERATURE_GENERIC_C3_NOT_CROP_SPECIFIC`): Kimball (1983), *Agronomy Journal* 75(5): 779-788, doi 10.2134/agronj1983.00021962007500050014x: pooled 430+ observations of 37 species, doubling
  atmospheric CO2 raises yield by about **33 %** (99.9 % confidence interval 24-43 %). Verified against the paper's Crossref record (abstract) on 2026-10-23; the full text was not read.
* **What is not in the source and is stated as an assumption in the file:** the logarithmic form; the doubling taken from the model's 420 ppm reference; a yield ratio applied to the growth rate (no water-saving effect, no acclimation); mostly greenhouse and chamber data
  (free-air studies give smaller responses; Kimball 2016/2017 reports about +19 % for C3 grain crops in FACE). It is a generic C3 value, not a tomato, pepper or lettuce value, and not calibrated in this model.
* **Your own value:** `co2_gain_per_doubling` (0-1) replaces the source value for the request and is part of its identity; the effective configuration reports which one was used.
* **Mechanics:** a factor above 1 is an enhancement of the radiation use efficiency, not one of the (at most 1) limitations, so `RadiationGrowthEngine.advance` takes an `enhancement_factor` (default 1: unchanged). The orchestrator and, with the crop-feedback option of phase 5.44, its growth proxy use the same response.
* **Effect (tomato, simplified greenhouse, CO2 event to about 620 ppm from 1 March):** cumulative biomass 149.6 -> 158.4 g/m2 with the logarithmic response; no change with the historical one. EnergyPlus does not model CO2 and is unaffected.

Tests: `tests/test_co2_response.py` (function values, parameter file, validation, opt-in behaviour, user gain, crop-feedback proxy, exact what-if).
