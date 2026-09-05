"""Typed Phase 0 domain state and its invariants."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta


def _in_range(name: str, value: float, minimum: float, maximum: float) -> None:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


@dataclass(frozen=True, slots=True)
class Plot:
    plot_id: str
    farm_name: str
    crop_key: str
    crop_variety: str
    area_ha: float
    current_stage: str
    irrigation_type: str
    soil_type: str
    station_id: str

    def __post_init__(self) -> None:
        if not self.plot_id or self.area_ha <= 0:
            raise ValueError("plot_id must be set and area_ha must be positive")


@dataclass(frozen=True, slots=True)
class WeatherState:
    temperature_c: float
    relative_humidity_pct: float
    solar_radiation_w_m2: float
    wind_speed_m_s: float
    wind_direction_deg: float
    rain_rate_mm_h: float
    pressure_hpa: float

    def __post_init__(self) -> None:
        for name in (
            "temperature_c", "relative_humidity_pct", "solar_radiation_w_m2",
            "wind_speed_m_s", "wind_direction_deg", "rain_rate_mm_h", "pressure_hpa",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        _in_range("relative_humidity_pct", self.relative_humidity_pct, 0, 100)
        if not 0 <= self.wind_direction_deg < 360:
            raise ValueError("wind_direction_deg must be in [0, 360)")
        if min(self.solar_radiation_w_m2, self.wind_speed_m_s, self.rain_rate_mm_h) < 0:
            raise ValueError("radiation, wind speed and rain rate cannot be negative")


@dataclass(frozen=True, slots=True)
class DerivedEnvironmentState:
    vpd_kpa: float
    thermal_load: float
    saturation_vapor_pressure: float
    vapor_pressure: float
    estimated_transpiration: float
    evapotranspiration_proxy: float


@dataclass(frozen=True, slots=True)
class SoilState:
    vwc_m3_m3: float
    soil_temperature_c: float
    field_capacity: float
    wilting_point: float
    drainage_rate: float
    root_zone_water: float

    def __post_init__(self) -> None:
        if self.vwc_m3_m3 < 0 or self.drainage_rate < 0 or self.root_zone_water < 0:
            raise ValueError("soil water values cannot be negative")
        if self.wilting_point > self.field_capacity:
            raise ValueError("wilting_point cannot exceed field_capacity")


@dataclass(frozen=True, slots=True)
class CropState:
    biomass: float
    leaf_area_index: float
    development_stage: str
    water_stress: float
    temperature_stress: float
    vpd_stress: float
    cumulative_stress: float
    development_index: float

    def __post_init__(self) -> None:
        for name in ("water_stress", "temperature_stress", "vpd_stress", "development_index"):
            _in_range(name, getattr(self, name), 0, 1)
        if self.biomass < 0 or self.leaf_area_index < 0 or self.cumulative_stress < 0:
            raise ValueError("crop aggregate values cannot be negative")

    @property
    def environmental_stress(self) -> float:
        """MVP environmental stress represented by the configured VPD index."""
        return self.vpd_stress

    @property
    def total_stress(self) -> float:
        return self.cumulative_stress

    @property
    def growth_factor(self) -> float:
        return 1.0 - self.cumulative_stress


@dataclass(frozen=True, slots=True)
class CropGrowthState:
    """Persistent crop state at an explicit SimulationClock instant.

    This contract deliberately stores no autonomous crop dynamics. A later
    growth engine will derive state changes from weather and an explicit dt.
    """

    simulation_time: datetime
    crop_key: str
    variety: str
    current_stage: str
    phenology_progress: float = 0.0
    biomass_total: float = 0.0
    biomass_leaf: float = 0.0
    biomass_stem: float = 0.0
    biomass_root: float = 0.0
    biomass_fruit: float = 0.0
    leaf_area_index: float = 0.0
    root_depth_m: float = 0.0
    soil_water_vwc: float = 0.0
    nutrient_status: float = 1.0
    water_stress: float = 0.0
    heat_stress: float = 0.0
    cold_stress: float = 0.0
    vpd_stress: float = 0.0
    radiation_stress: float = 0.0
    frost_damage: float = 0.0
    accumulated_stress: float = 0.0
    maturity_index: float = 0.0
    yield_estimate: float = 0.0
    harvest_ready: bool = False

    def __post_init__(self) -> None:
        if self.simulation_time.tzinfo is None:
            raise ValueError("simulation_time must be timezone-aware")
        if not self.crop_key or not self.variety or not self.current_stage:
            raise ValueError("crop_key, variety and current_stage must be set")
        for name in (
            "phenology_progress", "soil_water_vwc", "nutrient_status", "water_stress",
            "heat_stress", "cold_stress", "vpd_stress", "radiation_stress",
            "frost_damage", "maturity_index",
        ):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            _in_range(name, value, 0.0, 1.0)
        for name in (
            "biomass_total", "biomass_leaf", "biomass_stem", "biomass_root",
            "biomass_fruit", "leaf_area_index", "root_depth_m", "accumulated_stress",
            "yield_estimate",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        partitioned_biomass = self.biomass_leaf + self.biomass_stem + self.biomass_root + self.biomass_fruit
        if not math.isclose(self.biomass_total, partitioned_biomass, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("biomass_total must equal partitioned biomass")
        if self.harvest_ready and self.maturity_index < 1.0:
            raise ValueError("harvest_ready requires maturity_index of 1")

    def advance(self, simulation_time: datetime, dt_seconds: float) -> "CropGrowthState":
        """Return this persistent state at a later SimulationClock instant.

        ``simulation_time`` and ``dt_seconds`` are supplied by the caller's
        SimulationClock/Scheduler. No real-time clock or crop dynamics run here.
        """
        if simulation_time.tzinfo is None:
            raise ValueError("simulation_time must be timezone-aware")
        if not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise ValueError("dt_seconds must be finite and non-negative")
        if simulation_time != self.simulation_time + timedelta(seconds=dt_seconds):
            raise ValueError("simulation_time must advance by dt_seconds")
        return CropGrowthState(**(self.to_dict() | {"simulation_time": simulation_time}))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation using ISO 8601 simulation time."""
        payload = asdict(self)
        payload["simulation_time"] = self.simulation_time.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class ActuatorState:
    commanded_value: float
    actual_value: float
    min_value: float
    max_value: float
    slew_rate: float
    enabled: bool
    failed: bool
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.min_value > self.max_value or self.slew_rate < 0:
            raise ValueError("actuator bounds or slew_rate are invalid")
        _in_range("commanded_value", self.commanded_value, self.min_value, self.max_value)
        _in_range("actual_value", self.actual_value, self.min_value, self.max_value)
        if self.failed and not self.failure_reason:
            raise ValueError("failed actuators require a failure_reason")


@dataclass(frozen=True, slots=True)
class SimulationState:
    simulation_id: str
    plot_id: str
    simulation_time: str
    weather: WeatherState
    derived_environment: DerivedEnvironmentState
    soil: SoilState
    crop: CropState
    actuators: dict[str, ActuatorState]
    active_events: tuple[str, ...] = ()
    sequence: int = 0

    def __post_init__(self) -> None:
        if not self.simulation_id or not self.plot_id or not self.simulation_time:
            raise ValueError("simulation identifiers and time must be set")
        if self.sequence < 0:
            raise ValueError("sequence cannot be negative")