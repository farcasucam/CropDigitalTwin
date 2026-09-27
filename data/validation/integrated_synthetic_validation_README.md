# Integrated synthetic validation (Phase 5.29)

Deterministic `SYNTHETIC_INTEGRATED_VALIDATION` artifact. It qualifies software and model consistency under controlled synthetic scenarios.
It does not establish biological validity, field validity, experimental accuracy or transferability to real agricultural systems.

- version: `5.29.2`
- configuration hash: `691d75ec62768f6ec1598f163257a57d9e5f644d0813c09ab8f33c84136a8565`
- report hash: `12e16c7525311c92d8415bca46457fa170d6c8c1a334e028af540ca9a3961ccd`
- cases: `30`; status counts: `{"PASS": 30}`
- REAL_VERIFIED: `0`; calibration performed: `false`; experimental validation performed: `false`

## Qualification

- INTEGRATED_SYNTHETIC_VALIDATION: `READY`
- SYNTHETIC_MODEL_CONSISTENCY: `QUALIFIED`
- TEMPORAL_CONTINUITY: `QUALIFIED`
- PERSISTENT_STATE_CONSISTENCY: `QUALIFIED`
- MULTI_PLOT_CONSISTENCY: `QUALIFIED`
- MULTI_CYCLE_CONSISTENCY: `QUALIFIED`
- GREENHOUSE_CROP_INTEGRATION: `QUALIFIED`
- MICROCLIMATE_TO_CROP_COUPLING: `QUALIFIED`
- FEEDBACK_LOOP: `QUALIFIED`
- DORMANCY_PHENOLOGY_CONSISTENCY: `QUALIFIED`
- ROBUSTNESS_SCENARIOS: `QUALIFIED`
- DETERMINISM: `QUALIFIED`
- STATIC_AUDIT: `QUALIFIED`
- PARAMETER_IMMUTABILITY: `QUALIFIED`

## Open findings

- `PLAUSIBILITY_REVIEW` (WARNING): indoor air up to 6.4 C below outdoor without a cooling actuator (threshold 5 C, ENGINEERING_TEST_THRESHOLD); consistent with thermal inertia (tau = C/G = 8.7 h lags the outdoor diurnal cycle) plus canopy latent cooling, not an energy-conservation violation
- `CO2_RESPONSE_CAPPED_AT_REFERENCE` (INFO): CropGrowthEngine.co2_response = min(1, CO2 / 420): depletion limits growth, enrichment above 420 ppm gives no benefit (existing engineering response, not extended).
- `ORCHESTRATOR_EXCHANGE_NOT_ITERATED` (INFO): CropDigitalTwinOrchestrator feeds only LAI back to the greenhouse; transpiration/CO2-uptake coupling is iterated only in CropGreenhouseFeedbackLoop.
- `PERENNIAL_NEXT_CAMPAIGN_NOT_SUPPORTED` (INFO): No transition from post_harvest_dormancy back to dormancy/establishment exists in PhenologyEngine.
- `CONDENSATION_LATENT_HEAT_NEGLECTED` (INFO): Vapour above saturation condenses without releasing latent heat to the air; no longwave radiative exchange is modelled.
