# Phase 5.44: the simplified greenhouse is a lumped model of the same greenhouse EnergyPlus simulates

Status: **COMPLETE (software qualification)**. Consistency between two models that share PROVISIONAL envelope values; **not** validation against a real greenhouse (see `docs/scientific-limitations.md`).

## Why

The audit (`docs/auditoria_modelos_prediccion.md`, findings 2 and 3) found that the simplified greenhouse had a 1 m2 heat-exchange area for 1000 m3, so its solar gain was negligible:
at midday it was 0.02 K *cooler* than the outside air (EnergyPlus: 6.6 K warmer), 60 % shading changed its temperature by 0.05 K, and "vents fully open" meant +1 air change per hour
(EnergyPlus: 30). Every greenhouse intervention and the whole climate controller were physically meaningless in that model.

## What changed

* **One greenhouse for both models.** `application/consistent_greenhouse.py` derives the lumped model from what the EnergyPlus model is built from: floor area, volume and cover area from
  the typology geometry (`greenhouse_typology`, `greenhouse_idf.cover_area_m2`), cover U-value, glazed fraction and SHGC (`EnvelopeSpec`), infiltration, vent capacity (30 air changes per hour)
  and opening temperature (24 degC), heating set-point (12 degC) and capacity (100 W per m2 of floor), ground temperature (`ThermalSpec`), and the floor layer written into the IDF.
  The layout chosen in the interface therefore changes the results of **both** backends. A greenhouse request without a `greenhouse` block now means `SIMPLIFIED` with the default layout
  (its canonical request, hashes and results changed; open-field requests did not).
* **Two nodes.** Air and floor. The solar gain lands mostly on the floor (`solar_to_air_fraction`), which exchanges heat with the air and with the ground and gives it back slowly, as the
  EnergyPlus floor does. A single air node (first attempt) overheated in summer (+11 K at midday against +1.9 K). The step is the exact solution of the 2x2 linear system (`_two_node_step`, checked
  against an independent RK4 integration).
* **Same default operation as EnergyPlus.** Vents open by themselves above 24 degC when the outdoor air is cooler (30 air changes per hour), and an ideal heater holds 12 degC up to its capacity.
  Each stands down when a climate controller drives the same function (`ventilation_ach` and `heating` actuator keys).
* **Same command semantics.** A `VENTILATION` event is a fraction of the vent capacity in both backends; `ventilation_ach` carries physical air changes (the controller). `greenhouse_ventilation_fraction`
  is the vent **opening** in both (it used to be the exchanged fraction, about 0.95, in the simplified model).
* **The state carries the floor temperature** (`floor_temperature_c`, only when a model has one, so historical checkpoints keep their payload), so a what-if branch resumed from a checkpoint still equals the
  continuous run exactly.
* **The historical model is intact**: every new configuration field is inert at its default (bit-for-bit, tested), and the other phases (benchmarks, calibration, validation) still use it.
* **Constants the lumped model needs** (`src/greenhouse_reduced_model.json`, `CONSISTENCY_WITH_ENERGYPLUS_NOT_VALIDATED`): `incidence_factor` 0.71 (radiation reaching the floor per floor area, identified from EnergyPlus' transmitted
  radiation), `solar_to_air_fraction` 0.1, `floor_film_coefficient_w_m2k` 4.0. A sweep of these three on two windows found a flat optimum (scores 6.2-6.4 for neighbours), so they were not tuned further.

### The climate controller had to change with it

With realistic physics the phase 5.42 controller was **worse than not controlling** (36 degC against 30.6 degC): it started opening the vents at the crop's limit (28-32 degC) and, acting on the past hour, flipped
between "vents shut, air overheats" and "vents open, air collapses" (the vents cool faster than one step). Now it asks the greenhouse model itself what each action would do over the coming step (`ControlObservation.predict`,
with the forcing of that step as a perfect one-step forecast) and takes only what is still needed to keep the end of the step at the ceiling: vents, then extractors, then HVAC cooling, and the smallest heating power to
reach the stage minimum. The ceiling is the stage's `max_temp_c` minus `vents_start_margin_c` (4 K, a provisional design convention in `src/climate_control_config.json`, as a real greenhouse opens before the crop's limit).
Result on the tomato season to 10 May: maximum 28.0 degC, no heat stress, 2 vent flips (152 before), 1.6 MWh of cooling (28.5 MWh before). The rule-based ramps remain as the fallback for engines that cannot predict.

## How well the two models agree (`manual_phase5_44_greenhouse_consistency.py`, EnergyPlus 26.1)

| | winter (synthetic, 15 Feb-17 Mar) | | summer (real weather, El Ejido, Jun 2022) | |
|---|---|---|---|---|
| | lumped | EnergyPlus | lumped | EnergyPlus |
| radiation reaching the crop (W/m2) | 122.8 | 126.8 | 286.2 | 277.1 |
| indoor - outdoor, midday (K) | +4.6 | +6.5 | +2.5 | +1.9 |
| indoor - outdoor, night (K) | +5.5 | +5.3 | +1.2 | -2.0 |
| indoor minimum / maximum (degC) | 12.0 / 23.9 | 12.0 / 23.9 | 17.6 / 36.6 | 16.7 / 35.9 |
| indoor relative humidity (%) | 56 | 59 | 54 | 59 |
| heating energy (kWh) | 7352 | 6339 | 0 | 0 |
| hourly indoor temperature RMSE | 2.0 K | | 2.0 K | |

