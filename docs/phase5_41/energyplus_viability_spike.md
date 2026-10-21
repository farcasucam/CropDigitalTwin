# Phase 5.41, step 1: EnergyPlus viability spike

Scope: can EnergyPlus 26.1.0 (`C:\EnergyPlusV26-1-0`) be driven as an external process from this repo?
Nothing in `src/` was changed. Evidence was produced in a scratch directory; the working IDF is kept here as
`energyplus_26_1_spike.idf` (spike only, not a validated greenhouse model; all values are placeholders).

## Results

| Question | Result |
|---|---|
| Does the executable run? | Yes. `energyplus.exe -w <epw> -d <out> <idf>` completes. A one-week, 4-steps/hour run takes ~0.25 s. |
| Is `templates/greenhouse/greenhouse_template.idf` runnable? | **No, for any version.** Version 23.1 is declared, but `RunPeriod` and `ZoneHVAC:IdealLoadsAirSystem` have shifted fields, there is no `ZoneHVAC:EquipmentList`/`EquipmentConnections`/thermostat, and glazing is used as an opaque-surface construction. It has never run in EnergyPlus. |
| Version transition 23.1 -> 26.1 | Works with the bundled `Transition-V*.exe` chain, but only when run **from `PreProcess\IDFVersionUpdater`** (they need the `V*-Energy+.idd` files beside them). It cannot repair the field-order defects above. |
| Better path | Generate IDFs programmatically for 26.1 (also needed for parametric geometry) instead of transitioning the old template. |
| Python API needed? | No. Process execution plus SQLite/CSV output is enough. `.venv` is Python 3.13, EnergyPlus ships 3.12 bindings. |
| 26.1 schema changes hit | `BuildingSurface:Detailed` has a `Space Name` field after `Zone Name`; `RunPeriod` has Begin/End Year fields. |

## Physical sanity check (spike model, SF TMY3 weather, 1-7 July)

Single zone 10 x 8 x 4 m, simple-glazing cover (placeholder U 5.8, SHGC 0.80), ideal-loads heater (setpoint 12 C),
vents driven by the `Vent Opening` schedule (30 ACH when fully open).

| Run | Outdoor T (C) | Indoor T min / mean / max (C) | Mean heating energy per timestep (J) |
|---|---|---|---|
| Vents closed (`Vent Opening` = 0) | 11.1 / 15.2 / 20.6 | 12.0 / 22.9 / 39.9 | 1103 |
| Vents open (`Vent Opening` = 1) | same | 12.0 / 16.6 / 24.1 | 21209 (~19x) |

The intervention changes the interior in the expected direction (lower peak, more heating need). This shows the
mechanism works; it is **not** a validated result for any real greenhouse.

## Findings that constrain the design

1. **Actuators are schedule-driven.** Window opening, heater setpoint and shading go into the IDF as schedules.
   An intervention means regenerating the IDF and rerunning, not changing a value mid-run. EnergyPlus has no restart
   from a checkpoint; a checkpointed branch must rerun from the start (or from a warm-up) with the new schedules.
   The UI must say it is recomputing.
2. **Weather must be an EPW.** The project simulates from local CSV (`data/weather/`). A CSV -> EPW writer is required,
   with explicit handling of the fields CSV lacks (this is a design item, not yet done).
3. **Output variable names in `ENERGYPLUS_VARIABLES` are wrong for 26.1.**
   `Zone Ventilation Air Change Rate` and `Zone Infiltration Air Change Rate` are not generated. Real names include
   `Zone Ventilation Standard Density Air Change Rate` and `Infiltration Standard Density Air Change Rate`
   (verified in the run's `.rdd`). Not changed yet.
4. **No CO2 without a contaminant model.** `Zone Air CO2 Concentration` needs `ZoneAirContaminantBalance` and a CO2 source.
   Until modelled, CO2 must display as unavailable, not zero.
5. **Existing runner only keeps the last timestep.** `PythonEnergyPlusRunner` stores one value per variable; a time series
   needs a new runner that reads `eplusout.sql`.
6. **Lumped single zone.** Geometry only affects EnergyPlus through areas, volume and orientation. No spatial distribution
   or per-plant microclimate exists.
7. Warnings seen: no ground temperatures input (needs `Site:GroundTemperature:BuildingSurface`); `Schedule:Constant`
   without a type-limits name for the thermostat type.

## Open items before step 2

- Decide the CSV -> EPW strategy and which EPW fields are filled with documented defaults.
- Decide the runner contract (process + SQLite) and how `detect_energyplus()` locates the install without env vars
  (probe `C:\EnergyPlus*` and report the provenance of the path).
- Material and cover properties for the manufacturer typologies are unknown; they stay provisional with provenance.
