# Weather Engine

## Responsabilidad

Generar condiciones meteorológicas y mantener perturbaciones externas.

## Entradas

- SimulationClock;
- configuración;
- seed;
- eventos naturales.

## Salidas

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

La perturbación debe tener:
- event_id;
- start_time;
- end_time;
- intensidad;
- prioridad;
- fuente.

## Determinismo

No usar random sin seed. La generación pseudoaleatoria debe ser reproducible.
