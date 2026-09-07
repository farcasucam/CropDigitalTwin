"""Optional EnergyPlus Python API backend for the greenhouse contract.

This module executes EnergyPlus only when the runtime, Python API, IDD, IDF,
and weather file are explicitly configured. eppy remains responsible for IDF
variant generation in ``eppy_greenhouse``.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from agri_twin.domain.greenhouse import (
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    GreenhouseModelError,
    GreenhousePhysicalModel,
    MicroclimateState,
)
from agri_twin.domain.models import WeatherState


class EnergyPlusStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    MISCONFIGURED = "MISCONFIGURED"


@dataclass(frozen=True, slots=True)
class EnergyPlusAvailability:
    status: EnergyPlusStatus
    version: str | None = None
    executable: Path | None = None
    idd: Path | None = None
    python_api: bool = False
    detail: str = ""


def _find_executable() -> Path | None:
    configured = os.environ.get("ENERGYPLUS_EXECUTABLE")
    if configured:
        return Path(configured)
    found = shutil.which("energyplus") or shutil.which("EnergyPlus")
    if found:
        return Path(found)
    configured_idd = os.environ.get("ENERGYPLUS_IDD")
    if configured_idd:
        directory = Path(configured_idd).parent
        for name in ("energyplus.exe", "EnergyPlus.exe", "energyplus"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _find_idd(executable: Path | None) -> Path | None:
    configured = os.environ.get("ENERGYPLUS_IDD")
    if configured:
        return Path(configured)
    if executable:
        candidates = (executable.parent / "Energy+.idd", executable.parent / "EnergyPlus.idd")
        return next((path for path in candidates if path.is_file()), None)
    return None


def _runtime_version(executable: Path | None) -> str | None:
    if executable is None or not executable.is_file():
        return None
    try:
        result = subprocess.run((str(executable), "--version"), capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if text else None


def detect_energyplus() -> EnergyPlusAvailability:
    """Inspect installed runtime components without starting a simulation."""
    executable = _find_executable()
    idd = _find_idd(executable)
    try:
        importlib.import_module("pyenergyplus")
        importlib.import_module("pyenergyplus.api")
        python_api = True
    except ModuleNotFoundError:
        python_api = False
    except Exception as exc:
        return EnergyPlusAvailability(EnergyPlusStatus.INCOMPATIBLE, executable=executable, idd=idd, detail=f"Python API import failed: {exc}")

    version = _runtime_version(executable)
    if executable is None and not python_api:
        return EnergyPlusAvailability(EnergyPlusStatus.UNAVAILABLE, version, None, idd, False, "EnergyPlus executable and pyenergyplus are not available")
    if executable is None:
        return EnergyPlusAvailability(EnergyPlusStatus.UNAVAILABLE, version, None, idd, True, "EnergyPlus executable is not available")
    if not python_api:
        return EnergyPlusAvailability(EnergyPlusStatus.INCOMPATIBLE, version, executable, idd, False, "EnergyPlus executable found but pyenergyplus is not importable")
    if idd is None or not idd.is_file():
        return EnergyPlusAvailability(EnergyPlusStatus.MISCONFIGURED, version, executable, idd, True, "EnergyPlus IDD is missing; set ENERGYPLUS_IDD")
    return EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE, version, executable, idd, True)


class EnergyPlusBackendError(RuntimeError):
    """Raised when the optional EnergyPlus backend cannot execute."""


class EnergyPlusVariableUnavailable(EnergyPlusBackendError):
    """Raised when a requested EnergyPlus output variable is absent."""


# Names are the EnergyPlus Output:Variable names used by the Phase 5.7.2 IDF.
ENERGYPLUS_VARIABLES = {
    "air_temperature_c": "Zone Air Temperature",
    "relative_humidity_pct": "Zone Air Relative Humidity",
    "solar_radiation_w_m2": "Surface Window Transmitted Solar Radiation Rate",
    "ventilation_ach": "Zone Ventilation Air Change Rate",
    "infiltration_ach": "Zone Infiltration Air Change Rate",
    "heating_energy_j": "Zone Ideal Loads Supply Air Total Heating Energy",
    "cooling_energy_j": "Zone Ideal Loads Supply Air Total Cooling Energy",
    "co2_ppm": "Zone Air CO2 Concentration",
}


@dataclass(frozen=True, slots=True)
class EnergyPlusExecutionResult:
    variables: Mapping[str, float]
    applied_actuators: Mapping[str, float] = field(default_factory=dict)


class EnergyPlusRunner(Protocol):
    def run(self, *, weather: WeatherState, configuration: GreenhouseConfiguration, actuators: GreenhouseActuatorState, dt_seconds: float) -> EnergyPlusExecutionResult: ...


class PythonEnergyPlusRunner:
    """Real Python API boundary; it deliberately does not fall back to eppy."""

    def __init__(self, *, executable: str | Path, idf_path: str | Path, weather_path: str | Path, output_dir: str | Path, idd_path: str | Path | None = None) -> None:
        self.executable = Path(executable)
        self.idf_path = Path(idf_path)
        self.weather_path = Path(weather_path)
        self.output_dir = Path(output_dir)
        self.idd_path = Path(idd_path) if idd_path else None

    def run(self, *, weather: WeatherState, configuration: GreenhouseConfiguration, actuators: GreenhouseActuatorState, dt_seconds: float) -> EnergyPlusExecutionResult:
        del weather, configuration, dt_seconds
        try:
            api_module = importlib.import_module("pyenergyplus.api")
            api = api_module.EnergyPlusAPI()
        except Exception as exc:
            raise EnergyPlusBackendError(f"EnergyPlus Python API could not be loaded: {exc}") from exc
        if not self.executable.is_file() or not self.idf_path.is_file() or not self.weather_path.is_file():
            raise EnergyPlusBackendError("EnergyPlus executable, IDF, and weather file are required")
        if any((actuators.heating_kw, actuators.cooling_kw, actuators.ventilation_ach, actuators.shading_fraction, actuators.co2_supply_ppm)):
            raise EnergyPlusBackendError("the Phase 5.7.2 template exposes no verified EnergyPlus actuator handles")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        args = ["-w", str(self.weather_path), "-d", str(self.output_dir), str(self.idf_path)]
        state = api.state_manager.new_state()
        values: dict[str, float] = {}
        handles: dict[str, int] = {}

        def read_outputs(runtime_state: Any) -> None:
            if not api.exchange.api_data_fully_ready(runtime_state):
                return
            for key, variable_name in ENERGYPLUS_VARIABLES.items():
                handle = handles.setdefault(key, api.exchange.get_variable_handle(runtime_state, variable_name, "Greenhouse Zone"))
                if handle < 0:
                    continue
                values[key] = api.exchange.get_variable_value(runtime_state, handle)

        api.runtime.callback_end_zone_timestep_after_zone_reporting(state, read_outputs)
        result = api.runtime.run_energyplus(state, args)
        api.state_manager.delete_state(state)
        if result != 0:
            raise EnergyPlusBackendError(f"EnergyPlus execution failed with exit code {result}")
        missing = sorted(set(ENERGYPLUS_VARIABLES) - set(values))
        if missing:
            raise EnergyPlusVariableUnavailable(f"EnergyPlus output variables unavailable after run: {missing}")
        return EnergyPlusExecutionResult(values)


class EnergyPlusGreenhouseModel(GreenhousePhysicalModel):
    """Adapt EnergyPlus output variables to the shared microclimate state."""

    def __init__(self, runner: EnergyPlusRunner | None = None, availability: EnergyPlusAvailability | None = None, timestep_seconds: float = 3600.0) -> None:
        if timestep_seconds <= 0:
            raise GreenhouseModelError("timestep_seconds must be positive")
        self._availability = availability or detect_energyplus()
        self._runner = runner
        self._state: MicroclimateState | None = None
        self._timestep_seconds = timestep_seconds

    @property
    def availability(self) -> EnergyPlusAvailability:
        return self._availability

    def step(self, weather: WeatherState, configuration: GreenhouseConfiguration, actuators: GreenhouseActuatorState, crop_feedback: CropMicroclimateFeedback, dt_seconds: float, prior: MicroclimateState | None = None) -> MicroclimateState:
        del crop_feedback
        if not isinstance(configuration, GreenhouseConfiguration) or not isinstance(actuators, GreenhouseActuatorState):
            raise GreenhouseModelError("EnergyPlus backend requires greenhouse configuration and actuator state")
        if dt_seconds <= 0:
            raise GreenhouseModelError("dt_seconds must be positive")
        if self._runner is None:
            raise EnergyPlusBackendError(f"EnergyPlus backend is {self._availability.status.value}: {self._availability.detail}")
        result = self._runner.run(weather=weather, configuration=configuration, actuators=actuators, dt_seconds=dt_seconds)
        state = self._to_microclimate(result.variables, weather, actuators, dt_seconds)
        self._state = state
        self._timestep_seconds = dt_seconds
        return state

    def reset(self) -> None:
        self._state = None

    def state(self) -> MicroclimateState:
        if self._state is None:
            raise EnergyPlusBackendError("EnergyPlus backend has no state; execute step first")
        return self._state

    @staticmethod
    def _required(variables: Mapping[str, float], name: str) -> float:
        if name not in variables:
            raise EnergyPlusVariableUnavailable(f"EnergyPlus variable is unavailable: {name}")
        return float(variables[name])

    @classmethod
    def _to_microclimate(cls, variables: Mapping[str, float], weather: WeatherState, actuators: GreenhouseActuatorState, dt_seconds: float) -> MicroclimateState:
        temperature = cls._required(variables, "air_temperature_c")
        humidity = cls._required(variables, "relative_humidity_pct")
        solar = cls._required(variables, "solar_radiation_w_m2")
        ventilation = variables.get("ventilation_ach", variables.get("infiltration_ach", 0.0))
        heating = cls._required(variables, "heating_energy_j") / dt_seconds / 1000.0
        cooling = cls._required(variables, "cooling_energy_j") / dt_seconds / 1000.0
        co2 = cls._required(variables, "co2_ppm")
        saturation = 0.6108 * pow(2.718281828459045, 17.27 * temperature / (temperature + 237.3))
        vpd = max(0.0, saturation * (1.0 - humidity / 100.0))
        return MicroclimateState(
            air_temperature_c=temperature,
            relative_humidity_pct=humidity,
            vpd_kpa=vpd,
            pressure_hpa=weather.pressure_hpa,
            solar_radiation_w_m2=max(0.0, solar),
            par_umol_m2_s=max(0.0, solar * 2.04),
            co2_ppm=max(0.0, co2),
            wind_speed_m_s=weather.wind_speed_m_s,
            ventilation_fraction=max(0.0, float(ventilation)),
            heating_kw=max(0.0, heating),
            cooling_kw=max(0.0, cooling),
            shading_fraction=actuators.shading_fraction,
            temperature_c=temperature,
        )
