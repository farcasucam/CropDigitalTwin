# Simulation Engine

## Responsabilidad

Coordinar el tiempo simulado y los pasos físicos sin conocer detalles de MQTT, frontend o LLM.

## Componentes

- `SimulationClock`
- `SimulationScheduler`
- `ScenarioRunner`
- `SimulationContext`

## Clock

API conceptual:

```python
class SimulationClock:
    def now(self) -> datetime: ...
    def set_speed(self, speed: float) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def advance(self, real_seconds: float) -> timedelta: ...
```

## Scheduler

Debe permitir:
- timestep físico configurable;
- publicación meteorológica independiente;
- tareas periódicas;
- orden determinista;
- evitar drift acumulativo.

## Reproducibilidad

Guardar:
- seed;
- initial simulation time;
- configuration version;
- crop/farm configuration version;
- scenario ID;
- controller ID/version.

## Tests

- speed=3600;
- speed=86400;
- pause;
- resume;
- cambio dinámico de velocidad;
- mismo seed produce misma serie.
