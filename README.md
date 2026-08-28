# Gemelo Digital Agrícola

La Fase 0 está implementada: modelos de dominio puros, contratos JSON versionados, catálogo y puerto MQTT, configuración, logging y broker Mosquitto local. La Fase 1 y su hardening 1.1 están implementados. La Fase 2 de meteorología exterior también está implementada, con límites separados para baseline, variabilidad normal e invariantes físicos. La Fase 3 de física, así como cultivo, control y frontend, todavía no están implementados.

La Fase 1 añade un `SimulationClock` determinista y un `SimulationScheduler`.
El clock recibe un `initial_time` explícito, permite `start`, `pause`,
`resume`, `reset`, `set_speed` y `advance`, y puede integrarse mediante los
topics MQTT de simulación sin necesitar MQTT para sus tests.

La integración de fuentes meteorológicas está documentada en
`docs/components/weather-providers.md`: Open-Meteo se usa únicamente para
descargas explícitas y las simulaciones posteriores consumen CSV local sin
conexión de red.

La configuración de fuente se carga con `load_weather_source_configuration()`.
Puede seleccionar `synthetic` o `csv`; `open_meteo` prepara una adquisición
explícita, pero nunca descarga durante el arranque o la simulación.

## Fase 4: Crop Engine MVP

`CropEngine` calcula estrés térmico, hídrico y de VPD a partir de la etapa del
cultivo y sus thresholds en `src/crop_config.json`. `cumulative_stress` es la
media del estrés actual y `growth_factor = 1 - cumulative_stress`.
`development_index` y `biomass` son proxies deterministas dependientes del
tiempo simulado, no magnitudes calibradas. La auditoría se ejecuta con
`python -u manual_phase4_1_acceptance_test.py`; los campos de meses, radiación,
riego y nombre de etapa se cargan, pero permanecen pendientes de semántica
agronómica adicional.

## Fase 4.2: evolución temporal

`CropEngine.advance(...)` evoluciona explícitamente un `CropState` mediante
`dt_seconds` simulado, manteniendo la evaluación de estrés y los proxies de
biomasa/desarrollo deterministas. El JSON actual no define GDD, temperatura
base, duraciones ni transiciones, por lo que no se inventan cambios de etapa.

## Fase 2: parcela y cultivo

La configuración técnica permanece en `config/app.json`. Las parcelas y su
ubicación se definen en `src/farm_config.json`, y las definiciones
agronómicas, etapas y umbrales en `src/crop_config.json`. La operación
`download_weather_for_plot()` resuelve la parcela y el cultivo, construye el
request con las coordenadas de la parcela y adquiere el CSV explícitamente:

```python
from agri_twin.application import download_weather_for_plot

result = download_weather_for_plot(
	"plot_14705", "src/farm_config.json", "src/crop_config.json",
	"config/app.json", "data/weather/plot_14705.csv",
	"2026-08-28", "2026-08-28",
)
```

Después, `CsvWeatherProvider` permite ejecutar la simulación sin Internet.
`build_crop_digital_twin_state()` prepara el estado inicial de parcela,
cultivo, etapa y `WeatherState`; los umbrales no se copian al estado dinámico.
La aceptación manual se ejecuta con `python -u manual_phase2_acceptance_test.py`
y usa un directorio temporal para sus datasets.

## Fase 3: modelo físico MVP

`OpenFieldPhysicalModel` transforma un `WeatherState` y un `SoilState` en
variables ambientales derivadas (incluido VPD) y en el siguiente estado de
agua del suelo. El modelo es determinista, no conoce HTTP y permite aplicar
lluvia y riego mediante un balance causal simplificado. Se valida con
`python -u manual_phase3_acceptance_test.py` y funciona sobre un CSV local.
El modelo de invernadero, CO2, actuadores y crecimiento del cultivo quedan
para fases posteriores.

## Requisitos

- Python 3.11+
- Docker Compose (opcional, para Mosquitto)

## Desarrollo

```powershell
python -m pip install -e ".[dev]"
python -m pytest
docker compose up -d mosquitto
```

Los schemas JSON están en `schemas/`. La configuración local está en `config/app.json`. Las decisiones de la Fase 0 se documentan en `docs/architecture/DECISIONS.md`.

## Especificación

Este directorio también contiene la especificación de requisitos para el prototipo funcional.

## Documentos principales

- `architecture/ARCHITECTURE_REQUIREMENTS.md`: especificación maestra y desarrollo por fases.
- `architecture/DOMAIN_MODEL.md`: modelo de dominio y límites de responsabilidad.
- `architecture/EVENTS_AND_CAUSALITY.md`: causalidad, eventos y dinámica de simulación.
- `components/simulation-engine.md`: reloj, scheduler y motor de simulación.
- `components/weather-engine.md`: clima y perturbaciones naturales.
- `components/physical-model.md`: modelo físico exterior/invernadero/suelo.
- `components/crop-engine.md`: cultivo, fenología, estrés y crecimiento.
- `components/actuators.md`: actuadores artificiales.
- `components/controllers.md`: controladores automático/manual.
- `components/mqtt.md`: mensajería y contratos MQTT.
- `components/storage.md`: persistencia, histórico y métricas.
- `components/enrichment-engine.md`: Motor de Enriquecimiento y Serialización Semántica.
- `components/frontend.md`: frontend web en tiempo real y control.
- `components/backend-api.md`: API HTTP/WebSocket del backend.
- `components/observability.md`: logging, health, métricas y trazabilidad.
- `data_contracts/MESSAGE_SCHEMAS.md`: contratos JSON.
- `mqtt/TOPICS.md`: catálogo de topics.
- `docker/MOSQUITTO.md`: broker MQTT.
- `docker/docker-compose.yml`: infraestructura local MVP.

## Regla de implementación

El modelo de código debe implementar las fases en orden y no saltar a IA, MPC, modelos agronómicos avanzados o bases de datos distribuidas antes de que el núcleo determinista, los contratos y los tests estén funcionando.

La especificación conserva la separación fundamental:

`evento/dato externo -> modelo físico -> estado -> cultivo -> evaluación/control -> comando -> actuador -> modelo físico`.

El controlador nunca escribe directamente una temperatura, humedad o VWC resultante.



Ejecución MQTT:
 docker compose ps   
 docker compose up -d