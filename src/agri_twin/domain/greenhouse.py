"""Lumped greenhouse microclimate and actuator model."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any, Mapping

from agri_twin.domain.models import ActuatorState, CropGrowthState, DerivedEnvironmentState, WeatherState


class GreenhouseModelError(ValueError):
    """Raised when greenhouse or actuator inputs are invalid."""


# Physical constants (FAO-56, Allen et al. 1998, for cp and lambda; standard
# thermodynamics for the water-vapour gas constant) and the ambient CO2
# reference already used by the model. Registered in ParameterRegistry.
AIR_DENSITY_KG_M3 = 1.2
AIR_SPECIFIC_HEAT_J_KG_K = 1013.0
LATENT_HEAT_VAPORIZATION_J_KG = 2_450_000.0
WATER_VAPOUR_GAS_CONSTANT_J_KG_K = 461.5
OUTDOOR_CO2_PPM = 420.0


def saturation_vapour_pressure_kpa(temperature_c: float) -> float:
    """Tetens saturation vapour pressure (kPa), the formula used across the project."""
    return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))


def vapour_pressure_deficit_kpa(temperature_c: float, relative_humidity_pct: float) -> float:
    return max(0.0, saturation_vapour_pressure_kpa(temperature_c) * (1.0 - relative_humidity_pct / 100.0))


def saturation_vapour_density_kg_m3(temperature_c: float) -> float:
    """Ideal-gas water-vapour density at saturation: e_s [Pa] / (R_v T [K])."""
    return saturation_vapour_pressure_kpa(temperature_c) * 1000.0 / (WATER_VAPOUR_GAS_CONSTANT_J_KG_K * (temperature_c + 273.15))


def vapour_density_kg_m3(temperature_c: float, relative_humidity_pct: float) -> float:
    return saturation_vapour_density_kg_m3(temperature_c) * relative_humidity_pct / 100.0


def vapour_deficit_density_kg_m3(temperature_c: float, vpd_kpa: float) -> float:
    """Water vapour the air can still hold (kg m-3) for a given VPD at temperature."""
    return max(0.0, vpd_kpa) * 1000.0 / (WATER_VAPOUR_GAS_CONSTANT_J_KG_K * (temperature_c + 273.15))


def _first_order(initial: float, outdoor: float, source: float, rate: float, dt_seconds: float) -> float:
    """Exact solution of dX/dt = source + rate (outdoor - X) over dt_seconds."""
    if rate <= 0.0:
        return initial + source * dt_seconds
    equilibrium = outdoor + source / rate
    return equilibrium + (initial - equilibrium) * math.exp(-rate * dt_seconds)


def _two_node_step(t_air: float, t_floor: float, g_out: float, t_out: float, g_floor: float, g_ground: float, t_ground: float, c_air: float, c_floor: float,
                   q_air: float, q_floor: float, dt_seconds: float) -> tuple[float, float]:
    """Exact solution over dt of the air + floor network (heat capacities in J K-1, conductances in W K-1, heat inputs in W):
    c_air dTa/dt = g_out (To - Ta) + g_floor (Tf - Ta) + q_air;  c_floor dTf/dt = g_floor (Ta - Tf) + g_ground (Tg - Tf) + q_floor."""
    a, b = -(g_out + g_floor) / c_air, g_floor / c_air
    c, d = g_floor / c_floor, -(g_floor + g_ground) / c_floor
    b1, b2 = (g_out * t_out + q_air) / c_air, (g_ground * t_ground + q_floor) / c_floor
    det = a * d - b * c
    eq_air, eq_floor = -(d * b1 - b * b2) / det, -(-c * b1 + a * b2) / det
    disc = math.sqrt(max((a - d) ** 2 + 4.0 * b * c, 0.0))  # > 0: the off-diagonal terms have the same sign
    l1, l2 = (a + d + disc) / 2.0, (a + d - disc) / 2.0
    e1, e2, denom = math.exp(l1 * dt_seconds), math.exp(l2 * dt_seconds), l1 - l2
    dx, dy = t_air - eq_air, t_floor - eq_floor
    return (eq_air + ((e1 * (a - l2) - e2 * (a - l1)) * dx + (e1 - e2) * b * dy) / denom,
            eq_floor + ((e1 - e2) * c * dx + (e1 * (d - l2) - e2 * (d - l1)) * dy) / denom)


@dataclass(frozen=True, slots=True)
class GreenhouseConfiguration:
    """Explicit engineering configuration for a simplified greenhouse model."""

    volume_m3: float = 1000.0
    solar_transmission: float = 0.78
    ventilation_ach: float = 3.0
    heat_loss_w_k: float = 80.0
    thermal_mass_kj_k: float = 2500.0
    orientation_deg: float = 180.0
    shading_fraction: float = 0.0
    co2_ppm_baseline: float = 420.0
    thermal_exchange_area_m2: float = 1.0
    mode: str = "passive_greenhouse"
    # Optional extensions (all inert at their defaults, which leave the historical model bit-for-bit unchanged). They let one lumped model carry what a detailed
    # one (EnergyPlus) has for the same greenhouse: heat exchange with the ground, passive venting and a thermostat.
    ground_conductance_w_k: float = 0.0          # floor-to-ground conductance (W K-1)
    ground_temperature_c: float = 15.0
    passive_vent_ach: float = 0.0                # air changes per hour of the roof vents fully open (also the capacity the "ventilation" command is a fraction of)
    passive_vent_open_above_c: float | None = None  # vents open on their own above this indoor temperature, while the outdoor air is cooler
    thermostat_setpoint_c: float | None = None   # an ideal heater holds this minimum temperature, up to its capacity
    heater_capacity_kw: float = 0.0
    vent_command_fraction: bool = False          # True: the "ventilation" actuator is a fraction of passive_vent_ach (otherwise raw air changes per hour)
    # Floor node (two-node model, active when floor_mass_kj_k > 0): thermal_mass_kj_k is then the AIR's capacity, the solar gain lands mostly on the floor, which exchanges
    # heat with the air (floor_conductance_w_k) and with the ground (ground_conductance_w_k) and gives it back slowly.
    floor_mass_kj_k: float = 0.0
    floor_conductance_w_k: float = 0.0
    solar_to_air_fraction: float = 1.0

    def __post_init__(self) -> None:
        if self.mode not in {"outdoor", "passive_greenhouse", "actuated_greenhouse"}:
            raise GreenhouseModelError("greenhouse mode is invalid")
        if self.floor_mass_kj_k < 0 or self.floor_conductance_w_k < 0 or not 0.0 <= self.solar_to_air_fraction <= 1.0:
            raise GreenhouseModelError("floor mass and conductance cannot be negative and the solar share to the air must be in [0, 1]")
        if self.floor_mass_kj_k > 0 and self.floor_conductance_w_k <= 0:
            raise GreenhouseModelError("a floor node needs a floor-to-air conductance")
        if self.ground_conductance_w_k < 0 or self.passive_vent_ach < 0 or self.heater_capacity_kw < 0:
            raise GreenhouseModelError("ground conductance, vent capacity and heater capacity cannot be negative")
        if self.thermostat_setpoint_c is not None and self.heater_capacity_kw <= 0:
            raise GreenhouseModelError("a thermostat needs a heater capacity")
        if self.passive_vent_open_above_c is not None and self.passive_vent_ach <= 0:
            raise GreenhouseModelError("passive venting needs a vent capacity")
        if not 0 < self.volume_m3 <= 100000 or self.thermal_mass_kj_k <= 0 or self.heat_loss_w_k < 0 or self.thermal_exchange_area_m2 <= 0:
            raise GreenhouseModelError("greenhouse configuration values are invalid")
        if not 0 < self.solar_transmission <= 1:
            raise GreenhouseModelError("solar_transmission must be in (0, 1]")
        if self.ventilation_ach < 0:
            raise GreenhouseModelError("ventilation_ach cannot be negative")


@dataclass(frozen=True, slots=True)
class GreenhouseActuatorState:
    """Actuator inputs; CO2 supply is a concentration increment per timestep."""
    heating_kw: float = 0.0
    cooling_kw: float = 0.0
    ventilation_ach: float = 0.0
    shading_fraction: float = 0.0
    co2_supply_ppm: float = 0.0
    misting_mm_h: float = 0.0
    default_vent_enabled: bool = True     # False when a controller drives the vents: the default passive venting then stands down
    default_heating_enabled: bool = True  # False when a controller drives the heating: the default thermostat then stands down

    def __post_init__(self) -> None:
        for name in ("heating_kw", "cooling_kw", "ventilation_ach", "shading_fraction", "co2_supply_ppm", "misting_mm_h"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise GreenhouseModelError(f"{name} must be finite")
        if self.heating_kw < 0 or self.cooling_kw < 0 or self.ventilation_ach < 0 or self.shading_fraction < 0 or self.shading_fraction > 1:
            raise GreenhouseModelError("greenhouse actuator values are invalid")
        if self.co2_supply_ppm < 0 or self.misting_mm_h < 0:
            raise GreenhouseModelError("CO2 and misting values cannot be negative")


@dataclass(frozen=True, slots=True)
class CropMicroclimateFeedback:
    """Crop exchange inputs; CO2 uptake is a concentration decrement per timestep."""
    leaf_area_index: float = 0.0
    transpiration_mm_h: float = 0.0
    intercepted_radiation_w_m2: float = 0.0
    latent_heat_w_m2: float = 0.0
    sensible_heat_w_m2: float = 0.0
    co2_uptake_ppm: float = 0.0

    def __post_init__(self) -> None:
        for name in ("leaf_area_index", "transpiration_mm_h", "intercepted_radiation_w_m2", "latent_heat_w_m2", "sensible_heat_w_m2", "co2_uptake_ppm"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise GreenhouseModelError(f"{name} must be finite")
        if self.leaf_area_index < 0 or self.transpiration_mm_h < 0 or self.intercepted_radiation_w_m2 < 0 or self.latent_heat_w_m2 < 0 or self.sensible_heat_w_m2 < 0 or self.co2_uptake_ppm < 0:
            raise GreenhouseModelError("crop feedback values cannot be negative")


@dataclass(frozen=True, slots=True)
class GreenhouseProfile:
    mode: str
    solar_transmission: float = 1.0
    thermal_mass_kj_k: float = 1000.0
    ventilation_ach: float = 2.0
    heat_loss_w_k: float = 100.0
    volume_m3: float = 1000.0
    outdoor_bypass: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"outdoor", "passive_greenhouse", "actuated_greenhouse"}:
            raise GreenhouseModelError("greenhouse mode is invalid")
        if not 0 < self.solar_transmission <= 1 or self.thermal_mass_kj_k <= 0 or self.ventilation_ach < 0 or self.heat_loss_w_k < 0 or self.volume_m3 <= 0:
            raise GreenhouseModelError("greenhouse profile values are invalid")


@dataclass(frozen=True, slots=True)
class ActuatorControl:
    """Normalized actuator command with capacity, limits, state, and use."""

    requested: float = 0.0
    minimum: float = 0.0
    maximum: float = 1.0
    capacity: float = 1.0
    enabled: bool = True
    failed: bool = False
    consumption_kwh: float = 0.0

    def __post_init__(self) -> None:
        if self.minimum > self.maximum or self.capacity < 0 or self.consumption_kwh < 0:
            raise GreenhouseModelError("actuator limits are invalid")
        if not self.minimum <= self.requested <= self.maximum:
            raise GreenhouseModelError("actuator request is outside limits")

    @property
    def actual(self) -> float:
        if not self.enabled or self.failed:
            return 0.0
        return min(self.capacity, max(self.minimum, self.requested))


@dataclass(frozen=True, slots=True, init=False)
class MicroclimateState:
    air_temperature_c: float
    relative_humidity_pct: float
    vpd_kpa: float
    pressure_hpa: float
    solar_radiation_w_m2: float
    par_umol_m2_s: float
    co2_ppm: float = 420.0
    wind_speed_m_s: float = 0.0
    ventilation_fraction: float = 0.0
    heating_kw: float = 0.0
    cooling_kw: float = 0.0
    shading_fraction: float = 0.0
    temperature_c: float = 0.0
    floor_temperature_c: float | None = None

    def __init__(
        self,
        temperature_c: float = 0.0,
        relative_humidity_pct: float = 0.0,
        vpd_or_radiation: float = 0.0,
        co2_ppm: float = 420.0,
        *,
        air_temperature_c: float | None = None,
        vpd_kpa: float | None = None,
        pressure_hpa: float = 1013.0,
        solar_radiation_w_m2: float | None = None,
        par_umol_m2_s: float = 0.0,
        wind_speed_m_s: float = 0.0,
        ventilation_fraction: float = 0.0,
        heating_kw: float = 0.0,
        cooling_kw: float = 0.0,
        shading_fraction: float = 0.0,
        radiation_w_m2: float | None = None,
        floor_temperature_c: float | None = None,
    ) -> None:
        air = temperature_c if air_temperature_c is None else air_temperature_c
        solar = vpd_or_radiation if solar_radiation_w_m2 is None else solar_radiation_w_m2
        if solar_radiation_w_m2 is None and radiation_w_m2 is not None:
            solar = radiation_w_m2
        final_vpd = vpd_kpa if vpd_kpa is not None else max(vpd_or_radiation, 0.0)
        object.__setattr__(self, "air_temperature_c", air)
        object.__setattr__(self, "relative_humidity_pct", relative_humidity_pct)
        object.__setattr__(self, "vpd_kpa", final_vpd)
        object.__setattr__(self, "pressure_hpa", pressure_hpa)
        object.__setattr__(self, "solar_radiation_w_m2", solar)
        object.__setattr__(self, "par_umol_m2_s", par_umol_m2_s)
        object.__setattr__(self, "co2_ppm", co2_ppm)
        object.__setattr__(self, "wind_speed_m_s", wind_speed_m_s)
        object.__setattr__(self, "ventilation_fraction", ventilation_fraction)
        object.__setattr__(self, "heating_kw", heating_kw)
        object.__setattr__(self, "cooling_kw", cooling_kw)
        object.__setattr__(self, "shading_fraction", shading_fraction)
        object.__setattr__(self, "temperature_c", air)
        object.__setattr__(self, "floor_temperature_c", floor_temperature_c)
        if floor_temperature_c is not None and not math.isfinite(floor_temperature_c):
            raise GreenhouseModelError("floor_temperature_c must be finite")
        self._validate()

    def _validate(self) -> None:
        for name in (
            "air_temperature_c", "relative_humidity_pct", "vpd_kpa", "pressure_hpa",
            "solar_radiation_w_m2", "par_umol_m2_s", "co2_ppm", "wind_speed_m_s",
            "ventilation_fraction", "heating_kw", "cooling_kw", "shading_fraction", "temperature_c",
        ):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise GreenhouseModelError(f"{name} must be finite")
        if not 0 <= self.relative_humidity_pct <= 100:
            raise GreenhouseModelError("relative_humidity_pct must be in [0, 100]")
        if self.vpd_kpa < 0 or self.pressure_hpa <= 0 or self.solar_radiation_w_m2 < 0 or self.par_umol_m2_s < 0 or self.co2_ppm < 0:
            raise GreenhouseModelError("microclimate state values are invalid")
        if self.wind_speed_m_s < 0 or self.ventilation_fraction < 0 or self.heating_kw < 0 or self.cooling_kw < 0 or self.shading_fraction < 0 or self.shading_fraction > 1:
            raise GreenhouseModelError("microclimate actuator values are invalid")

    @property
    def radiation_w_m2(self) -> float:
        return self.solar_radiation_w_m2

    @radiation_w_m2.setter
    def radiation_w_m2(self, value: float) -> None:
        object.__setattr__(self, "solar_radiation_w_m2", value)

    def to_dict(self) -> dict[str, float]:
        document = {
            "air_temperature_c": self.air_temperature_c,
            "relative_humidity_pct": self.relative_humidity_pct,
            "vpd_kpa": self.vpd_kpa,
            "pressure_hpa": self.pressure_hpa,
            "solar_radiation_w_m2": self.solar_radiation_w_m2,
            "par_umol_m2_s": self.par_umol_m2_s,
            "co2_ppm": self.co2_ppm,
            "wind_speed_m_s": self.wind_speed_m_s,
            "ventilation_fraction": self.ventilation_fraction,
            "heating_kw": self.heating_kw,
            "cooling_kw": self.cooling_kw,
            "shading_fraction": self.shading_fraction,
            "temperature_c": self.temperature_c,
        }
        if self.floor_temperature_c is not None:
            document["floor_temperature_c"] = self.floor_temperature_c
        return document


class GreenhouseMicroclimateState(MicroclimateState):
    """Backward-compatible alias for the common microclimate state."""


@dataclass(frozen=True, slots=True)
class GreenhouseMicroclimateResult:
    environment: DerivedEnvironmentState
    indoor_state: GreenhouseMicroclimateState
    actuator_consumption_kwh: float
    irrigation_applied_mm: float


PROFILES = {
    "outdoor": GreenhouseProfile("outdoor", outdoor_bypass=True),
    "passive_greenhouse": GreenhouseProfile("passive_greenhouse", 0.78, 2500, 3, 80, 1000),
    "actuated_greenhouse": GreenhouseProfile("actuated_greenhouse", 0.78, 3500, 3, 80, 1000),
}


class GreenhousePhysicalModel(ABC):
    """Common greenhouse microclimate contract used by simplified and optional backends."""

    @abstractmethod
    def step(
        self,
        weather: WeatherState,
        configuration: GreenhouseConfiguration,
        actuators: GreenhouseActuatorState,
        crop_feedback: CropMicroclimateFeedback,
        dt_seconds: float,
        prior: MicroclimateState | None = None,
    ) -> MicroclimateState:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    def commit(self, state: MicroclimateState) -> None:
        """Record an externally converged state (e.g. by the crop feedback loop)
        as the model's current state, replacing the last evaluated candidate."""
        self._state = state

    @abstractmethod
    def state(self) -> MicroclimateState:
        raise NotImplementedError


