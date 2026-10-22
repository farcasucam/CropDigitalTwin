# Phase 5.46: climate control on EnergyPlus in lock-step

Status: **COMPLETE (software qualification)**. The controller of phase 5.42 can now act on the EnergyPlus greenhouse hour by hour. Not validated against a real greenhouse (see `docs/scientific-limitations.md`).

## Why

EnergyPlus used to run as a timeline computed **before** the run, so anything that had to react to its state (a controller) was refused. Lock-step runs EnergyPlus as a child process and advances it one simulated hour per call, so the
controller decides from the state at the end of the previous hour, exactly as with the simplified model. The mechanism was verified in `docs/phase5_41` (Python Plugin bridge over loopback TCP); this phase makes it the production path.

## How it works

* `infrastructure/energyplus_lockstep.py`: `LockstepSession` writes the IDF (`RunSpec.lockstep=True`), the weather file and a Python Plugin next to it, starts EnergyPlus, accepts the plugin's connection and exposes `advance(label, commands)`:
  one hour = four zone timesteps with the commands held. The plugin runs inside EnergyPlus' bundled Python (the project's interpreter does not matter). Errors (EnergyPlus fails, the bridge stops answering) become `EnergyPlusTimelineError` with EnergyPlus' own message.
* **Faithful reading of results.** Temperature, solar gain and heating/cooling power are read at the end of the zone timestep; relative humidity and ventilation rate are the mean over the system timesteps inside it, as EnergyPlus reports them (found by
  comparison: reading them at the last system timestep differed by up to 18 points of humidity). With default commands the session reproduces the open-loop timeline to 1e-13 in every variable (tested).
* **Actuators the controller drives** (generated IDF objects): the passive venting on/off, the commanded vent opening, extra air changes (vents beyond the design opening, extractors), a signed power in kW into the zone air (`OtherEquipment`, all convective: a
  heater or a cooler as a heat source, like the lumped model) and the ideal-loads set-points (each driven function makes the default thermostat stand down). Each is verified to move the temperature the right way and by a plausible amount.
* **Not drivable: the shade screen.** EnergyPlus gets shading as a scaling of the weather file fixed before the run. A controller asking for it (`control.actuators.shade` not OFF) is refused with that reason; manual SHADING events still work (they are in the file).
* **Forecast model.** EnergyPlus cannot predict, so the controller looks one step ahead with the lumped model of the **same greenhouse** (phase 5.44), fed with EnergyPlus' own air state; its floor node (which EnergyPlus' state does not expose) is kept in step by running it alongside,
  and the controller corrects every forecast by an exponentially smoothed bias (`FORECAST_BIAS_SMOOTHING`, 0.7: a design convention of this adapter, not a physical value) equal to the last difference between EnergyPlus and the forecast for the commands actually sent. A real controller has an imperfect model too.
  Without the bias correction the forecast model's different response to cooling made the controller over-cool (indoor 6-12 degC with 30 degC outside); without any forecast the ramp rules oscillated and the air reached 59 degC.
* **Checkpoints and what-if.** EnergyPlus only runs forward, so a run resumed from a checkpoint (what-if branches) first **replays the run from the campaign start** up to the checkpoint on the same session with the same controller, checks that it ends in exactly
  the checkpoint's state (otherwise the run fails with that reason) and continues. Branch events start at or after the checkpoint, so the prefix is identical. What-if equals the continuous run exactly (tested).
* The session is closed (process terminated, files removed) in every case: completion, failure, cancellation.

## Result (tomato, El Ejido, 1 May-15 June 2022, vents/extractors/cooling/heating on AUTO with the illustrative equipment)

| | open loop | controller |
|---|---|---|
| EnergyPlus: hours above 28 degC | 119 | 34 (lock-step) |
| EnergyPlus: maximum / mean air temperature | 33.0 / 22.9 | 32.0 / 22.3 degC |
| EnergyPlus: cooling energy | 0 | 20.5 MWh (estimated input energy 8.8 MWh) |
| lumped model: hours above 28 degC | 172 | 0 |
| lumped model: cooling energy | 0 | 30.6 MWh |

The controller works on EnergyPlus but less tightly than on the lumped model: its forecasts come from a model that differs from EnergyPlus (hourly RMSE about 2 K, phase 5.44). A run takes about 6.5 s for 46 days.

## Limits

* The shade screen is not drivable; no crop feedback and no CO2 in EnergyPlus (as before).
* The forecast is imperfect and uses a lumped model with provisional values; the controller's ceiling margin (phase 5.44) absorbs part of it, not all.
* Replay makes a what-if branch cost the prefix again (three EnergyPlus runs instead of one for a season); runs are short (seconds).
* EnergyPlus must be 26.1 and its bundled Python plugin support must work (verified on this installation); a firewall that blocks loopback sockets would stop it.

## Tests

`tests/test_energyplus_lockstep.py`: actuator-to-command mapping and stand-down rules; the shade is refused; open-loop requests unchanged; with default commands the session equals the open-loop timeline to 1e-9; every actuator moves the zone correctly; hours must be requested in order and closing ends the process;
a controlled run is deterministic and acts; what-if equals the continuous run; a checkpoint from another controller is refused. (EnergyPlus-dependent tests skip when it is not installed.)
