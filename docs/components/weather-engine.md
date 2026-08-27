# Weather Engine

## Responsabilidad

Generar únicamente condiciones meteorológicas exteriores y mantener
perturbaciones temporales. El único estado de salida es `WeatherState`.
El motor no conoce MQTT, frontend, cultivo, invernadero, actuadores ni LLM.

## API

```python
engine = WeatherEngine(configuration)
state = engine.generate(simulation_time)
engine.add_perturbation(event)
engine.remove_perturbation(event_id)
engine.reset()
```

`generate(simulation_time)` requiere un datetime timezone-aware y normaliza el
instante a UTC. Su resultado depende únicamente de configuración, seed,
instante y perturbaciones activas. Repetir la misma llamada produce el mismo
`WeatherState`, independientemente del historial de llamadas.

## Configuración

`WeatherConfiguration` está organizada en `temperature`, `radiation`,
`humidity`, `wind`, `pressure` y `simulation`. La configuración de ejemplo
está en `config/weather_config.json`; el intervalo meteorológico por defecto
es de 60 segundos simulados y el seed pertenece a `simulation`.

## Perfiles

- Temperatura: curva cosenoidal continua entre mínimo nocturno y máximo
	diurno, con variabilidad determinista suave.
- Radiación: seno continuo entre salida y puesta de sol; es cero durante la
	noche.
- Humedad: perfil suave limitado por su configuración.
- Viento: velocidad y dirección con variación sinusoidal determinista.
- Presión: variación suave alrededor de la base y limitada por variabilidad.

No se usa random global ni una muestra independiente por tick.

## Entradas

- SimulationClock;
- configuración;
- seed;
- eventos naturales.

## Salida

`WeatherState`.

## Reglas MVP

Temperatura:
- mínimo nocturno;
- incremento matinal;
- máximo vespertino;
- descenso nocturno.

Radiación:
- 0 durante noche;
- curva diurna suave.

Humedad:
- variación temporal;
- relación coherente con temperatura.

Viento:
- evolución suave.

Lluvia:
- normalmente 0;
- modificable por eventos.

## Perturbaciones

Una ola de calor puede aplicar un offset/forzamiento temporal a la temperatura exterior.

Una helada puede forzar un periodo de temperatura baja.

`WeatherPerturbation` es inmutable, usa datetimes UTC y contiene `event_id`,
`event_type`, `start_time`, `end_time`, `priority`, `source` y
`parameters: Mapping[str, float]`.

Semántica de parámetros:

| Evento | Parámetro | Semántica |
|---|---|---|
| `rain` | `rate_mm_h` | absoluto; lluvias compatibles usan el máximo |
| `frost` | `temperature_c` | absoluto; conflicto por prioridad |
| `heatwave` | `temperature_offset_c` | offset; offsets compatibles se suman |
| `wind` | `speed_multiplier` | multiplicador; compatibles se multiplican |
| `wind` | `direction_deg` | absoluto en `[0, 360)`; conflicto por prioridad |
| `solar_radiation` | `radiation_multiplier` | multiplicador; compatibles se multiplican |
| `solar_radiation` | `radiation_offset_w_m2` | offset; compatibles se suman |

Los valores absolutos en conflicto se ordenan por `priority DESC`,
`start_time ASC`, `event_id ASC`. Los eventos activos cumplen
`start_time <= simulation_time < end_time`.

`reset()` elimina perturbaciones y conserva configuración y seed.

## Semántica de límites

La generación se interpreta en tres capas, en este orden:

```text
baseline(t) + normal_variability(t) -> eventos activos -> invariantes físicos
```

El baseline es el perfil nominal. `temperature.minimum_c` y
`temperature.maximum_c` delimitan el baseline; con `12..30 °C` y variabilidad
`0.5 °C`, el rango normal permitido es `11.5..30.5 °C`. La radiación nominal
está en `0..maximum_w_m2`; con máximo `900` y variabilidad `15`, la radiación
normal puede llegar a `915 W/m2`.

La variabilidad normal se aplica al baseline. La humedad se mantiene dentro de
`minimum_pct..maximum_pct`; el viento nunca es negativo; la presión queda en
`base_hpa +/- variability_hpa`; la dirección siempre está en `[0, 360)`.

Los eventos se aplican después y no se recortan contra los límites del
baseline. Por ejemplo, una helada de `-10 °C` puede estar por debajo de un
mínimo base de `12 °C`, una ola de calor de `+20 °C` puede superar `30 °C` y
una anomalía de radiación puede superar `900 W/m2`.

Los invariantes físicos finales son: radiación, viento y lluvia no negativos;
humedad en `[0, 100]`; dirección en `[0, 360)`; temperatura, presión y todos
los valores finitos. No se aplica clamp global de temperatura o radiación
después de los eventos.

## Determinismo

## Integración

`SimulationClock` proporciona el tiempo simulado y `SimulationScheduler` llama
periódicamente a `generate()`. El scheduler no contiene lógica meteorológica.
El adaptador MQTT publica bajo `agri/environment/weather` y recibe eventos bajo
`agri/environment/events`; no publica automáticamente al conectar.

## Invariantes y tests

Humedad está en `[0, 100]`, radiación, lluvia y velocidad no son negativas,
dirección está en `[0, 360)`, presión y temperatura son finitas y los datetimes
son timezone-aware. Los tests no esperan tiempo real ni usan `sleep()`.
