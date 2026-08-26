# Storage

## MVP

SQLite.

## Repositorios

- `StateRepository`
- `EventRepository`
- `CommandRepository`
- `MetricRepository`
- `SemanticPacketRepository`

## Datos

Guardar como mínimo:
- timestamp real;
- simulation_time;
- simulation_id;
- plot_id;
- weather;
- climate state;
- soil state;
- crop state;
- actuator states;
- commands;
- events;
- failures;
- semantic packets.

## Evolución

Implementar interfaces para poder sustituir SQLite por PostgreSQL/TimescaleDB/InfluxDB.

El simulador no debe conocer SQL.
