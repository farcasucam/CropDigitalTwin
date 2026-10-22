"""Lumped greenhouse model parameterised from the same geometry and envelope as the EnergyPlus model.

The historical simplified model had a 1 m2 exchange area for 1000 m3, so its solar gain was negligible and it never behaved like a greenhouse. This module derives every
number of the lumped model from what the EnergyPlus greenhouse is built from (``GreenhouseGeometrySpec``, ``EnvelopeSpec``, ``ThermalSpec``), plus three constants that a lumped
model needs and EnergyPlus resolves with detailed geometry (``src/greenhouse_reduced_model.json``). The two backends therefore describe one greenhouse and can be compared.

It has the same default operation as the EnergyPlus model (vents open by themselves above a temperature when it is cooler outside, an ideal heater holds a minimum), no crop
feedback unless asked for (``crop_exchange``, see ``GeometryGreenhouseEngine``) and no CO2 balance beyond the commanded supply and the crop's uptake. All values are provisional; this is consistency between models, not validation against a real greenhouse.
"""

from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

from agri_twin.domain.crop_greenhouse_feedback import CropGreenhouseFeedbackConfiguration, CropGreenhouseFeedbackLoop, CropPhysicalExchangeModel
from agri_twin.domain.crop_growth import CropGrowthEngine
from agri_twin.domain.greenhouse import (
    AIR_DENSITY_KG_M3,
    AIR_SPECIFIC_HEAT_J_KG_K,
    ActuatorControl,
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    GreenhouseMicroclimateEngine,
    GreenhouseMicroclimateResult,
    GreenhouseMicroclimateState,
    derived_environment,
)
from agri_twin.domain.greenhouse_typology import GreenhouseGeometrySpec, floor_area_m2, volume_m3
from agri_twin.domain.models import WeatherState
from agri_twin.infrastructure.greenhouse_idf import FLOOR_MATERIAL, EnvelopeSpec, ThermalSpec, cover_area_m2

CONSTANTS_FILE = Path(__file__).resolve().parents[2] / "greenhouse_reduced_model.json"


@lru_cache(maxsize=1)
def reduced_model_constants() -> Mapping[str, Any]:
    return json.loads(CONSTANTS_FILE.read_text(encoding="utf-8"))


