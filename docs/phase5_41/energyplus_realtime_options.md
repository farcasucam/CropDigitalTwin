# Phase 5.41: EnergyPlus in interactive (lock-step) mode

Goal: drive EnergyPlus step by step from an external controller (UI/scenario service) instead of running a
whole period and reading results afterwards. Verified against EnergyPlus 26.1.0 at `C:\EnergyPlusV26-1-0`.
Evidence files: `realtime_spike/` (IDF, plugin, controller). These are spike artefacts with placeholder physics.

## Constraint that decides the choice

`.venv` is Python 3.13. EnergyPlus 26.1 ships `pyenergyplus` for **Python 3.12** (`python312.dll`, `python_lib`).
Only Python 3.9 is registered in the `py` launcher on this machine, so no 3.12 interpreter is available to import
`pyenergyplus` from outside. Python Plugins run on the interpreter bundled inside EnergyPlus, so they work today.

## 1. Runtime API (Python wraps EnergyPlus)

- `from pyenergyplus.api import EnergyPlusAPI` (add the EnergyPlus install dir to `sys.path`; interpreter must be 3.12).
- `api.runtime.run_energyplus(state, args)` **blocks the calling thread**; callbacks run on that same thread, inside
  the simulation. For interactivity, run it in a worker thread/process and exchange data with `queue`/`Event`.
  Blocking inside a callback pauses the simulation; `api.runtime.stop_simulation(state)` ends it.
- Data access: `api.exchange.get_variable_handle/get_variable_value`, `get_actuator_handle/set_actuator_value/reset_actuator`.
  Handles are valid only once `api.exchange.api_data_fully_ready(state)` is true.
- Pros: one process for lifecycle control, no sockets, direct Python objects, easy start/stop/pause.
- Cons here: needs a Python 3.12 environment with matching bindings (not provisioned); bindings tied to the EnergyPlus version.

## 2. Python Plugins (EnergyPlus runs Python)

- IDF objects: `PythonPlugin:SearchPaths` and `PythonPlugin:Instance` (module name, class name). The class extends
  `pyenergyplus.plugin.EnergyPlusPlugin` and implements `on_<calling_point>(self, state) -> int` (0 = ok, 1 = error).
- Same exchange API, via `self.api`. The plugin lives inside the EnergyPlus process and interpreter.
- Pros: no Python version coupling to the project interpreter; **verified working here**; the controller can be any
  process/language.
- Cons: to reach an external controller you must build the channel yourself (TCP/pipe) inside the plugin; debugging is
  harder; the plugin must be listed in the IDF (regeneration needed to change which handles it uses).

## Comparison for real-time data transfer

| Aspect | Runtime API | Python Plugin + socket bridge |
|---|---|---|
| Who owns the loop | Your Python (callback thread) | EnergyPlus; plugin blocks on the socket |
| Interpreter | Must be 3.12 matching E+ | Bundled by E+; controller can be 3.13 |
| Channel to the UI/service | In-process queues | TCP/pipe (JSON lines in the spike) |
| Pause | Block in callback | Controller withholds the reply |
| Cancel | `stop_simulation` | Close socket / kill process |
| Per-step overhead measured | not measured (no 3.12 available) | ~0.4 ms/step over loopback (672 steps in 0.26 s) |
| Setup effort here | Provision Python 3.12 | None beyond IDF objects |
| Rewind to a past time | Not supported | Not supported |

Neither approach can restart from a checkpoint: EnergyPlus only runs forward. Rewinding means re-running from t0.

## Recommendation for this project

Use the **Python Plugin + external controller** as the interactive channel now; keep the runtime API as an alternative
if a managed Python 3.12 worker is later provisioned. The controller side stays interpreter-independent and testable
without EnergyPlus (a fake peer can speak the same JSON-lines protocol).

### Verified minimal example (`realtime_spike/`)

`rt_bridge.py` (inside EnergyPlus): at the earliest zone-timestep point it sends state to the controller, blocks for the
reply and applies the weather override; at `BeginTimestepBeforePredictor` it applies the vent schedule and thermostat setpoint.
`controller.py` (venv Python 3.13): TCP server, starts EnergyPlus, replies per step.

