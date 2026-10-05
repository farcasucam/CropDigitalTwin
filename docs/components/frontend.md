# Frontend Web

## Estado implementado en Phase 5.38

La aplicación inicial de simulación vive en `frontend/` y consume únicamente
el adaptador HTTP local `agri_twin.interfaces.frontend_api`, que delega en
`InteractiveSimulationService` (Phase 5.37). La UI está implementada con HTML,
CSS y JavaScript nativos; no contiene lógica científica. La guía operativa y
sus limitaciones están en
[`docs/phase5_38_frontend_simulation.md`](../phase5_38_frontend_simulation.md).

La pantalla de simulación muestra los datos disponibles de la parcela
seleccionada en `src/farm_config.json`. Si no existe una ficha configurada,
indica expresamente que no hay metadatos ni coordenadas, sin inferirlos. Cuando
hay coordenadas, ofrece un enlace voluntario a OpenStreetMap; no carga mapas ni
envía la ubicación a servicios externos hasta que se abre ese enlace. La ficha
describe la configuración local, no verifica la ubicación ni el estado actual
del campo.

Esta entrega no incluye actuadores, WebSocket, alarmas, Semantic Panel ni
control por eventos. Los apartados posteriores describen superficies futuras
del frontend general, no capacidades disponibles en la pantalla de simulación
actual. La operación greenhouse actuada tampoco está expuesta por el contrato
5.37.

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
