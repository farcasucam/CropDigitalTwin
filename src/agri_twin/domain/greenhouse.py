"""Lumped greenhouse microclimate and actuator model."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

from agri_twin.domain.models import ActuatorState, CropGrowthState, DerivedEnvironmentState, WeatherState


class GreenhouseModelError(ValueError):
    """Raised when greenhouse or actuator inputs are invalid."""


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
    mode: str = "passive_greenhouse"

    def __post_init__(self) -> None:
        if self.mode not in {"outdoor", "passive_greenhouse", "actuated_greenhouse"}:
            raise GreenhouseModelError("greenhouse mode is invalid")
        if not 0 < self.volume_m3 <= 100000 or self.thermal_mass_kj_k <= 0 or self.heat_loss_w_k < 0:
            raise GreenhouseModelError("greenhouse configuration values are invalid")
        if not 0 < self.solar_transmission <= 1:
            raise GreenhouseModelError("solar_transmission must be in (0, 1]")
        if self.ventilation_ach < 0:
            raise GreenhouseModelError("ventilation_ach cannot be negative")


@dataclass(frozen=True, slots=True)
class GreenhouseActuatorState:
    heating_kw: float = 0.0
    cooling_kw: float = 0.0
    ventilation_ach: float = 0.0
    shading_fraction: float = 0.0
    co2_supply_ppm: float = 0.0
    misting_mm_h: float = 0.0

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
        return {
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
    ) -> MicroclimateState:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

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
        for name, value in actuators.items():
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
        )

    def step(
        self,
        weather: WeatherState,
        configuration: GreenhouseConfiguration | CropGrowthState | None = None,
        *args: Any,
        actuators: GreenhouseActuatorState | Mapping[str, Any] | None = None,
        crop_feedback: CropMicroclimateFeedback | None = None,
        dt_seconds: float = 3600.0,
        **legacy: Any,
    ) -> MicroclimateState | GreenhouseMicroclimateResult:
        mode = legacy.pop("mode", None)
        prior = legacy.pop("prior", self._state)
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
                    0.6108 * math.exp(17.27 * state.air_temperature_c / (state.air_temperature_c + 237.3)),
                    0.6108 * math.exp(17.27 * state.air_temperature_c / (state.air_temperature_c + 237.3)) * state.relative_humidity_pct / 100.0,
                    max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
                    max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
                ),
                indoor_state=GreenhouseMicroclimateState(**state.to_dict()),
                actuator_consumption_kwh=0.0,
                irrigation_applied_mm=0.0,
            )

        cfg = configuration or self._configuration
        if mode is not None:
            cfg = GreenhouseConfiguration(
                volume_m3=cfg.volume_m3,
                solar_transmission=cfg.solar_transmission,
                ventilation_ach=cfg.ventilation_ach,
                heat_loss_w_k=cfg.heat_loss_w_k,
                thermal_mass_kj_k=cfg.thermal_mass_kj_k,
                orientation_deg=cfg.orientation_deg,
                shading_fraction=cfg.shading_fraction,
                co2_ppm_baseline=cfg.co2_ppm_baseline,
                mode=str(mode),
            )
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
                vpd_kpa=0.0,
                pressure_hpa=weather.pressure_hpa,
                solar_radiation_w_m2=weather.solar_radiation_w_m2,
                par_umol_m2_s=max(0.0, weather.solar_radiation_w_m2 * 2.04),
                co2_ppm=420.0,
                wind_speed_m_s=weather.wind_speed_m_s,
                ventilation_fraction=0.0,
                heating_kw=0.0,
                cooling_kw=0.0,
                shading_fraction=0.0,
                temperature_c=weather.temperature_c,
            )
            return indoor

        shade = min(1.0, max(0.0, actuators.shading_fraction))
        ventilation = max(0.0, actuators.ventilation_ach)
        transmission = config.solar_transmission * (1.0 - shade)
        indoor_radiation = weather.solar_radiation_w_m2 * transmission
        par = max(0.0, indoor_radiation * 2.04)
        delta_t = weather.temperature_c - 20.0
        thermal_gain = indoor_radiation * 0.004 + actuators.heating_kw * 10.0 - actuators.cooling_kw * 10.0 - config.heat_loss_w_k * max(-10.0, min(10.0, delta_t)) / 100.0
        ventilation_ratio = min(1.0, ventilation / max(profile.ventilation_ach, 1e-6))
        base_temperature = weather.temperature_c + thermal_gain / max(config.volume_m3 / 10.0, 1.0) * (dt_seconds / 3600.0)
        previous_temperature = prior.temperature_c if prior is not None else weather.temperature_c
        temperature = weather.temperature_c + (previous_temperature - weather.temperature_c) * (1.0 - ventilation_ratio)
        temperature += (base_temperature - weather.temperature_c) * 0.25
        temperature = temperature - crop_feedback.sensible_heat_w_m2 * 0.01

        humidity = weather.relative_humidity_pct + max(0.0, crop_feedback.transpiration_mm_h * 5.0) - ventilation_ratio * 10.0 - actuators.misting_mm_h * 1.5
        previous_humidity = prior.relative_humidity_pct if prior is not None else weather.relative_humidity_pct
        humidity = weather.relative_humidity_pct + (previous_humidity - weather.relative_humidity_pct) * (1.0 - ventilation_ratio)
        humidity = min(100.0, max(0.0, humidity + (weather.relative_humidity_pct - humidity) * 0.25))

        saturation = 0.6108 * math.exp(17.27 * temperature / (temperature + 237.3))
        vapor = saturation * humidity / 100.0
        vpd = max(0.0, saturation - vapor) / 10.0
        co2 = config.co2_ppm_baseline + actuators.co2_supply_ppm - crop_feedback.co2_uptake_ppm
        return MicroclimateState(
            air_temperature_c=temperature,
            relative_humidity_pct=humidity,
            vpd_kpa=vpd,
            pressure_hpa=weather.pressure_hpa,
            solar_radiation_w_m2=indoor_radiation,
            par_umol_m2_s=par,
            co2_ppm=max(0.0, co2),
            wind_speed_m_s=weather.wind_speed_m_s,
            ventilation_fraction=ventilation_ratio,
            heating_kw=actuators.heating_kw,
            cooling_kw=actuators.cooling_kw,
            shading_fraction=shade,
            temperature_c=temperature,
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
        saturation = 0.6108 * math.exp(17.27 * indoor.temperature_c / (indoor.temperature_c + 237.3))
        vapor = saturation * indoor.relative_humidity_pct / 100.0
        vpd = max(0.0, saturation - vapor)
        environment = DerivedEnvironmentState(vpd, max(0.0, indoor.temperature_c - 20.0) + indoor.radiation_w_m2 / 1000.0, saturation, vapor, max(0.0, vpd * 0.15 + indoor.radiation_w_m2 * 0.00005), max(0.0, vpd * 0.15 + indoor.radiation_w_m2 * 0.00005))
        return GreenhouseMicroclimateResult(environment, indoor, consumption, irrigation)


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
        cfg = GreenhouseConfiguration(mode=mode)
        controls = self._normalize_actuators(actuators)
        feedback = CropMicroclimateFeedback(leaf_area_index=crop.leaf_area_index)
        state = self.step(weather, cfg, controls, feedback, dt_seconds, prior=prior)
        consumption = 0.0
        if actuators:
            for value in actuators.values():
                if isinstance(value, ActuatorControl):
                    consumption += value.consumption_kwh if getattr(value, "enabled", True) and not getattr(value, "failed", False) else 0.0
        environment = DerivedEnvironmentState(
            state.vpd_kpa,
            max(0.0, state.air_temperature_c - 20.0) + state.solar_radiation_w_m2 / 1000.0,
            0.6108 * math.exp(17.27 * state.air_temperature_c / (state.air_temperature_c + 237.3)),
            0.6108 * math.exp(17.27 * state.air_temperature_c / (state.air_temperature_c + 237.3)) * state.relative_humidity_pct / 100.0,
            max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
            max(0.0, state.vpd_kpa * 0.15 + state.solar_radiation_w_m2 * 0.00005),
        )
        return GreenhouseMicroclimateResult(
            environment=environment,
            indoor_state=GreenhouseMicroclimateState(**state.to_dict()),
            actuator_consumption_kwh=consumption,
            irrigation_applied_mm=0.0,
        )