def reduced_configuration(spec: GreenhouseGeometrySpec, envelope: EnvelopeSpec | None = None, thermal: ThermalSpec | None = None) -> tuple[GreenhouseConfiguration, dict[str, Any]]:
    """The lumped configuration of ``spec`` and the description of where each number comes from."""
    envelope, thermal, constants = envelope or EnvelopeSpec(), thermal or ThermalSpec(), reduced_model_constants()
    area, volume, cover = floor_area_m2(spec), volume_m3(spec), cover_area_m2(spec)
    glazed = envelope.cover_area_fraction.value
    transmission = min(1.0, envelope.cover_shgc.value * glazed * (cover / area) * float(constants["incidence_factor"]))
    floor_to_ground_w_m2k = FLOOR_MATERIAL["conductivity_w_mk"] / FLOOR_MATERIAL["thickness_m"]  # through the layer written into the IDF, to its ground boundary
    air_mass_kj_k = AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_K * volume / 1000.0
    floor_mass_kj_k = FLOOR_MATERIAL["thickness_m"] * FLOOR_MATERIAL["density_kg_m3"] * FLOOR_MATERIAL["specific_heat_j_kgk"] / 1000.0 * area * float(constants["floor_mass_participation"])
    configuration = GreenhouseConfiguration(
        volume_m3=volume, solar_transmission=transmission, ventilation_ach=thermal.infiltration_ach.value, heat_loss_w_k=cover * envelope.cover_u_w_m2k.value,
        thermal_mass_kj_k=air_mass_kj_k, thermal_exchange_area_m2=area, mode="passive_greenhouse",
        floor_mass_kj_k=floor_mass_kj_k, floor_conductance_w_k=area * float(constants["floor_film_coefficient_w_m2k"]), solar_to_air_fraction=float(constants["solar_to_air_fraction"]),
        ground_conductance_w_k=area * floor_to_ground_w_m2k, ground_temperature_c=thermal.ground_temperature_c.value, passive_vent_ach=thermal.max_ventilation_ach.value,
        passive_vent_open_above_c=thermal.vent_open_above_c.value, thermostat_setpoint_c=thermal.heating_setpoint_c.value,
        heater_capacity_kw=thermal.heater_capacity_w_m2.value * area / 1000.0, vent_command_fraction=True)
    description = {
        "model": "two lumped nodes (air, floor), exact step; one greenhouse with the EnergyPlus model (same geometry and envelope)",
        "floor_area_m2": round(area, 1), "volume_m3": round(volume, 1), "cover_area_m2": round(cover, 1), "solar_transmission_per_floor_area": round(transmission, 4),
        "cover_conductance_w_k": round(configuration.heat_loss_w_k, 1), "ground_conductance_w_k": round(configuration.ground_conductance_w_k, 1),
        "air_thermal_mass_kj_k": round(configuration.thermal_mass_kj_k, 1), "floor_thermal_mass_kj_k": round(configuration.floor_mass_kj_k, 1),
        "floor_to_air_conductance_w_k": round(configuration.floor_conductance_w_k, 1), "solar_share_to_air": configuration.solar_to_air_fraction, "infiltration_ach": thermal.infiltration_ach.value, "vent_capacity_ach": thermal.max_ventilation_ach.value,
        "vents_open_above_c": thermal.vent_open_above_c.value, "heating_setpoint_c": thermal.heating_setpoint_c.value, "heater_capacity_kw": round(configuration.heater_capacity_kw, 1),
        "ground_temperature_c": thermal.ground_temperature_c.value,
        "sources": "envelope and thermal values: greenhouse_idf EnvelopeSpec/ThermalSpec (PROVISIONAL); constants: src/greenhouse_reduced_model.json (CONSISTENCY_WITH_ENERGYPLUS_NOT_VALIDATED)",
        "limits": ["no crop feedback (transpiration, CO2 uptake), like the EnergyPlus backend", "two lumped nodes: no vertical gradients and no cover temperature",
                   "provisional envelope values; consistency with EnergyPlus, not validation against a real greenhouse"]}
    return configuration, description


