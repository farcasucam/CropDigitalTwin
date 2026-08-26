# Crop Engine

## Responsabilidad

Representar el estado agronómico y calcular su evolución.

## Fuente

`crop_config.json` es la fuente de configuración de cultivos. Contiene `default_crop`, cultivos, fases, thresholds de temperatura, VPD, VWC, radiación e irrigación.

## Entradas

- temperatura;
- radiación;
- humedad/VPD;
- CO2;
- VWC;
- agua disponible;
- fase actual;
- timestep.

## Salidas

- biomass;
- LAI;
- development_stage;
- water_stress;
- temperature_stress;
- vpd_stress;
- growth_rate.

## VPD

Debe calcularse una sola vez mediante un servicio dedicado y quedar disponible como variable derivada.

La documentación suministrada define VPD como diferencia entre presión de vapor de saturación y presión real y aporta rangos generales. Estos rangos no sustituyen los thresholds específicos de cada cultivo/fase.

## Thresholds

El motor debe consultar los thresholds de la fase activa, no codificarlos en el controlador.

## Crecimiento MVP

Implementar una función simplificada y estable:

```text
potential_growth
    × radiation_factor
    × temperature_factor
    × vpd_factor
    × water_factor
```

El resultado modifica biomasa y desarrollo.

Debe quedar encapsulado para poder sustituirse por un modelo agronómico avanzado.
