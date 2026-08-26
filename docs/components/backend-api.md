# Backend API

## Objetivo

Servir al frontend y actuar como frontera segura entre UI y bus MQTT.

## Tecnología

El modelo de código puede usar FastAPI.

## REST

Endpoints mínimos:

```text
GET  /api/health
GET  /api/simulation
POST /api/simulation/speed
POST /api/simulation/pause
POST /api/simulation/resume

GET  /api/state/latest
GET  /api/state/history
GET  /api/events
POST /api/events

GET  /api/actuators
POST /api/actuators/{id}/command

GET  /api/scenarios
POST /api/scenarios/{id}/run

GET  /api/semantic/latest
GET  /api/semantic/history
```

## WebSocket

`/ws/state`

Enviar actualizaciones:
- estado;
- actuadores;
- eventos;
- alarmas;
- semantic packets.

## Regla

El backend publica comandos/eventos MQTT. No modifica el estado del simulador directamente.

## Validación

Validar:
- rango;
- tipo;
- target;
- permisos;
- simulation_id;
- plot_id.

## Seguridad futura

Preparar:
- autenticación;
- autorización;
- roles;
- auditoría.
