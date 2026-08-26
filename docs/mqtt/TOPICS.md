# MQTT Topics

Base:

```text
agri/
```

## Simulation

```text
agri/simulation/time
agri/simulation/control
agri/simulation/events
agri/simulation/status
```

## Environment

```text
agri/environment/weather
agri/environment/events
agri/environment/derived
```

## State

```text
agri/state/climate
agri/state/soil
agri/state/crop
agri/state/actuators
agri/state/full
```

## Commands

```text
agri/commands/shade
agri/commands/windows
agri/commands/hvac
agri/commands/irrigation
agri/commands/natural-event
```

## Actuators

```text
agri/actuators/shade
agri/actuators/windows
agri/actuators/hvac
agri/actuators/irrigation
```

## Semantic

```text
agri/semantic/context
agri/semantic/alerts
```

## Faults

```text
agri/events/fault
```

## Frontend/backend

El backend no necesita topics propios; actúa como gateway.

## Retain

Retener:
- simulation/status;
- último estado de actuadores, si se decide;
- configuración publicada.

No retener telemetría de alta frecuencia indiscriminadamente.
