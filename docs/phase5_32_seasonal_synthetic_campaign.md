# Phase 5.32 — Plausible Synthetic Climate Scenarios and Full-Campaign Validation

## Current Result and Scientific Stance

```text
PHASE 5.32 COMPLETE
SEASON-SCALE SYNTHETIC CAMPAIGN FRAMEWORK QUALIFIED
SYNTHETIC CLIMATE SCENARIOS QUALIFIED
FULL-CAMPAIGN TEMPORAL CONSISTENCY QUALIFIED
STRESS RESPONSE CONSISTENCY QUALIFIED
MULTI-PLOT CONSISTENCY QUALIFIED
CHECKPOINT / RESTART CONSISTENCY QUALIFIED
DETERMINISTIC REPLAY QUALIFIED
GREENHOUSE SEASONAL COUPLING QUALIFIED
SEASON RESPONSES NOT CHARACTERISED FOR PEACH AND APPLE (OPEN_SCIENTIFIC_DECISION)
REAL AGRICULTURAL DATA NOT VERIFIED
REAL_VERIFIED = 0
CALIBRATION NOT PERFORMED
CALIBRATION_PERFORMED = false
EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE
EXPERIMENTAL_VALIDATION_PERFORMED = false
BIOLOGICAL VALIDITY NOT CLAIMED
FIELD ACCURACY NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

`QUALIFIED` means only that the software passes the synthetic scenarios and
invariants of this phase. Results do not quantitatively represent a real
agricultural campaign. Direction checks are classified `MODEL_BEHAVIOR_CONSISTENT`,
never `BIOLOGICALLY_VALIDATED`; scenario response metrics are not accuracy.

## 1. Objective

Move from analytical physical consistency (5.31) to season-scale synthetic
behavioural consistency: complete crop campaigns for the seven crops under
plausible, deterministic synthetic climates, outdoor and greenhouse.

## 2. Baseline and audit

Baseline at HEAD `1a18d8f` (clean tree, Python 3.13.9): **787 passed, 12 skipped,
0 failed** — the expected Phase 5.31 result.

Existing weather generation: `WeatherEngine` (Phase 2) gives a fixed diurnal
cycle (temperature min at 05:00 and max at 15:00, sine radiation between fixed
sunrise/sunset, cosine humidity) plus a small seeded per-day wave. It had no
seasonal cycle and no configurable day-to-day variability, and the per-day wave
re-phases at midnight (small discontinuities; kept unchanged because every
earlier weather-driven artifact depends on it). Events were the `ScenarioEvent`
overlays of `ScenarioRunner` (step on/off).

## 3. Architecture (extension, no second engine)

- `WeatherConfiguration` gains two optional sections (default `None`, outputs
  bit-identical): `SeasonalConfiguration` (continuous cosine annual cycle of
  temperature, radiation and humidity; seasonal day length) and
  `DailyVariabilityConfiguration` (seeded day anomalies interpolated between
  midnight anchors, so the forcing is continuous).
- `ScenarioEvent` overlays gain an optional `ramp_hours` parameter (linear onset
  and decay, gradual return to the base regime) and two types, `cold_wave`
  (additive negative offset) and `wind` (speed multiplier). Unramped events keep
  their exact previous values.
- `CropSimulationSnapshot` records the existing `WaterBalanceResult`
  (transpiration, evaporation, irrigation, precipitation, drainage).
- The Phase 5.29 multi-plot/multi-cycle runners accept a weather configuration.
- `src/agri_twin/application/seasonal_synthetic_campaign.py`
  (`SeasonalSyntheticCampaignSuite`, `SyntheticClimateScenario`, `CampaignSpec`)
  composes `ScenarioRunner`/`SimulationClock`, `CropDigitalTwinOrchestrator`,
  `MultiPlotSimulation`, the 5.29 validators and checkpoint helpers, and the
  existing synthetic cycles. It contains no weather, crop, phenology, greenhouse
  or water equations.

## 4. Climate profiles

Base synthetic profile (scenario forcing, not a real climatology): diurnal
11.5–24 °C, 750 W m-2 peak, 40–88 % RH; seasonal amplitude 8.5 °C, ±30 %
radiation, ±8 % RH (humid when cold), ±2 h day length, warmest day 200; daily
anomalies ±2 °C, ±15 % radiation, ±5 % RH (seeded). Resulting annual cycle:
January mean ≈ 9.3 °C with ≈ 9 h daylight, July mean ≈ 26.7 °C with ≈ 15 h.

Verified properties: seasonal gradient, seasonal day length, continuity across
days (≤ 0.002 per second across midnight; threshold 0.01 as
`ENGINEERING_TEST_THRESHOLD`; the engine resolves time to the second), zero
night radiation, radiation peak at midday, temperature minimum near dawn and
maximum mid-afternoon, physical bounds, seed-reproducible and seed-dependent
variability, gradual event onset/decay, and exact return to the base regime
after an event.

## 5. Scenarios

Season-long profile shifts: `HOT_SEASON` (+3 °C), `COLD_SEASON` (−3 °C),
`LOW_RADIATION` (×0.7), `HIGH_RADIATION` (×1.2), `DRY_SEASON` (−20 % RH and half
irrigation), `HUMID_SEASON` (+10 % RH). Seven-day ramped events at mid-campaign:
`HEAT_WAVE` (+8 °C), `COLD_WAVE` (−8 °C), `HEAT_WAVE_WITH_DRYNESS` (+8 °C, RH →
20 %, irrigation gap), `HIGH_RADIATION_WITH_LOW_WATER` (×1.3, irrigation gap),
`RECOVERY_AFTER_STRESS` (+8 °C with irrigation gap, then recovery), plus
supplementary `WIND_SPELL` and `RAIN_SPELL` (tomato outdoor). `BASE_SEASON` has
season-long drip irrigation of 0.4 mm h-1. None represents a real climatology.

## 6. Crops, dates and environments

All seven crops outdoor; tomato, lettuce and pepper also in the passive
greenhouse (crop consumes indoor temperature, RH, VPD, radiation and CO2, no
rain). Campaign dates come only from the existing synthetic cycles
(`SyntheticReferenceDatasetGenerator`): planting date to harvest end; perennial
cycles without a planting date start on 1 January of the campaign year
(dormancy). Varieties RAF, Lamuyo, Monastrell and Suplum 26 are kept and labelled
`SPECIES_FALLBACK`.

## 7. Invariants, determinism, restart

Per campaign: the 13 Phase 5.29 trajectory invariants, plus strictly increasing,
non-duplicated, uniform timestamps; no soil water created beyond irrigation and
rain; the crop consumes the correct environment; a single CO2 response; physical
ranges of VPD, RH, radiation and CO2. Tomato outdoor under every scenario and
every crop/environment `BASE_SEASON` are replayed with identical trajectory
hashes; checkpoints at 25/50/75 % (tomato outdoor, plum outdoor, tomato
greenhouse heat wave) restart with `max_difference = 0.0`. ParameterRegistry,
all crop ParameterSets and the default GreenhouseConfiguration are unchanged
before and after.

## 8. Direction checks (ceteris paribus against `BASE_SEASON`)

Warmer/colder environment and non-decreasing heat/cold stress for season shifts;
APAR at the first active step (identical crop state) moves with radiation, and
cumulative APAR drops under low radiation; drier air raises VPD and, when water
becomes limiting, water stress; humid air lowers VPD; scenarios coincide with
`BASE_SEASON` before the event window; heat waves raise VPD and do not lower heat
stress; cold waves do not lower cold stress; irrigation gaps raise water stress,
which falls again after irrigation resumes; biomass lost in stress-only events
does not reappear. Growth changes under heat or high radiation are reported, not
imposed.

## 9. Findings and classification

| Classification | Finding |
| --- | --- |
| `OPEN_SCIENTIFIC_DECISION` | Peach and apple cycles start on 1 February (existing synthetic cycle); with no chilling accumulation defined before that date, the existing chilling requirement (600 h) is not met under `BASE_SEASON`, so their season responses are not characterised. No chilling-onset date is invented. |
| model behaviour | Grape and plum release dormancy (Feb 13 / Feb 28) and mature; under `HOT_SEASON` their chilling requirement is not met (low-chill behaviour of the existing profile). |
| `SCENARIO_DESIGN_ISSUE` | Lettuce campaigns follow the 41-day synthetic cycle, which ends before the engineering thermal-time maturity; tomato under `COLD_SEASON` also ends just before maturity. Reported as warnings. |
| `SCENARIO_DESIGN_ISSUE` (checks) | Direction checks now require their precondition: cumulative APAR only with an active canopy, water-stress increase only when water becomes limiting (winter greenhouse lettuce stays unlimited with half irrigation). |
| `MODEL_CAPABILITY_GAP` | No consecutive perennial campaigns; wind is not an input of the crop engines; water use is demand-based (WaterBalanceEngine reports demand under deficit). |

## 10. Tests and artifacts

- `tests/test_seasonal_synthetic_campaign.py`: 67 tests (10 climate-profile
  properties plus engine/overlay compatibility, 7 crop campaigns, greenhouse,
  stress responses, all 12 scenarios on lettuce, multi-plot, multi-cycle,
  checkpoints, determinism, immutability, static audit, scientific stance).
- `manual_phase5_32_seasonal_synthetic_campaign_test.py`: full matrix and the
  mandatory showcase; exit 0 only if every mandatory case passes.
- `data/validation/seasonal_synthetic_campaign_report.json` and
  `seasonal_synthetic_campaign_README.md`: scenarios, crops, varieties, plots,
  seeds, environments, campaign lengths, response metrics, stress exposure,
  trajectory and checkpoint hashes, determinism, registry and configuration
  hashes, warnings, unsupported capabilities, open decisions, limitations; the
  report hash excludes the execution metadata (performance).

## 11. Limitations

Synthetic forcing only; one seed; species-level engineering parameters; calendar
from existing synthetic cycles; one perennial campaign; wind without crop effect;
demand-based water use; the limitations of Phases 5.29–5.31 still apply.
