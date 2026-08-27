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