Result of the spike (one week, 4 steps/hour, 672 exchanges):

| Run | Outdoor T max (C) | Zone T max / mean (C) |
|---|---|---|
| Controller opens vents above 26 C | 20.6 | 33.6 / 20.0 |
| Same + injected outdoor dry-bulb 38 C on 4-5 July | 38.0 | 40.7 / 25.0 |

The outdoor override shows in EnergyPlus's own reported `Site Outdoor Air Drybulb Temperature`, so it went through
the engine and not around it. Physics values are placeholders; this only proves the control path.

### Calling points

Order within a zone timestep (EnergyPlus event -> plugin hook / Runtime API callback):

1. `BeginZoneTimestepBeforeSetCurrentWeather` -> `on_begin_zone_timestep_before_set_current_weather`: where the
   `Weather Data` actuators (outdoor dry bulb, dew point, RH, solar, wind) are applied. Use it to inject exterior events.
2. `BeginTimestepBeforePredictor` -> `on_begin_timestep_before_predictor` /
   `callback_begin_system_timestep_before_predictor`: set schedule values, thermostat setpoints and
   `Zone Ventilation`/`Zone Infiltration` flow before the predictor computes zone loads.
3. `AfterPredictorBeforeHVACManagers` / `AfterPredictorAfterHVACManagers`: adjust node setpoints or ideal-loads
   inputs after loads are predicted, before/after the HVAC managers run.
4. `InsideSystemIterationLoop`: only for controls that must iterate with the HVAC solver.
5. `EndOfZoneTimestepAfterZoneReporting`: read reported results of the step just finished.

Zone values read at points 1-2 belong to the previous timestep. Plan for a one-step lag in feedback control.

### Actuators confirmed available in the spike model (`Output:EnergyManagementSystem, Verbose` -> `.edd`)

`Weather Data` (Outdoor Dry Bulb, Dew Point, Relative Humidity, Diffuse/Direct Solar, Wind Speed/Direction),
`Schedule:Constant` Schedule Value, `Zone Temperature Control` Heating/Cooling Setpoint, `Zone Ventilation` and
`Zone Infiltration` Air Exchange Flow Rate, `Ideal Loads Air System` supply temperature/humidity/flow, `System Node Setpoint`,
`Surface` Construction State. Window opening as an airflow-network opening factor needs `AirflowNetwork` objects (not tested).

### Open limits

- Overriding only `Outdoor Dry Bulb` leaves humidity inconsistent; a physically coherent event must also set dew point or RH.
- No restart: a "checkpoint" is a recorded command log replayed from t0. A week took ~0.3 s in the spike; season cost is untested.
- Not tested: the Runtime API example (no Python 3.12 here), airflow-network windows, CO2, moving shading, long runs,
  error paths (controller crash, plugin exception) and firewall behaviour on loopback.
- The `.edd` listing and the plugin were exercised on the spike model only, not on a parametric greenhouse IDF.

### Runtime API equivalent (NOT run here: needs Python 3.12)

```python
import sys, threading
sys.path.insert(0, r"C:\EnergyPlusV26-1-0")
from pyenergyplus.api import EnergyPlusAPI

api = EnergyPlusAPI()
state = api.state_manager.new_state()
h = {}

def before_predictor(s):
    ex = api.exchange
    if not ex.api_data_fully_ready(s):
        return
    if not h:
        h["t"] = ex.get_variable_handle(s, "Zone Mean Air Temperature", "GREENHOUSE ZONE")
        h["sp"] = ex.get_actuator_handle(s, "Zone Temperature Control", "Heating Setpoint", "GREENHOUSE ZONE")
    if ex.get_variable_value(s, h["t"]) < 15.0:
        ex.set_actuator_value(s, h["sp"], 18.0)
    else:
        ex.reset_actuator(s, h["sp"])

api.runtime.callback_begin_system_timestep_before_predictor(state, before_predictor)
worker = threading.Thread(target=lambda: api.runtime.run_energyplus(state, ["-w", "w.epw", "-d", "out", "rt.idf"]))
worker.start(); worker.join()
```
