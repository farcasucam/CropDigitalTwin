# Simulation Engine

## Responsabilidad

Coordinar el tiempo simulado y los pasos físicos sin conocer detalles de MQTT, frontend o LLM.

## Componentes

- `SimulationClock`
- `SimulationScheduler`
- `ScenarioRunner`
- `SimulationContext`

## Clock

`SimulationClock` mantiene un instante simulado independiente del reloj de
pared. Recibe explícitamente el instante inicial y usa una fuente monotónica
inyectable para la progresión automática.

Estados:

- `STOPPED`: estado inicial y estado después de `reset()`.
- `RUNNING`: la progresión automática usa `elapsed_real_seconds * speed`.
- `PAUSED`: conserva el tiempo simulado y no progresa automáticamente.

Transiciones válidas:

```text
STOPPED -> RUNNING  start()
RUNNING -> PAUSED   pause()
PAUSED  -> RUNNING  resume()
RUNNING -> STOPPED  reset()
PAUSED  -> STOPPED  reset()
STOPPED -> STOPPED  reset()
```

API pública:

```python
class SimulationClock:
    def __init__(
        self,
        initial_time: datetime,
        speed: float = 1.0,
        source: ClockSource | None = None,
    ): ...
    def now(self) -> datetime: ...
    def start(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def reset(self) -> None: ...
    def set_speed(self, multiplier: float) -> None: ...
    def advance(self, seconds: float) -> timedelta: ...
```

`advance(seconds)` es una orden determinista de avance en segundos
simulados. Es válida en cualquier estado y no depende de `speed` ni del
tiempo real. En cambio, la progresión automática solo ocurre en `RUNNING` y
usa la fuente monotónica multiplicada por `speed`.

La velocidad expresa segundos simulados por segundo real: `1`, `3600` o
`86400` representan un segundo, una hora o un día simulados por segundo real.
Los valores no finitos o no positivos producen `SimulationClockValueError`.
Las transiciones inválidas producen `SimulationClockStateError`. `reset()`
restaura exactamente `initial_time`, conserva la velocidad y comienza una
nueva época de simulación.

La política datetime es conservar la representación del `initial_time`: un
datetime naïve produce tiempos naïve y uno aware conserva su zona horaria.
No se mezclan ni se convierten silenciosamente representaciones durante una
misma simulación.

## Scheduler

Debe permitir:
- timestep físico configurable;
- publicación meteorológica independiente;
- tareas periódicas;
- orden determinista;
- evitar drift acumulativo.

La implementación actual es determinista y manual: `register(name, interval,
callback)` registra callbacks que reciben el `datetime` simulado del
vencimiento; `advance(seconds)` avanza el reloj en timesteps configurables y
ejecuta las tareas pendientes. `run_pending()` permite procesar progresión
automática sin crear threads, asyncio ni esperas reales.
El scheduler observa la propiedad explícita `clock.epoch` y rebasea las
tareas al tiempo inicial de cada nueva época después de `reset()`.

El clock protege sus lecturas y mutaciones con un `RLock`. El scheduler y el
adapter no crean threads; la sincronización de callbacks MQTT productivos
deberá conservar este límite en futuras integraciones.

## MQTT

El adaptador `SimulationClockMQTTAdapter` usa `agri/simulation/control`,
`agri/simulation/time` y `agri/simulation/status`. Los controles son envelopes
`1.0` con `data.command` igual a `start`, `pause`, `resume`, `reset` o
`set_speed` con `data.speed`. Tiempo y estado usan ISO 8601; los errores se
publican en status con `code` y `message`. Status usa QoS 1 y retain; time usa
QoS 0.

## Tests

Los tests usan `FakeClockSource` e `InMemoryMQTTClient`. No esperan tiempo
real: `advance(3600)` avanza exactamente una hora simulada y la progresión
automática se prueba cambiando directamente la fuente monotónica falsa.

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
