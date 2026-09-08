# Guía de recogida de datos agrícolas

Este documento describe los datos que necesitamos recopilar para poder estudiar y calibrar progresivamente un modelo de crecimiento vegetal. No es necesario disponer de todos los datos. Deben rellenarse únicamente las variables realmente medidas.

## Prioridad

**Nivel 1, imprescindible:** parcela, cultivo, variedad, plantación o trasplante, meteorología, fechas fenológicas, cosecha y producción.

**Nivel 2, muy recomendable:** humedad de suelo, riego y LAI.

**Nivel 3, excelente:** biomasa, crecimiento de fruto, microclima, CO2, PAR y actuadores.

Una campaña de una parcela, una variedad y un ciclo completo ya puede ser útil. Es preferible recibir datos reales incompletos pero trazables que datos completos obtenidos mediante estimaciones no documentadas.

## Cómo rellenar las plantillas

Las plantillas están en `data/templates/agricultural/`. Cada archivo representa un tipo de información y puede entregarse vacío si no existe esa medición. No se debe inventar una fecha o un valor desconocido. Dejar la celda vacía y conservar el registro.

- `plot_id` es un identificador estable de parcela.
- `crop_cycle_id` identifica un ciclo concreto, incluso si dos ciclos usan la misma parcela.
- Usar las variedades conocidas del proyecto cuando correspondan: tomate RAF, pimiento Lamuyo, uva Monastrell y ciruela Suplum 26. No inventar una variedad para melocotón o manzana.
- Usar `outdoor` o `greenhouse` en `environment`.
- Mantener la frecuencia real. No crear mediciones intermedias.
- Los eventos fenológicos son observaciones, no predicciones.
- Registrar el método real (`weather_station`, `ceptometer`, `soil_probe`, `field_observation`, `harvest_scale`, etc.). Si se desconoce, usar `UNKNOWN`.
- Registrar `uncertainty` o `uncertainty_days` cuando el protocolo la proporcione.

## Tiempo y unidades

Toda medición temporal debe usar `YYYY-MM-DDTHH:MM:SS+timezone`, por ejemplo `2026-05-06T09:00:00+02:00`. Para España, documentar `Europe/Madrid`. Un evento puede tener precisión diaria si esa es la precisión real; no añadir una hora inventada.

| Variable | Unidad recomendada |
|---|---|
| Temperatura | °C |
| Humedad relativa | % |
| Radiación solar | W/m² |
| Velocidad del viento | m/s |
| Precipitación | mm |
| Humedad de suelo | m³/m³ |
| Conductividad eléctrica | dS/m |
| Riego | L |
| LAI | m²/m² |
| Biomasa | g/m² |
| Producción | kg |
| Peso de fruto | g |
| Longitud y diámetro | mm |
| CO2 | ppm |
| PAR | µmol/m²/s |

El sistema puede normalizar algunas unidades, pero conserva la unidad original. El `depth_cm` de suelo es obligatorio cuando hay sensores a distintas profundidades. No convertir altura de planta en LAI ni estimar biomasa si nunca se midió.

## Faltantes, calidad e incertidumbre

Usar vacío para un valor no medido; nunca usar `0` para representar ausencia de medición. La calidad puede ser `VALID`, `MISSING`, `ESTIMATED`, `INVALID` o `SUSPECT`. `ESTIMATED` debe indicar una estimación real documentada, no una interpolación manual. No interpolar LAI ni rellenar curvas entre medidas; cualquier imputación futura será una operación separada y trazable.

## Invernadero y actuadores

Si existe instrumentación, registrar temperatura y humedad interior, CO2, PAR, radiación interior, ventilación, sombreo, calefacción, refrigeración y riego. Estos datos describen el microclima o los actuadores; no son observaciones fisiológicas del cultivo. Para actuadores se recomienda conservar `timestamp`, `greenhouse_id`, `actuator`, `state`, `value` y `unit`.

## Lo que no hace falta aportar

No es necesario conocer RUE, SLA, coeficiente de extinción, Tbase, Tupper, parámetros DSSAT ni parámetros internos del Digital Twin. Esos parámetros pertenecen al modelo y a su futura calibración. El técnico aporta observaciones, no parámetros del modelo.

## Entrega y trazabilidad

La meteorología de estación puede marcarse `REAL_WORLD`; los datos de Open-Meteo, `OPEN_METEO`. No mezclar weather forcing con observaciones de LAI, biomasa o cosecha. Los CSV reales entrarán por `ObservationIngestion`, que valida unidades, exige timestamps con zona horaria, conserva provenance y reporta problemas sin ocultarlos.

Los datos sintéticos del proyecto viven en `data/synthetic/phase5_9/` y son exclusivamente para pruebas y demostración. Nunca deben entregarse como datos medidos.
