# Eventos y Causalidad

## Principio

```text
EVENTO / DATO
     ↓
CONDICIÓN EXTERNA O ACTUADOR
     ↓
MODELO FÍSICO
     ↓
ESTADO AMBIENTAL
     ↓
CULTIVO
     ↓
EVALUACIÓN
     ↓
CONTROLADOR
     ↓
COMANDO
     ↓
ACTUADOR
     ↓
MODELO FÍSICO
```

## Eventos naturales

Tipos mínimos:
- `rain`
- `heatwave`
- `frost`
- `wind`
- `solar_radiation`
- `temperature_override`
- `humidity_override`

Un evento de lluvia de 20 mm/h debe modificar `rain_rate_mm_h`; no debe establecer directamente `indoor_humidity` ni `soil_vwc`.

## Eventos de simulación

- pause
- resume
- set_speed
- reset
- seek, si se implementa
- scenario_start
- scenario_stop

## Eventos de fallo

- actuator_failure
- actuator_recovery
- sensor_failure, preparado para fases posteriores
- communication_failure

## Eventos de usuario

El frontend genera comandos de intención, no mutaciones de estado.

Ejemplo:

```json
{
  "type": "manual_command",
  "target": "shade",
  "value": 0.8,
  "source": "web-ui"
}
```

El simulador valida y aplica el comando al actuador.