class GeometryGreenhouseEngine(GreenhouseMicroclimateEngine):
    """Orchestrator-facing engine of the reduced model: uses its OWN configuration (the historical engine rebuilt a default one every step)."""

    EXCHANGE_ITERATIONS = 3  # fixed-point passes of vapour/heat/CO2 exchange against the microclimate it produces (humidity feeds back negatively, so it settles)

    def __init__(self, configuration: GreenhouseConfiguration, crop_exchange: bool = False) -> None:
        super().__init__(configuration=configuration)
        self.crop_exchange = crop_exchange
        # with the exchange on, the orchestrator also hands over the step time and the soil (everything the exchange is computed from is carried state, so what-if branches stay exact)
        self.requires_simulation_time = crop_exchange
        self.requires_soil = crop_exchange
        if crop_exchange:
            volume_per_floor_m2 = configuration.volume_m3 / configuration.thermal_exchange_area_m2  # the air column the crop's vapour and CO2 are shared with
            self._exchange_configuration = CropGreenhouseFeedbackConfiguration(air_volume_m3=volume_per_floor_m2)
            self._exchange = CropPhysicalExchangeModel(self._exchange_configuration)
            self._growth = CropGreenhouseFeedbackLoop(self, exchange=self._exchange, configuration=self._exchange_configuration)

    def use_co2_response(self, response) -> None:
        """The growth proxy behind the crop's CO2 uptake responds to CO2 like the orchestrator's growth does."""
        if self.crop_exchange:
            self._growth.crop_engine = CropGrowthEngine(co2_response=response)

    def use_water_engine(self, water) -> None:
        """The crop's transpiration is the orchestrator's own water balance (same ET0 method), so the air and the soil see one evapotranspiration."""
        if self.crop_exchange:
            self._exchange.water = water

    @property
    def configuration(self) -> GreenhouseConfiguration:
        return self._configuration

    def advance(self, weather: WeatherState, crop, dt_seconds: float, mode: str = "outdoor", actuators: Mapping[str, Any] | None = None,
                prior: GreenhouseMicroclimateState | None = None, simulation_time=None, soil=None) -> GreenhouseMicroclimateResult:
        if prior is None:
            self._state = None
        controls = self._normalize_actuators(self._scaled(actuators))
        configuration = replace(self._configuration, mode=mode)
        feedback = CropMicroclimateFeedback(leaf_area_index=crop.leaf_area_index)
        if self.crop_exchange and simulation_time is not None:
            feedback = self._crop_feedback(weather, crop, configuration, controls, dt_seconds, prior, simulation_time, soil)
        state = self.step(weather, configuration, controls, feedback, dt_seconds, prior=prior)
        consumption = sum(value.consumption_kwh for value in (actuators or {}).values() if isinstance(value, ActuatorControl) and value.enabled and not value.failed)
        return GreenhouseMicroclimateResult(derived_environment(state), GreenhouseMicroclimateState(**state.to_dict()), consumption, 0.0)

    def _crop_feedback(self, weather: WeatherState, crop, configuration: GreenhouseConfiguration, controls, dt_seconds: float, prior, simulation_time, soil) -> CropMicroclimateFeedback:
        """Transpiration, latent and sensible heat and CO2 uptake of the crop in the air it produces: a pure function of the carried state (crop, soil, prior air) and the step's
        forcing, iterated a fixed number of times from the crop-free air. Transpiration cannot exceed what the air's vapour deficit can take (mass conservation in the exchange model)."""
        feedback = CropMicroclimateFeedback(leaf_area_index=crop.leaf_area_index)
        for _ in range(self.EXCHANGE_ITERATIONS):
            state = self._compute_state(weather, configuration, controls, feedback, dt_seconds, prior)
            growth = self._growth.grow(crop, weather, state, dt_seconds, simulation_time)
            feedback = self._exchange.calculate(crop, growth, state, weather, dt_seconds, soil, simulation_time).to_feedback()
        return feedback

    def predict_air_temperature(self, weather: WeatherState, prior: GreenhouseMicroclimateState | None, dt_seconds: float, mode: str = "passive_greenhouse",
                                extra_air_changes: float = 0.0, net_hvac_kw: float = 0.0, shade: float = 0.0) -> float:
        """Air temperature at the end of a step for the given extra air exchange, HVAC power (+ heating, - cooling) and shading, with the default venting and
        thermostat standing down (a controller is the one deciding). The same equations and state as the step itself, so the prediction IS the outcome."""
        actuators = GreenhouseActuatorState(heating_kw=max(0.0, net_hvac_kw), cooling_kw=max(0.0, -net_hvac_kw), ventilation_ach=max(0.0, extra_air_changes),
                                            shading_fraction=min(1.0, max(0.0, shade)), default_vent_enabled=False, default_heating_enabled=False)
        return self._compute_state(weather, replace(self._configuration, mode=mode), actuators, CropMicroclimateFeedback(), dt_seconds, prior).air_temperature_c

    def _scaled(self, actuators: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        """A "ventilation" command is a fraction of the vent capacity (as in EnergyPlus); "ventilation_ach" is already physical."""
        if not actuators or not self._configuration.vent_command_fraction:
            return actuators
        scale = self._configuration.passive_vent_ach
        scaled = dict(actuators)
        for key in ("ventilation", "vent"):
            control = scaled.get(key)
            if isinstance(control, ActuatorControl):
                scaled[key] = ActuatorControl(control.actual * scale, maximum=scale, capacity=scale)
        return scaled


def engine_factory(configuration: GreenhouseConfiguration, crop_exchange: bool = False) -> Callable[[Any, Any], GeometryGreenhouseEngine]:
    return lambda _scenario, _provider: GeometryGreenhouseEngine(configuration, crop_exchange)
