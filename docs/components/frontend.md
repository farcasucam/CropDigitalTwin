# Frontend Web

## Objetivo

Visualización gráfica en tiempo real y control interactivo del gemelo.

## Vistas

### Dashboard
- temperatura interior/exterior;
- RH;
- VPD;
- radiación;
- VWC;
- lluvia;
- viento;
- CO2;
- biomasa;
- estrés;
- fase fenológica.

### Actuadores
Tarjetas para:
- ventanas;
- toldo;
- HVAC;
- riego.

Mostrar:
- comando;
- estado real;
- fallo;
- diferencia.

### Timeline
Mostrar:
- eventos;
- actuaciones;
- cambios de estado;
- alarmas.

### Semantic Panel
Mostrar:
- situación;
- severidad;
- hechos;
- métricas;
- cadena causal;
- narrativa.

### Simulation Controls
- play/pause;
- speed;
- fecha simulada;
- reset;
- escenario.

### Natural Events
Controles para:
- rain;
- temperature;
- solar radiation;
- frost;
- heatwave;
- wind.

Los eventos deben tener duración/intensidad cuando corresponda.

## Gráficas

Usar series temporales con:
- ventana móvil;
- zoom;
- selección de variables;
- timestamps simulados;
- comparación de límites.

## Tiempo real

WebSocket como canal principal de actualización.

No hacer polling agresivo si existe WebSocket.

## UX

Distinguir visualmente:
- estado observado;
- comando;
- estado real;
- métrica derivada;
- evento;
- inferencia semántica.

Nunca presentar una inferencia como medición.
