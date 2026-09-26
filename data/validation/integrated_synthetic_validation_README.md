# Integrated synthetic validation (Phase 5.29)

Deterministic `SYNTHETIC_INTEGRATED_VALIDATION` artifact. It qualifies software and model consistency under controlled synthetic scenarios.
It does not establish biological validity, field validity, experimental accuracy or transferability to real agricultural systems.

- version: `5.29.1`
- configuration hash: `99189c9e2a04f596a4265a47bb123bcb2bf4b85d3007bb34f99156898d8abf1a`
- report hash: `735d615ecf6a3b00f2bfd135c252fa452554c300c2550d215244dfdaf54be210`
- cases: `30`; status counts: `{"PASS": 25, "PASS_WITH_WARNINGS": 5}`
- REAL_VERIFIED: `0`; calibration performed: `false`; experimental validation performed: `false`

## Qualification

- INTEGRATED_SYNTHETIC_VALIDATION: `READY`
- SYNTHETIC_MODEL_CONSISTENCY: `QUALIFIED`
- TEMPORAL_CONTINUITY: `QUALIFIED`
- PERSISTENT_STATE_CONSISTENCY: `QUALIFIED`
- MULTI_PLOT_CONSISTENCY: `QUALIFIED`
- MULTI_CYCLE_CONSISTENCY: `QUALIFIED`
- GREENHOUSE_CROP_INTEGRATION: `NOT_QUALIFIED`
- ROBUSTNESS_SCENARIOS: `QUALIFIED`
- DETERMINISM: `QUALIFIED`
- STATIC_AUDIT: `QUALIFIED`
- PARAMETER_IMMUTABILITY: `QUALIFIED`

## Open findings

- `CO2_NOT_CONSUMED_BY_ORCHESTRATOR_GROWTH` (WARNING): CropDigitalTwinOrchestrator raises indoor CO2 under enrichment but its growth limitation product has no CO2 factor; only CropGreenhouseFeedbackLoop applies co2_ppm / 420 (capped at 1).
- `DORMANCY_GROWTH_NOT_SUPPRESSED` (WARNING): Perennial biomass increases before dormancy release: dormancy only gates GDD accumulation in PhenologyEngine; growth engines do not suppress growth during endodormancy.
- `PLAUSIBILITY_REVIEW` (WARNING): indoor air up to 8.8 C below outdoor without a cooling actuator (threshold 5 C, ENGINEERING_TEST_THRESHOLD)
- `INVARIANT_VIOLATION` (FAILURE): latent heat flux > 0 while indoor VPD = 0 (saturated air) in 63 steps: CropPhysicalExchangeModel transpiration ignores indoor saturation
- `PLAUSIBILITY_REVIEW` (WARNING): indoor air up to 32.7 C below outdoor without a cooling actuator (threshold 5 C, ENGINEERING_TEST_THRESHOLD)
- `GREENHOUSE_TEMPERATURE_NOT_USED_BY_CROP` (WARNING): CropDigitalTwinOrchestrator passes outdoor air temperature (with indoor radiation) to phenology, water balance and climate stress; indoor air temperature from the greenhouse model is not used by the crop.
- `GREENHOUSE_CONFIGURATION_VENTILATION_UNUSED` (WARNING): GreenhouseConfiguration.ventilation_ach (base infiltration) is not read by SimplifiedGreenhouseModel; only the actuator ventilation drives air exchange, so a closed greenhouse has zero infiltration and heat loss is referenced to a fixed 20 C.
- `ORCHESTRATOR_GREENHOUSE_STEP_MEMORYLESS` (INFO): GreenhouseMicroclimateEngine.advance resets its prior state when no prior is given, so the orchestrator greenhouse step carries no thermal/CO2 memory between steps; memory is exercised through SimplifiedGreenhouseModel with an explicit prior.
