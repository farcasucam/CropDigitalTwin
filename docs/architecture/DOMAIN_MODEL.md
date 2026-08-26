# Modelo de Dominio

## Entidades

### Farm
Identifica una finca o unidad productiva.

### Plot
Representa una parcela/sector y debe incluir como mínimo:
- plot_id
- farm_name
- crop_key
- crop_variety
- area_ha
- current_stage
- irrigation_type
- soil_type
- station_id

### CropProfile
Proviene de `crop_config.json` y contiene fases y thresholds.

### CropState
Estado dinámico:
- biomass
- leaf_area_index
- development_stage
- water_stress
- temperature_stress
- vpd_stress
- cumulative_stress
- development_index

### WeatherState
- temperature_c
- relative_humidity_pct
- solar_radiation_w_m2
- wind_speed_m_s
- wind_direction_deg
- rain_rate_mm_h
- pressure_hpa

### DerivedEnvironmentState
- vpd_kpa
- thermal_load
- saturation_vapor_pressure
- vapor_pressure
- estimated_transpiration
- evapotranspiration_proxy

### SoilState
- vwc_m3_m3
- soil_temperature_c
- field_capacity
- wilting_point
- drainage_rate
- root_zone_water

### ActuatorState
Para cada actuador:
- commanded_value
- actual_value
- min_value
- max_value
- slew_rate
- enabled
- failed
- failure_reason

### SimulationState
Agrega:
- simulation_id
- plot_id
- simulation_time
- weather
- derived_environment
- soil
- crop
- actuators
- active_events
- sequence

## Invariantes

- valores normalizados entre 0 y 1 cuando se indique;
- RH entre 0 y 100%;
- radiación >= 0;
- VWC >= 0;
- potencia HVAC dentro de límites;
- comandos no pueden saltarse validación;
- timestamp simulado nunca depende de `datetime.now()`.

## Separación

`Domain` no importa:
- Paho;
- FastAPI;
- React;
- SQLite;
- proveedor LLM.

Las dependencias apuntan hacia infraestructura, nunca al revés.
