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

## MVP implementado y auditoría 4.1

`CropEngine` implementa estrés térmico, hídrico y de VPD usando los thresholds
de la etapa activa. Los índices están normalizados en `[0, 1]`; `cumulative_stress`
es la media del estrés actual y `growth_factor` es su complemento.
`development_index` y `biomass` son proxies dependientes de `dt` simulado, sin
unidades físicas ni calibración agronómica.

`stage_name`, `months`, `solar_radiation_thresholds` e `irrigation` se cargan
y conservan en `CropStageDefinition`, pero la auditoría confirma que todavía
no intervienen en el cálculo del MVP. Quedan preparados para una futura
especificación de fenología, radiación y riego; no se interpretan aquí de forma
inventada.

## Fase 4.2: evolución temporal MVP

`CropEngine.advance(...)` recibe un `CropState` explícito y un `dt_seconds`
simulado. Reutiliza la evaluación de estrés de la etapa activa y evoluciona
`development_index` y `biomass` con el proxy temporal existente. `dt=0` es un
no-op y los valores negativos se rechazan. El resultado no depende de la
velocidad del reloj de pared.

El JSON actual no contiene grados-día, temperatura base de desarrollo,
duraciones ni umbrales de transición. Por eso esta fase no inventa una
fenología GDD ni transiciones entre stages: `development_stage` permanece en
la etapa configurada hasta que exista una especificación parametrizada.

La configuración fenológica futura será opcional y validable, pero permanece
inactiva mientras no existan datos agronómicos por cultivo y etapa. El
contrato preparado admite métodos `gdd`, `calendar` o `external`, etapas en
orden explícito y valores `null` para datos aún no suministrados. No ejecuta
transiciones. La auditoría también distingue la plantilla vacía
`config/crop_config.json` del catálogo efectivo `src/crop_config.json`.

La Fase 4.4 prepara sin activar la fenología. El contrato opcional valida
método, etapas ordenadas, trazabilidad de fuente y estado de calibración,
pero no ejecuta GDD, chilling ni transiciones automáticas. Los parámetros
agronómicos necesarios todavía deben suministrarse por cultivo/cultivar.
