# Phase 5.42: passive-first climate control, schedules and energy estimate

Status: **IN PROGRESS (partial)**. Domain rules, API, bench panel and tests exist for the simplified greenhouse backend. No calibration, no real data and no
validation is claimed (see `docs/scientific-limitations.md`).

## What it does

A request may carry a `control` block. Each actuator is `OFF`, `AUTO` or `SCHEDULE`:

| Actuator | Layer | `AUTO` rule (thresholds of the current stage, from `src/crop_config.json`) |
|---|---|---|
| `shade` | passive | radiation reaching the crop above `optimal_max_w_m2` ramps up to `shading_reduction_pct` at `photoinhibition_w_m2` |
| `vents` | passive | opens over the first part of the hot band `max_temp_c .. critical_heat_c`, only while the outside air is cooler |
| `extractors` | active (electric) | takes over once the vents are fully open |
| `cooling` | active (HVAC) | works beyond what vents and extractors can do |
| `heating` | active (HVAC) | holds `min_temp_c` |
| `irrigation` | passive | below `vwc_thresholds.optimal_min`, refills to `irrigation.target_vwc_after_irrigation` |

**Passive before active** is structural: the tiers are ordered, and an active tier starts only where the previous available tier ends. If an actuator is
`OFF` or has no equipment, the next tier starts earlier.

`SCHEDULE` repeats a daily window (`start_hour`..`end_hour`, UTC, may wrap midnight) over a range of days (`MM-DD`..`MM-DD`, may wrap the year end), for
example the shade screen every day from 11:00 to 17:00 between 06-15 and 09-15. A manual runtime event (`VENTILATION`, `SHADING`, ...) replaces the
controller for that actuator. Controls on a request without a `control` block (or with every actuator `OFF`) change nothing: hashes and checkpoints are
identical to before.

## Where each number comes from

* **Crop thresholds**: only from the crop catalogue JSON, per stage. A missing value is `null`: the rule that needs it does not act, the decision says
  `NO_THRESHOLD` and the interface lists what is missing. No default is invented.
* **Equipment** (capacities, COP, fan power): user-defined site inventory, supplied per request. An empty item makes that actuator `UNAVAILABLE`; an
  active actuator without its efficiency reports its energy as `null` ("not estimable") and never a substituted value. The bench offers a button that fills
  *illustrative* values (labelled "not sourced") to try the simulator.
* **Algorithm design** (`src/climate_control_config.json`, `DESIGN_CONVENTION_NOT_VALIDATED`): where the vents and extractors reach full output inside
  the hot band, and the HVAC gain. These are not agronomic values.
* **Energy** = electric/fuel input of the active equipment: extractors `level x power`, cooling `thermal kW / COP`, heating `thermal kW / efficiency`.
  Passive actuators spend none. It is an estimate from user-defined efficiencies.

## Controller properties

* **Stateless**: a decision depends only on the observation at the start of the step (`ControlObservation`). A what-if branch resumed from a checkpoint
  behaves exactly like the continuous run, and the control configuration is part of the resume identity.
* **Stable at one step per hour**: HVAC power compensates the disturbance (it estimates the temperature the greenhouse would settle at without HVAC from
  the previous step's HVAC power and the conductance) instead of feeding the measured temperature back. A plain proportional loop alternated in sign and
  overshot (43.6 degC inside against 34.8 degC outside in a tomato season) with the oversized equipment of the first trials; `tests/test_climate_control.py`
  closes the loop on a lumped greenhouse and checks that it settles.
* **Causality kept**: the controller only emits actuator commands; the physical model computes temperature, humidity and VPD. Controllers never write state.
* **Extension point for learned strategies**: `agri_twin.domain.climate_control.ClimateController` (`decide(ControlObservation) -> ControlDecision`).
  `ControlObservation.forecast` is reserved for the next outdoor hours; the rules do not use it. `ControlSession(config, crop, controller=...)` accepts any
  implementation.

## Limits

* Simplified greenhouse backend only. EnergyPlus runs as a precomputed timeline and cannot react to a controller: the request is rejected with a reason.
* The proportional HVAC leaves an offset from its target (it closes `hvac_gain` of the distance); a predictive controller can do better.
* Humidity control (venting for VPD) and CO2 are not controlled; wind affects only the forcing weather.
* The simplified greenhouse has a small thermal exchange area, so its solar gain is weak: results describe the software, not a real greenhouse.

## Interface (`/bench`)

Group "3 - Climate control": a mode per actuator (with a passive / uses-energy badge), the equipment list, daily schedules and warnings for anything
undefined. New trajectory variables (`control_vent_opening`, `control_extractor_level`, `control_layer`, `control_electric_kw`, `control_energy_kwh`,
`control_energy_kwh_cumulative`) appear only when control is on (`NOT_APPLICABLE` otherwise). Under the event bars of the timeline, one strip per actuator
shows what it really did over the run.

## Tests

`tests/test_climate_control.py` (rules, tiers, schedules, energy, validation, determinism, resume identity, manual override, closed-loop stability) and the
climate-control cases of `tests/test_bench.py`.
