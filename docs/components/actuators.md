# Actuators

## Interfaz

```python
class Actuator(Protocol):
    def command(self, value: float) -> None: ...
    def step(self, dt_seconds: float) -> None: ...
    def state(self) -> ActuatorState: ...
```

## Actuadores MVP

### Windows
- 0 = cerrado
- 1 = abierto
- efecto: ventilación.

### Shade
- 0 = completamente abierto
- 1 = completamente cerrado
- efecto: reducción de radiación.

### HVAC
- 0 = apagado
- 1 = potencia máxima
- evolución progresiva.
- preparar separación futura heating/cooling.

### Irrigation
- rate configurable;
- unidades documentadas;
- afecta balance hídrico.

## Fallos

Un actuador puede tener:
- `failed=true`;
- comando solicitado;
- estado real diferente.

Ejemplo:

```text
controller -> HVAC 1.0
actuator.commanded = 1.0
actuator.actual = 0.0
failure = true
```

El modelo físico usa `actual`, no `commanded`.

## Manual

Los comandos manuales siguen exactamente el mismo flujo que los automáticos.
