# Seasonal synthetic campaign (Phase 5.32)

Complete crop campaigns under plausible, deterministic synthetic climate scenarios. Results characterise the implemented model
(scenario response metrics, MODEL_BEHAVIOR_CONSISTENT at most); they are not accuracy, calibration, biological validation or
a representation of any real climatology.

- version: `5.32.1`; seed: `532`
- campaigns: `122`; status counts: `{"PASS": 72, "PASS_WITH_WARNINGS": 50}`
- direction checks: `112` rows, inconsistent: `0`
- qualified: `True`
- report hash: `54ed8088b5972d42ed73fa788615e00eef93cd2f72ded82d1e67a34f9afb0d9b` (execution metadata excluded)

## Sections

- climate_profiles: `PASS`
- determinism: `PASS`
- greenhouse: `PASS`
- immutability: `PASS`
- multi_cycle: `PASS_WITH_WARNINGS`
- multi_plot: `PASS`
- persistence: `PASS`
- restart: `PASS`
- static_audit: `PASS`

## Open scientific decisions

- `PERENNIAL_CHILLING_SEASON_ONSET` (apple): the existing synthetic cycle starts the apple campaign on 2026-02-01; no chilling accumulation before that date is defined, and the existing chilling requirement is not met under BASE_SEASON, so its season-scale growth responses are not characterised (no date is invented)
- `PERENNIAL_CHILLING_SEASON_ONSET` (peach): the existing synthetic cycle starts the peach campaign on 2026-02-01; no chilling accumulation before that date is defined, and the existing chilling requirement is not met under BASE_SEASON, so its season-scale growth responses are not characterised (no date is invented)

## Unsupported capabilities

- `PERENNIAL_CONSECUTIVE_CAMPAIGNS` (OPEN_MODEL_CAPABILITY): PhenologyEngine has no transition from post_harvest_dormancy back to dormancy; one perennial campaign is simulated
- `WIND_EFFECT_ON_CROP` (NOT_SUPPORTED): wind speed is not an input of the crop, stress or water-balance engines; WIND_SPELL is carried through the forcing only
- `ACTUAL_EVAPOTRANSPIRATION_UNDER_DEFICIT` (OPEN_MODEL_CAPABILITY): WaterBalanceResult reports transpiration/evaporation demand even when soil water limits uptake; water_use_mm is a demand-based proxy