class SimplifiedGreenhouseModel(GreenhousePhysicalModel):
    """Fast, deterministic greenhouse microclimate model using the project's existing contracts."""

    def __init__(self, profiles: Mapping[str, GreenhouseProfile] | None = None, configuration: GreenhouseConfiguration | None = None) -> None:
        self._profiles = dict(PROFILES if profiles is None else profiles)
        self._configuration = configuration or GreenhouseConfiguration()
        self._state: MicroclimateState | None = None

    def profile_for(self, mode: str) -> GreenhouseProfile:
        try:
            return self._profiles[mode]
        except KeyError as exc:
            raise GreenhouseModelError(f"greenhouse profile not found: {mode}") from exc

    def _normalize_actuators(self, actuators: GreenhouseActuatorState | Mapping[str, Any] | None) -> GreenhouseActuatorState:
        if actuators is None:
            return GreenhouseActuatorState()
        if isinstance(actuators, GreenhouseActuatorState):
            return actuators
        if not isinstance(actuators, Mapping):
            raise GreenhouseModelError("actuators must be a mapping or GreenhouseActuatorState")

        shading = 0.0
        ventilation = 0.0
        heating = 0.0
        cooling = 0.0
        co2 = 0.0
        misting = 0.0
        vent_enabled = heat_enabled = True
        for name, value in actuators.items():
            if name == "ventilation_ach":
                vent_enabled = False
            elif name in {"heating", "heat"}:
                heat_enabled = False
            actual = value.actual if isinstance(value, ActuatorControl) else getattr(value, "actual_value", 0.0)
            if name in {"shade", "shading"}:
                shading = float(actual)
            elif name in {"ventilation", "vent", "ventilation_ach"}:
                ventilation = float(actual)
            elif name in {"heating", "heat"}:
                heating = float(actual)
            elif name in {"cooling", "cool"}:
                cooling = float(actual)
            elif name in {"co2", "carbon_dioxide"}:
                co2 = float(actual) * 100.0 if actual <= 1.0 else float(actual)
            elif name in {"misting", "humidify"}:
                misting = float(actual) * 10.0 if actual <= 1.0 else float(actual)
        return GreenhouseActuatorState(
            heating_kw=heating,
            cooling_kw=cooling,
            ventilation_ach=ventilation,
            shading_fraction=shading,
            co2_supply_ppm=co2,
            misting_mm_h=misting,
            default_vent_enabled=vent_enabled,
            default_heating_enabled=heat_enabled,
        )

    def step(
        self,
        weather: WeatherState,
        configuration: GreenhouseConfiguration | CropGrowthState | None = None,
        *args: Any,
        actuators: GreenhouseActuatorState | Mapping[str, Any] | None = None,
        crop_feedback: CropMicroclimateFeedback | None = None,
        dt_seconds: float = 3600.0,
        prior: MicroclimateState | None = None,
        **legacy: Any,
    ) -> MicroclimateState | GreenhouseMicroclimateResult:
        mode = legacy.pop("mode", None)
        prior = prior if prior is not None else legacy.pop("prior", self._state)
        legacy_actuators = legacy.pop("actuators", None)

        positional = list(args)
        if positional:
            if actuators is None and not isinstance(positional[0], (int, float)):
                actuators = positional[0]
            if crop_feedback is None and len(positional) >= 2 and not isinstance(positional[1], (int, float)):
                crop_feedback = positional[1]
            if len(positional) >= 1 and isinstance(positional[0], (int, float)):
                dt_seconds = float(positional[0])
            if len(positional) >= 2 and isinstance(positional[1], (int, float)) and actuators is not None:
                dt_seconds = float(positional[1])
            if len(positional) >= 3 and isinstance(positional[2], (int, float)):
                dt_seconds = float(positional[2])

        if isinstance(configuration, CropGrowthState):
            crop = configuration
            cfg = self._configuration if mode is None else GreenhouseConfiguration(mode=str(mode))
            feedback = crop_feedback or CropMicroclimateFeedback(leaf_area_index=getattr(crop, "leaf_area_index", 0.0))
            controls = self._normalize_actuators(actuators if actuators is not None else legacy_actuators)
            state = self._compute_state(weather, cfg, controls, feedback, float(dt_seconds), prior)
            self._state = state
            return GreenhouseMicroclimateResult(
                environment=DerivedEnvironmentState(
                    state.vpd_kpa,
                    max(0.0, state.air_temperature_c - 20.0) + state.solar_radiation_w_m2 / 1000.0,
                    saturation_vapour_pressure_kpa(state.air_temperature_c),
                    saturation_vapour_pressure_kpa(state.air_temperature_c) * state.relative_humidity_pct / 100.0,
                    max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
                    max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
                ),
                indoor_state=GreenhouseMicroclimateState(**state.to_dict()),
                actuator_consumption_kwh=0.0,
                irrigation_applied_mm=0.0,
            )

        cfg = configuration or self._configuration
        if mode is not None:
            cfg = replace(cfg, mode=str(mode))
        if not isinstance(cfg, GreenhouseConfiguration):
            raise GreenhouseModelError("configuration must be GreenhouseConfiguration")
        controls = self._normalize_actuators(actuators if actuators is not None else legacy_actuators)
        feedback = crop_feedback or CropMicroclimateFeedback()
        state = self._compute_state(weather, cfg, controls, feedback, float(dt_seconds), prior)
        self._state = state
        return state

    def _compute_state(
        self,
        weather: WeatherState,
        config: GreenhouseConfiguration,
        actuators: GreenhouseActuatorState,
        crop_feedback: CropMicroclimateFeedback,
        dt_seconds: float,
        prior: MicroclimateState | None = None,
    ) -> MicroclimateState:
        if not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise GreenhouseModelError("dt_seconds must be positive and finite")
        profile = self.profile_for(config.mode)
        if profile.outdoor_bypass:
            indoor = MicroclimateState(
                air_temperature_c=weather.temperature_c,
                relative_humidity_pct=weather.relative_humidity_pct,
                vpd_kpa=vapour_pressure_deficit_kpa(weather.temperature_c, weather.relative_humidity_pct),
                pressure_hpa=weather.pressure_hpa,
                solar_radiation_w_m2=weather.solar_radiation_w_m2,
                par_umol_m2_s=max(0.0, weather.solar_radiation_w_m2 * 2.04),
                co2_ppm=OUTDOOR_CO2_PPM,
                wind_speed_m_s=weather.wind_speed_m_s,
                ventilation_fraction=0.0,
                heating_kw=0.0,
                cooling_kw=0.0,
                shading_fraction=0.0,
                temperature_c=weather.temperature_c,
            )
            return indoor

        # Lumped, well-mixed air volume (Phase 5.30). Every balance is a linear
        # first-order ODE integrated exactly over dt, so no step size can overshoot:
        #   dX/dt = S + k (X_out - X),  k = ACH / 3600 s-1
        #   X(dt) = X_eq + (X0 - X_eq) exp(-k dt),  X_eq = X_out + S / k   (k > 0)
        #   X(dt) = X0 + S dt                                               (k = 0)
        # Crop fluxes and solar gain are per m2 of thermal_exchange_area_m2.
        shade = min(1.0, max(0.0, actuators.shading_fraction))
        air_changes_h = max(0.0, config.ventilation_ach) + max(0.0, actuators.ventilation_ach)
        exchange_rate_s = air_changes_h / 3600.0
        exchanged_fraction = 1.0 - math.exp(-exchange_rate_s * dt_seconds)
        transmission = config.solar_transmission * (1.0 - shade)
        indoor_radiation = weather.solar_radiation_w_m2 * transmission
        par = max(0.0, indoor_radiation * 2.04)
        area = config.thermal_exchange_area_m2
        volume = config.volume_m3
        previous_temperature = prior.temperature_c if prior is not None else weather.temperature_c
        previous_vapour = (
            vapour_density_kg_m3(prior.temperature_c, prior.relative_humidity_pct) if prior is not None
            else vapour_density_kg_m3(weather.temperature_c, weather.relative_humidity_pct)
        )
        outdoor_vapour = vapour_density_kg_m3(weather.temperature_c, weather.relative_humidity_pct)

        # Misting can only evaporate into the vapour deficit of the air at the
        # start of the step; the evaporated water humidifies and cools the air.
        misting_supplied_kg = actuators.misting_mm_h * area * dt_seconds / 3600.0
        misting_capacity_kg = max(0.0, saturation_vapour_density_kg_m3(previous_temperature) - previous_vapour) * volume
        misting_evaporated_kg = min(misting_supplied_kg, misting_capacity_kg)

        # Energy (W): solar gain + actuators + crop sensible - crop latent - misting latent.
        heat_sources_w = (
            indoor_radiation * area
            + actuators.heating_kw * 1000.0
            - actuators.cooling_kw * 1000.0
            + (crop_feedback.sensible_heat_w_m2 - crop_feedback.latent_heat_w_m2) * area
            - misting_evaporated_kg * LATENT_HEAT_VAPORIZATION_J_KG / dt_seconds
        )
        # Conductance to outdoor air (W K-1): cover heat loss + ventilation enthalpy exchange (+ the floor, when the configuration has one).
        heat_capacity_j_k = config.thermal_mass_kj_k * 1000.0
        ground_w_k = config.ground_conductance_w_k
        two_node = config.floor_mass_kj_k > 0.0
        solar_w = indoor_radiation * area
        previous_floor = (getattr(prior, "floor_temperature_c", None) if prior is not None else None)
        if previous_floor is None:
            previous_floor = config.ground_temperature_c

        def settle(ach: float, heater_w: float) -> tuple[float, float, float | None]:
            """Exact end-of-step air temperature, the conductance of the air node and the floor temperature (None without a floor node)."""
            air_w_k = AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_K * volume * (ach / 3600.0)
            outdoor_w_k = config.heat_loss_w_k + air_w_k
            if two_node:
                other_w = heat_sources_w - solar_w  # actuators, crop and misting terms heat the air directly
                air_end, floor_end = _two_node_step(previous_temperature, previous_floor, outdoor_w_k, weather.temperature_c, config.floor_conductance_w_k, ground_w_k,
                                                    config.ground_temperature_c, heat_capacity_j_k, config.floor_mass_kj_k * 1000.0,
                                                    other_w + heater_w + config.solar_to_air_fraction * solar_w, (1.0 - config.solar_to_air_fraction) * solar_w, dt_seconds)
                return air_end, outdoor_w_k + config.floor_conductance_w_k, floor_end
            total = outdoor_w_k + ground_w_k
            sink = weather.temperature_c if ground_w_k == 0.0 else (outdoor_w_k * weather.temperature_c + ground_w_k * config.ground_temperature_c) / total
            return _first_order(previous_temperature, sink, (heat_sources_w + heater_w) / heat_capacity_j_k, total / heat_capacity_j_k, dt_seconds), total, None

        # Default operation of a greenhouse that has one (same rules as the EnergyPlus model): vents open by themselves when it is too warm inside and cooler outside,
        # and an ideal heater holds the minimum temperature. Both stand down when a controller drives the same actuator.
        heater_w = 0.0
        base_ach = air_changes_h
        if config.passive_vent_open_above_c is not None and actuators.default_vent_enabled:
            free = settle(air_changes_h, 0.0)[0]
            if free > config.passive_vent_open_above_c and weather.temperature_c < free:
                air_changes_h += config.passive_vent_ach
        if config.thermostat_setpoint_c is not None and actuators.default_heating_enabled:
            free = settle(air_changes_h, 0.0)[0]
            if free < config.thermostat_setpoint_c:
                response_k_per_w = (settle(air_changes_h, 1000.0)[0] - free) / 1000.0  # air temperature gained per watt held for the whole step (the model is linear)
                heater_w = min(config.heater_capacity_kw * 1000.0, (config.thermostat_setpoint_c - free) / response_k_per_w)
        if air_changes_h != base_ach:
            exchange_rate_s = air_changes_h / 3600.0
            exchanged_fraction = 1.0 - math.exp(-exchange_rate_s * dt_seconds)
        temperature, conductance_w_k, floor_temperature = settle(air_changes_h, heater_w)
        # With a vent capacity the reported ventilation is the OPENING (0..1 of the vents), as in EnergyPlus; otherwise the historical exchanged fraction.
        if config.passive_vent_ach > 0.0:
            exchanged_fraction = min(1.0, max(0.0, (air_changes_h - max(0.0, config.ventilation_ach)) / config.passive_vent_ach))

        # Water vapour (kg m-3): transpiration + evaporated misting, exchanged with
        # outdoor air; vapour above saturation at the new temperature condenses.
        vapour_source = (crop_feedback.transpiration_mm_h * area / 3600.0 + misting_evaporated_kg / dt_seconds) / volume
        vapour = _first_order(previous_vapour, outdoor_vapour, vapour_source, exchange_rate_s, dt_seconds)
        saturation_vapour = saturation_vapour_density_kg_m3(temperature)
        vapour = min(max(0.0, vapour), saturation_vapour)
        humidity = min(100.0, max(0.0, 100.0 * vapour / saturation_vapour))
        vpd = vapour_pressure_deficit_kpa(temperature, humidity)

        # CO2 (ppm): supply and crop uptake are per-timestep increments (contract).
        previous_co2 = prior.co2_ppm if prior is not None else config.co2_ppm_baseline
        co2_source = (actuators.co2_supply_ppm - crop_feedback.co2_uptake_ppm) / dt_seconds
        co2 = _first_order(previous_co2, OUTDOOR_CO2_PPM, co2_source, exchange_rate_s, dt_seconds)
        return MicroclimateState(
            air_temperature_c=temperature,
            relative_humidity_pct=humidity,
            vpd_kpa=vpd,
            pressure_hpa=weather.pressure_hpa,
            solar_radiation_w_m2=indoor_radiation,
            par_umol_m2_s=par,
            co2_ppm=max(0.0, co2),
            wind_speed_m_s=weather.wind_speed_m_s,
            ventilation_fraction=exchanged_fraction,
            heating_kw=actuators.heating_kw + heater_w / 1000.0,
            cooling_kw=actuators.cooling_kw,
            shading_fraction=shade,
            temperature_c=temperature,
            floor_temperature_c=floor_temperature,
        )

    def reset(self) -> None:
        self._state = None

    def state(self) -> MicroclimateState:
        if self._state is None:
            return MicroclimateState(0.0, 0.0, 0.0, 420.0, pressure_hpa=1013.0, solar_radiation_w_m2=0.0, par_umol_m2_s=0.0)
        return self._state

    @staticmethod
    def _control(value: ActuatorControl | ActuatorState) -> ActuatorControl:
        if isinstance(value, ActuatorControl):
            return value
        return ActuatorControl(value.actual_value, value.min_value, value.max_value, value.max_value, value.enabled, value.failed)

    @staticmethod
    def _result(indoor: GreenhouseMicroclimateState, weather: WeatherState, consumption: float, irrigation: float) -> GreenhouseMicroclimateResult:
        saturation = saturation_vapour_pressure_kpa(indoor.temperature_c)
        vapor = saturation * indoor.relative_humidity_pct / 100.0
        vpd = max(0.0, saturation - vapor)
        environment = DerivedEnvironmentState(vpd, max(0.0, indoor.temperature_c - 20.0) + indoor.radiation_w_m2 / 1000.0, saturation, vapor, max(0.0, vpd * 0.15 + indoor.radiation_w_m2 * 0.00005), max(0.0, vpd * 0.15 + indoor.radiation_w_m2 * 0.00005))
        return GreenhouseMicroclimateResult(environment, indoor, consumption, irrigation)


