# Phase 5.7.3: EnergyPlus greenhouse backend

## Architecture

The optional backend implements the existing `GreenhousePhysicalModel` contract:

`WeatherState + GreenhouseConfiguration + GreenhouseActuatorState + CropMicroclimateFeedback + dt_seconds -> EnergyPlusGreenhouseModel -> MicroclimateState`

EnergyPlus does not own or advance `SimulationClock`. A
`SimulationScheduler` task may call the backend with an externally selected
`timestep`; the backend never reads wall-clock time or advances the clock.
`CropGrowthEngine` is not imported or coupled to this adapter. Crop feedback is
accepted for the contract and intentionally not applied in 5.7.3.

## Availability and installation

`detect_energyplus()` returns `AVAILABLE`, `UNAVAILABLE`, `INCOMPATIBLE`, or
`MISCONFIGURED`, with version, executable, IDD, Python API, and diagnostic
reason. The core package does not require EnergyPlus or `pyenergyplus`.

Configure installations without hardcoding a version:

```powershell
$env:ENERGYPLUS_EXECUTABLE = "C:\EnergyPlusV26-1-0\energyplus.exe"
$env:ENERGYPLUS_IDD = "C:\EnergyPlusV26-1-0\Energy+.idd"
```

The executable may also be found on `PATH`; the IDD is read from
`ENERGYPLUS_IDD` or next to that executable. Future installation versions only
require updating environment configuration. `pyenergyplus` must come from the
same EnergyPlus installation and version family as the executable.

The current audit found no EnergyPlus executable, no `pyenergyplus` module, and
no project IDD. The IDD files found under eppy's resources are editor schemas,
not proof that an EnergyPlus runtime is installed.

## eppy versus EnergyPlus API

Phase 5.7.2's `EppyGreenhouseBuilder` remains responsible for loading and
modifying IDF variants. This backend never imports eppy for simulation.
`PythonEnergyPlusRunner` is the runtime boundary for `pyenergyplus.api`: it
creates an API state, registers a zone-timestep callback, reads output handles,
runs EnergyPlus, and reports non-zero runtime failures.

## Variables

The requested names are the actual `Output:Variable` names declared in the
Phase 5.7.2 template:

| State field | EnergyPlus variable |
|---|---|
| air temperature | `Zone Air Temperature` |
| relative humidity | `Zone Air Relative Humidity` |
| solar radiation | `Surface Window Transmitted Solar Radiation Rate` |
| ventilation | `Zone Ventilation Air Change Rate` |
| fallback air exchange | `Zone Infiltration Air Change Rate` |
| heating energy | `Zone Ideal Loads Supply Air Total Heating Energy` |
| cooling energy | `Zone Ideal Loads Supply Air Total Cooling Energy` |
| CO2 | `Zone Air CO2 Concentration` |

Missing handles are reported as `EnergyPlusVariableUnavailable`; the adapter
never replaces them with fabricated values. Heating and cooling energy are
converted from joules per external timestep to kW. VPD and PAR are derived from
returned temperature, humidity, and solar radiation using the common state
conversion already used by the project.

## Actuators and timestep

The current template contains no verified EnergyPlus actuator handles. The
real runner therefore rejects non-zero heating, cooling, ventilation, shading,
or CO2 commands instead of silently applying them to another object. The
adapter still passes `GreenhouseActuatorState` through its contract and unit
tests verify that mapping boundary. A future phase must add and validate actual
EnergyPlus actuator objects/API component-control-type triples before enabling
those commands.

`dt_seconds` is the external Digital Twin timestep. EnergyPlus may use its own
internal substeps, but the callback result is returned for that external call.
The current template's `Timestep` object requests four internal steps per hour;
this does not replace the Digital Twin clock.

## Failure behavior and tests

When EnergyPlus is absent, `EnergyPlusGreenhouseModel.availability` exposes the
exact diagnostic and `step()` raises `EnergyPlusBackendError`. The application
can inspect availability and retain the simplified 5.7.1 backend. Runtime
errors and missing variables are explicit. Unit tests use a fake runner only to
exercise conversion, contract, clock, scheduler, and error handling; the
manual diagnostic never fakes an EnergyPlus run.

```powershell
python -m pytest tests/test_energyplus_greenhouse.py
python manual_phase5_7_3_energyplus_test.py
```

## Scientific status and limits

This is an optional execution adapter, not a calibration or validation result.
The greenhouse geometry, material, HVAC, and exchange values remain engineering
placeholders from 5.7.2. Crop transpiration, sensible/latent crop heat, CO2
uptake, iterative crop-microclimate feedback, and EnergyPlus-versus-simplified
comparison are explicitly deferred to later phases.