Mean change of the indoor temperature for a 72 h intervention (winter), lumped against EnergyPlus: vents fully open -4.0 against -4.1 K (heating +28 against +33 kW); 60 % shading -1.7 against -2.0 K;
radiation x0.5 -1.4 against -1.7 K; radiation x1.5 -0.1 against +0.8 K (the heater backs off and the vents open earlier; the sign differs in the mean).

Tolerances asserted: hourly RMSE < 3 K, midday gap < 2.5 K, radiation within 8 %, winter heating energy within 35 %, intervention gap < 1.5 K.

## Known residual differences

* A cold wave of -8 degC lowers the lumped interior more (-3.9 K) than EnergyPlus' (-1.7 K): at that load the 86 kW heater is at capacity in the lumped model and EnergyPlus loses less heat. Heating energy is 16 % higher.
* On summer nights EnergyPlus' interior is 2 K *below* the outside air (long-wave exchange of the cover with the sky, which the lumped model does not have); the lumped one is 1.2 K above.
* The vents are open more of the time in the lumped model (0.86 against 0.49 in summer): EnergyPlus decides per 15 minutes, this model per hour with a predicted end-of-step temperature.
* Humidity is 3-5 points lower (no crop feedback in either; vapour exchange differs slightly).
* Everything depends on provisional envelope values; both models can be consistently wrong about a real greenhouse.

## Tests

`tests/test_greenhouse_consistency.py` (solver against RK4 and the analytic equilibrium, thermostat, vents, controller stand-down, ventilation semantics, floor state, one geometry for both models, layout changes results, exact what-if),
`tests/test_intervention_effects.py` (directions and magnitudes in both greenhouse models, agreement with EnergyPlus when installed), `tests/test_climate_control.py` (controller with sized equipment, no vent flipping), and
the updated backend tests (`tests/test_energyplus_backend.py`). The API qualification suite compares its greenhouse case against a direct run with the same engine.

## Optional HVAC cooling in EnergyPlus

By default the EnergyPlus greenhouse only ventilates (its ideal-loads unit never cools: cooling set-point 60 degC), so its cooling-power series is zero. A request may add
`"greenhouse": {"backend": "ENERGYPLUS", "hvac": {"cooling_setpoint_c": 28, "cooling_capacity_w_m2": 150}}`: both values are the user's (no default; one without the other is rejected; set-point 5-50 degC, capacity up to 1000 W/m2),
written into the IDF as the cooling set-point schedule and the ideal-loads cooling capacity limit (`EvidenceStatus.USER_SUPPLIED`). The block is part of the request, the effective configuration and the hashes only when present.
It is a fixed rule over the whole run (EnergyPlus runs as a precomputed timeline), not the stage-aware climate controller, and it is rejected for the simplified model (cooled by the controller's equipment).
Example (El Ejido, June 2022, default layout): maximum air temperature 35.9 -> 29.1 degC with 28 degC / 150 W/m2, 11.1 MWh of cooling, peak 130 kW. No energy-cost series is produced for it (the cost needs the controller's energy estimate, which needs a COP).

## Optional crop feedback in the simplified greenhouse

`"greenhouse": {"backend": "SIMPLIFIED", "crop_exchange": true}` (checkbox "Crop feedback on the air" in the bench; default off, absent from requests that do not use it, so earlier hashes are unchanged; rejected for EnergyPlus and open field)
couples the crop to the lumped greenhouse the way `CropGreenhouseFeedbackLoop` does, inside the orchestrator step:

* **What the crop gives the air:** transpiration (the water balance evaluated in the indoor air, limited by what the air's vapour deficit can take), its latent heat (cools), leaf-air sensible heat (warms) and CO2 uptake from the growth carbon proxy.
  Fluxes are per m2 of floor and shared with the air column of the layout (volume / floor area), so a taller greenhouse dilutes them.
* **How:** a fixed three passes from the crop-free air (`GeometryGreenhouseEngine.EXCHANGE_ITERATIONS`); humidity feeds back negatively, so it settles. The exchange is a pure function of carried state (crop, soil, previous air) and the step's forcing, so
  runs are deterministic and a what-if branch from a checkpoint equals the continuous run exactly (tested). The engine receives the step time and the soil from the orchestrator only when the option is on.
* **What it does (tomato, El Ejido 2022, 15 Mar-30 Jun):** mean relative humidity 54.4 -> 60.9 %, peak air temperature 36.6 -> 35.2 degC, CO2 falls to about 90 ppm at its minimum (no enrichment, no respiration), cumulative biomass 275 -> 319 g/m2 (less heat and VPD stress). Runs take about twice as long.
* **Limits:** engineering defaults of `CropGreenhouseFeedbackConfiguration`, not calibrated; **no crop respiration or CO2 emission** (it would need a user-supplied rate; none is assumed); the crop's CO2 response in the growth model is `min(1, C/420)` (audit finding 6), so low CO2
  only penalises growth; the climate controller's one-step forecast ignores the crop's transpiration cooling (conservative); EnergyPlus cannot model it (precomputed timeline).