def derived_environment(state: MicroclimateState) -> DerivedEnvironmentState:
    """Derived environment (VPD, stress indices) of a microclimate state; shared by every greenhouse backend."""
    return DerivedEnvironmentState(
        state.vpd_kpa,
        max(0.0, state.air_temperature_c - 20.0) + state.solar_radiation_w_m2 / 1000.0,
        saturation_vapour_pressure_kpa(state.air_temperature_c),
        saturation_vapour_pressure_kpa(state.air_temperature_c) * state.relative_humidity_pct / 100.0,
        max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
        max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
    )


class GreenhouseMicroclimateEngine(SimplifiedGreenhouseModel):
    """Backward-compatible alias of the simplified greenhouse engine."""

    def advance(
        self,
        weather: WeatherState,
        crop: CropGrowthState,
        dt_seconds: float,
        mode: str = "outdoor",
        actuators: Mapping[str, ActuatorControl | ActuatorState] | None = None,
        prior: GreenhouseMicroclimateState | None = None,
    ) -> GreenhouseMicroclimateResult:
        if prior is None:
            self._state = None
        cfg = GreenhouseConfiguration(mode=mode)
        controls = self._normalize_actuators(actuators)
        feedback = CropMicroclimateFeedback(leaf_area_index=crop.leaf_area_index)
        state = self.step(weather, cfg, controls, feedback, dt_seconds, prior=prior)
        consumption = 0.0
        if actuators:
            for value in actuators.values():
                if isinstance(value, ActuatorControl):
                    consumption += value.consumption_kwh if getattr(value, "enabled", True) and not getattr(value, "failed", False) else 0.0
        environment = derived_environment(state)
        return GreenhouseMicroclimateResult(
            environment=environment,
            indoor_state=GreenhouseMicroclimateState(**state.to_dict()),
            actuator_consumption_kwh=consumption,
            irrigation_applied_mm=0.0,
        )
