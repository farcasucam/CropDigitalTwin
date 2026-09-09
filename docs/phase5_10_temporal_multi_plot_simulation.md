# Phase 5.10: temporal multi-plot simulation

## Objetivo

Phase 5.10 añade semántica temporal explícita para ejecutar varios ciclos productivos sobre un único tiempo simulado. No calibra el modelo, no reclama validación experimental y no añade otro motor fisiológico.

## Arquitectura

`SimulationClock` es la única autoridad temporal. `SimulationScheduler` avanza el reloj en pasos deterministas y ejecuta la tarea `multi-plot-cycle-execution`. `MultiPlotSimulation` ordena parcelas y ciclos de forma estable, resuelve el ciclo de cada parcela y entrega un `PlotSimulationResult` a los motores existentes mediante `step_handler`.

El orden de cada tick es: timestamp del reloj, resolución de ciclo, forcing meteorológico, resultado por parcela y callback de motores existentes. La capa no duplica `CropGrowthEngine`, `PhenologyEngine`, física de invernadero, balance de agua ni feedback.

## CropDefinition y CropCycle

`CropDefinition` describe una especie en el catálogo. `SyntheticCropCycle`, introducido en Phase 5.9, representa una instancia de campaña con `crop_cycle_id`, parcela, cultivo, variedad y fechas. Phase 5.10 lo reutiliza como contrato de ciclo; no crea una segunda definición equivalente.

Los estados de ejecución son `PRE_PLANTING`, `ACTIVE`, `HARVEST_READY`, `HARVESTED` y `POST_HARVEST`, además de `PLANNED` y `CANCELLED` como estados del contrato. Solo `ACTIVE` y `HARVEST_READY` reciben ticks de crecimiento. Los estados anteriores y posteriores se reportan sin crecimiento.

## Ciclos anuales, cortos y perennes

Tomate y pimiento pueden tener un ciclo anual independiente. Lechuga puede tener varios ciclos en la misma parcela y el resolvedor selecciona el ciclo activo por fecha. Uva, melocotón, ciruela y manzana se representan como perennes; después de la cosecha conservan su identidad y pasan a `POST_HARVEST`, no se eliminan ni se reinician como una planta nueva.

Si faltan fechas agronómicas, el ciclo puede conservar `None`; el generador sintético sí aporta fechas marcadas por su metadata como sintéticas. No se infieren fechas reales.

## Multi-parcela y aislamiento

Las parcelas se ordenan por `plot_id`. Cada `crop_cycle_id` tiene un `CropCycleState` independiente con ticks y tiempo acumulado. Un ciclo cosechado no recibe estado mutable por accidente y un nuevo ciclo no hereda LAI, biomasa, madurez, estrés ni fenología del anterior. La configuración de ambiente, variedad y parcela permanece en el resultado.

El callback `step_handler` es el punto de integración para invocar el `CropGrowthEngine`, `PhenologyEngine`, `GreenhousePhysicalModel` y `CropGreenhouseFeedbackLoop` ya existentes. Para exterior se puede consumir directamente `WeatherState`; para invernadero el callback puede aplicar la cadena física existente, manteniendo una configuración independiente por parcela.

## Weather forcing y provenance

El proveedor meteorológico solo entrega `WeatherState` para el timestamp solicitado; no mueve el reloj. Se conserva `source` (`REAL_WORLD`, `OPEN_METEO`, `USER_SCENARIO` o `SYNTHETIC`) como provenance de forcing. Las observaciones de LAI, biomasa, fenología, suelo y cosecha siguen entrando por `ObservationIngestion` y no se convierten en forcing.

## Determinismo y ventanas parciales

Con el mismo reloj inicial, ciclos, parcelas, proveedor, semilla y callback se obtiene el mismo resultado. El scheduler permite avanzar desde antes de plantación, a mitad de ciclo, entre ciclos o después de cosecha. El sistema no usa la fecha del ordenador ni obliga a comenzar el 1 de enero.

## Tests y manual

Los tests están en `tests/test_multi_plot_simulation.py`. El manual es `manual_phase5_10_multi_plot_temporal_test.py` y muestra el caso multi-parcela con dataset sintético. La regresión completa continúa ejecutándose sin red.

## Limitaciones

Esta fase no ofrece calibración real, validación experimental, inferencia automática de fechas, reconstrucción fisiológica perfecta de estados históricos, modelos específicos calibrados por variedad, sensor fusion, data assimilation, ML, TimesFM, rendimiento real ni manejo agronómico detallado. Tampoco implementa persistencia de checkpoints; el estado es determinista mientras se conserven el reloj y los estados de ejecución.

**PHASE 5.10 COMPLETE — TEMPORAL CROP-CYCLE EXECUTION READY — MULTI-PLOT SIMULATION READY — SYNTHETIC DATA ONLY — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED**
