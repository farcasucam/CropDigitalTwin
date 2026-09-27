# Greenhouse physical benchmark (Phase 5.31)

Deterministic analytical benchmarks of the greenhouse-crop model. QUALIFIED means the implementation passed these synthetic benchmarks;
it is not validation against a real greenhouse, not calibration, and claims no biological validity or field accuracy.

- version: `5.31.1`
- benchmark cases: `47`; status counts: `{"FAIL": 0, "PASS": 47, "WARN": 0}`
- qualified: `True`
- invariants: `PASS`; traceability: `PASS`; static audit: `PASS`
- EnergyPlus: `UNAVAILABLE` (optional, never ground truth)
- parameter registry hash: `18cddbc7e9b834a9a327825489178bdca7f1a64924b075274f4882d70839aa90`
- report hash: `c4b0ba39d307bf643909d7501dcf03f8efbdbc202e59647b3f717ca478645c55`

## Cases

- `energy.identical_ambient_no_drift` [PHYSICAL_CONSISTENCY] PASS: identical indoor/outdoor state without sources: no thermal or humidity drift
- `energy.radiation_energy_closure` [PHYSICAL_CONSISTENCY] PASS: sealed adiabatic air: stored heat C*dT equals transmitted solar energy (no energy created or lost)
- `energy.exchange_sign` [PHYSICAL_CONSISTENCY] PASS: indoor warmer than outdoor loses heat, colder gains heat
- `energy.exchange_scales_with_difference` [PHYSICAL_CONSISTENCY] PASS: without sources the exchange is linear in (T_in - T_out): doubling the difference doubles the change
- `energy.no_hidden_reference_temperature` [PHYSICAL_CONSISTENCY] PASS: translating both temperatures (across 20 C) leaves the exchange unchanged: no fixed reference temperature
- `energy.thermal_time_constant` [PHYSICAL_CONSISTENCY] PASS: pure decay with tau = C/G: after ln2*tau the indoor-outdoor difference halves
- `monotonicity.outdoor_temperature` [PHYSICAL_CONSISTENCY] PASS: higher outdoor temperature gives a higher indoor temperature, ceteris paribus
- `ventilation.exchanged_fraction` [PHYSICAL_CONSISTENCY] PASS: exchanged fraction = 1 - exp(-ACH dt/3600), 0 at 0 ACH, increasing with ACH, never instantaneous equilibrium
- `ventilation.temperature_toward_outdoor` [PHYSICAL_CONSISTENCY] PASS: more air exchange brings indoor temperature closer to outdoor; no change at 0 ACH
- `ventilation.vapour_toward_outdoor` [PHYSICAL_CONSISTENCY] PASS: more air exchange brings indoor vapour closer to outdoor; no change at 0 ACH
- `ventilation.co2_toward_outdoor` [PHYSICAL_CONSISTENCY] PASS: more air exchange brings indoor co2 closer to outdoor; no change at 0 ACH
- `ventilation.configuration_plus_actuator` [SOFTWARE_CORRECTNESS] PASS: air exchange = configured ventilation_ach + actuator ventilation
- `ventilation.no_direct_biomass_path` [PHYSICAL_CONSISTENCY] PASS: when ventilation leaves the microclimate unchanged, the crop is unchanged: no actuator-to-biomass path
- `humidity.rh_vpd_bounds` [PHYSICAL_CONSISTENCY] PASS: RH in [0, 100] %, VPD >= 0 kPa, VPD = 0 at saturation, for dry, humid and saturated air
- `humidity.closed_box_vapour_conservation` [PHYSICAL_CONSISTENCY] PASS: sealed air below saturation: vapour mass gain equals transpired water (1 mm = 1 kg m-2)
- `humidity.condensation_bound` [PHYSICAL_CONSISTENCY] PASS: cooling humid air caps vapour at saturation: RH = 100 %, VPD = 0
- `humidity.closed_saturated_greenhouse_no_latent_regression` [PHYSICAL_CONSISTENCY] PASS: Phase 5.29 regression: no latent heat flux while indoor air is saturated (VPD = 0) in a closed greenhouse
- `humidity.no_double_vpd_correction` [SOFTWARE_CORRECTNESS] PASS: transpiration demand is not VPD-corrected a second time (only the saturation cap), and crop VPD stress is one ramp of the environment VPD
- `units.vpd_kpa` [SOFTWARE_CORRECTNESS] PASS: VPD is reported in kPa (Tetens e_s(25 C) = 3.1686 kPa, half of it at 50 % RH)
- `latent.no_crop_no_flux` [PHYSICAL_CONSISTENCY] PASS: no canopy: no transpiration and no latent flux
- `latent.crop_without_transpiration` [PHYSICAL_CONSISTENCY] PASS: canopy without radiative demand (night): no transpiration, no latent flux
- `latent.dry_air_cooling_applied_once` [PHYSICAL_CONSISTENCY] PASS: LE = E*lambda/3600 and the greenhouse cools by exactly LE*A*dt/C (single application, correct sign)
- `latent.saturated_air_no_cooling` [PHYSICAL_CONSISTENCY] PASS: saturated air (VPD = 0) has no evaporative capacity: no latent cooling
- `monotonicity.transpiration_capacity` [PHYSICAL_CONSISTENCY] PASS: more evaporative capacity (lower RH) gives non-decreasing latent flux, bounded by the water-balance demand
- `radiation.cover_transmission` [PHYSICAL_CONSISTENCY] PASS: indoor radiation = outdoor x transmission (lower transmission, less radiation)
- `radiation.shading` [PHYSICAL_CONSISTENCY] PASS: indoor radiation = outdoor x transmission x (1 - shading) (more shading, less radiation)
- `radiation.zero` [PHYSICAL_CONSISTENCY] PASS: no outdoor radiation: no indoor radiation and no potential growth
- `radiation.single_path_to_crop` [SOFTWARE_CORRECTNESS] PASS: potential growth = PAR(indoor radiation) x (1 - exp(-k LAI)) x RUE, applied once; never the outdoor radiation
- `co2.closed_box_bookkeeping` [PHYSICAL_CONSISTENCY] PASS: sealed air: supply adds and uptake removes exactly their per-step increments
- `co2.ventilated_equilibrium` [PHYSICAL_CONSISTENCY] PASS: with constant supply and exchange, CO2 tends to C_out + S/k
- `monotonicity.co2_supply` [PHYSICAL_CONSISTENCY] PASS: more supply gives higher indoor CO2, ceteris paribus
- `co2.crop_uptake_reduces_co2` [PHYSICAL_CONSISTENCY] PASS: a growing canopy lowers indoor CO2 relative to the same greenhouse without crop
- `co2.single_path_to_growth` [SOFTWARE_CORRECTNESS] PASS: MicroclimateState.CO2 -> CropGrowthInput.co2_ppm -> CropGrowthEngine.co2_response, applied once in both integration paths; double input rejected
- `crop_microclimate.outdoor_temperature` [SOFTWARE_CORRECTNESS] PASS: outdoor: crop temperature == outdoor weather temperature (whole WeatherState, rain included)
- `crop_microclimate.greenhouse_temperature` [SOFTWARE_CORRECTNESS] PASS: greenhouse: crop temperature == indoor microclimate temperature, not outdoor
- `crop_microclimate.greenhouse_rh_vpd_radiation_co2` [SOFTWARE_CORRECTNESS] PASS: greenhouse: crop RH, VPD, radiation and CO2 are the indoor values and no rain reaches the crop
- `feedback.none` [SOFTWARE_CORRECTNESS] PASS: without crop exchanges (all zero) the loop reproduces the greenhouse step (to 1e-12 relative, the rounding of the relaxation blend)
- `feedback.thermal_isolated` [PHYSICAL_CONSISTENCY] PASS: thermal feedback changes only its own balance (temperature sign +1; vapour unchanged; CO2 unchanged)
- `feedback.latent_isolated` [PHYSICAL_CONSISTENCY] PASS: latent feedback changes only its own balance (temperature sign -1; vapour unchanged; CO2 unchanged)
- `feedback.co2_isolated` [PHYSICAL_CONSISTENCY] PASS: co2 feedback changes only its own balance (temperature sign +0; vapour unchanged; CO2 decreases)
- `feedback.relaxation_applied_once` [SOFTWARE_CORRECTNESS] PASS: one iteration = one relaxation of the candidate toward the recomputed state, both from the same start state
- `feedback.only_converged_state_persists` [SOFTWARE_CORRECTNESS] PASS: intermediate iterations mutate no persistent state: loop and greenhouse backend hold the converged state, the input crop is untouched
- `feedback.combined_convergence_determinism` [SOFTWARE_CORRECTNESS] PASS: combined thermal+latent+CO2 feedback converges every step, replays identically, has no NaN/Inf and no artificial temperature oscillation
- `determinism.scenario_replay` [SOFTWARE_CORRECTNESS] PASS: the same scenario replayed through SimulationClock gives an identical full trajectory
- `units.heating_kw_to_joules` [SOFTWARE_CORRECTNESS] PASS: 1 kW for 1 h into C = thermal_mass_kj_k x 1000 J/K raises T by 3.6e6 / C
- `units.misting_mm_h_to_kg` [SOFTWARE_CORRECTNESS] PASS: 0.36 mm/h over 1 m2 for 1 h evaporates 0.36 kg (below saturation) and removes its latent heat
- `mutation.no_parameter_configuration_or_state_mutation` [SOFTWARE_CORRECTNESS] PASS: benchmark execution mutates neither the ParameterRegistry, nor GreenhouseConfiguration, nor input crop states
