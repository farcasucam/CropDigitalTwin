# Controllers

## Interfaz

```python
class Controller(Protocol):
    def evaluate(self, state: SimulationState) -> list[Command]: ...
```

## ManualController

Solo transforma intención del usuario en comandos válidos.

## RuleBasedController

Reglas configurables.

Ejemplos iniciales:
- temperatura > threshold -> abrir ventanas;
- temperatura > critical/heat threshold -> HVAC;
- radiación > threshold -> sombreo;
- VWC < threshold -> riego;
- lluvia -> cerrar ventanas.

No codificar thresholds de un cultivo concreto en Python.

## Futuro

Implementar mediante la misma interfaz:
- PID;
- MPC;
- optimizador;
- RL;
- controlador híbrido.

## Seguridad

Un controlador nunca puede:
- escribir `state.temperature`;
- escribir `state.vwc`;
- escribir directamente el estado de un actuador.

Solo puede emitir comandos.
