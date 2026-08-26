# Observabilidad

## Logging

Usar `logging`.

Cada log debe poder incluir:
- timestamp real;
- timestamp simulado;
- process;
- simulation_id;
- plot_id;
- event;
- action;
- error;
- correlation_id.

Ejemplo:

```text
2026-08-26 20:00:01 SIM=2026-08-27T08:00:00
[CONTROLLER] Temperature 31.2C -> opening windows to 80%
```

## Health

Cada proceso debe ofrecer o publicar estado:
- connected;
- running;
- paused;
- error;
- last_simulation_time.

## Métricas

Preparar:
- MQTT messages/sec;
- simulation ticks;
- processing latency;
- WebSocket clients;
- enrichment latency;
- semantic packets/sec;
- command failures.

## Correlation

Cada evento/comando debe tener `correlation_id`.

Debe ser posible seguir:

```text
UI command
 -> MQTT command
 -> actuator
 -> physical state
 -> semantic enrichment
 -> UI observation
```
