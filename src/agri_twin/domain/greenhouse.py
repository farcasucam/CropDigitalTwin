"""Lumped greenhouse microclimate and actuator model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from agri_twin.domain.models import ActuatorState, CropGrowthState, DerivedEnvironmentState, WeatherState


class GreenhouseModelError(ValueError):
    """Raised when greenhouse or actuator inputs are invalid."""


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


@dataclass(frozen=True, slots=True)
class GreenhouseMicroclimateState:
    temperature_c: float
    relative_humidity_pct: float
    radiation_w_m2: float
    co2_ppm: float = 420.0


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


class GreenhouseMicroclimateEngine:
    """Transform outdoor WeatherState into crop-consumable indoor environment."""

    def __init__(self, profiles: Mapping[str, GreenhouseProfile] | None = None) -> None:
        self._profiles = dict(PROFILES if profiles is None else profiles)

    def profile_for(self, mode: str) -> GreenhouseProfile:
        try:
            return self._profiles[mode]
        except KeyError as exc:
            raise GreenhouseModelError(f"greenhouse profile not found: {mode}") from exc

    def advance(
        self,
        weather: WeatherState,
        crop: CropGrowthState,
        dt_seconds: float,
        mode: str = "outdoor",
        actuators: Mapping[str, ActuatorControl | ActuatorState] | None = None,
        prior: GreenhouseMicroclimateState | None = None,
    ) -> GreenhouseMicroclimateResult:
        if not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise GreenhouseModelError("dt_seconds must be positive and finite")
        profile = self.profile_for(mode)
        controls = {name: self._control(value) for name, value in (actuators or {}).items()}
        if profile.outdoor_bypass:
            indoor = GreenhouseMicroclimateState(weather.temperature_c, weather.relative_humidity_pct, weather.solar_radiation_w_m2, 420.0)
            return self._result(indoor, weather, 0.0, 0.0)
        shade = min(1.0, max(0.0, controls.get("shade", ActuatorControl()).actual))
        ventilation = controls.get("ventilation", ActuatorControl()).actual
        heating = controls.get("heating", ActuatorControl()).actual + controls.get("hvac", ActuatorControl()).actual
        cooling = controls.get("cooling", ActuatorControl()).actual
        transmission = profile.solar_transmission * (1.0 - shade)
        indoor_radiation = weather.solar_radiation_w_m2 * transmission
        solar_offset = indoor_radiation * 0.004
        net_hvac = heating - cooling
        heat_loss = profile.heat_loss_w_k / 1000.0
        target_temperature = weather.temperature_c + solar_offset + (net_hvac / max(heat_loss, 0.01))
        ventilation_ratio = min(1.0, ventilation / max(profile.ventilation_ach * 4.0, 1.0))
        target_temperature = target_temperature * (1.0 - ventilation_ratio) + weather.temperature_c * ventilation_ratio
        prior_temperature = prior.temperature_c if prior else weather.temperature_c
        alpha = 1.0 - math.exp(-dt_seconds / max(profile.thermal_mass_kj_k / max(profile.heat_loss_w_k, 0.001) * 1000.0, 1.0))
        temperature = prior_temperature + alpha * (target_temperature - prior_temperature)
        misting = controls.get("misting", ActuatorControl()).actual
        prior_rh = prior.relative_humidity_pct if prior else weather.relative_humidity_pct
        humidity_target = weather.relative_humidity_pct + min(25.0, crop.leaf_area_index * 2.0 + misting * 20.0)
        humidity_target = humidity_target * (1.0 - ventilation_ratio) + weather.relative_humidity_pct * ventilation_ratio
        relative_humidity = min(100.0, max(0.0, prior_rh + alpha * (humidity_target - prior_rh)))
        co2 = 420.0 + controls.get("co2", ActuatorControl()).actual * 100.0
        indoor = GreenhouseMicroclimateState(temperature, relative_humidity, indoor_radiation, co2)
        consumption = sum(control.consumption_kwh * dt_seconds / 3600.0 for control in controls.values())
        irrigation = controls.get("irrigation", ActuatorControl()).actual * dt_seconds / 3600.0
        return self._result(indoor, weather, consumption, irrigation)

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