# Auditoría de los modelos de predicción de cultivo y clima: efecto de las intervenciones

Fecha: 2026-10-22. Alcance: cómo actúan las intervenciones (eventos de tiempo de ejecución) sobre todas las salidas del simulador, en campo abierto y en invernadero, con el
modelo simplificado y con EnergyPlus 26.1. Reproducible con `python -u manual_audit_intervention_effects.py` (escribe `data/audit/intervention_effects.json`).

**Estado científico.** Todo es forzamiento sintético definido por el usuario. Las diferencias son entre dos escenarios simulados, no contra datos reales (no existe ningún dato
`REAL_VERIFIED`). Esta auditoría dice si el comportamiento es físicamente coherente y consistente entre modos; no valida ningún modelo.

## Método

Para cada modo (campo abierto, invernadero simplificado, invernadero EnergyPlus) y cada tipo de evento: la misma simulación con y sin el evento (tomate, 27-feb a 2-mar, 72 h), y
la diferencia de cada salida (media dentro de la ventana, máximo dentro y máximo después). Más tres comprobaciones: cuándo actúa un evento, qué hace con la humedad una ola de
calor, y cómo se comparan los climas interiores de los dos modelos. Lectura del código de cada camino (`_ScenarioWeatherProvider`, `actuator_controls`, `SimplifiedGreenhouseModel`,
`WaterBalanceEngine`, `ClimateStressEngine`, `RadiationGrowthEngine`, la plantilla IDF de EnergyPlus).

## Matriz de efectos (media en la ventana; entre paréntesis el máximo)

| Intervención | Campo abierto | Invernadero simplificado | Invernadero EnergyPlus |
|---|---|---|---|
| Ola de calor +8 °C | T +8,0 exacto; HR sin cambio; VPD +0,23 kPa | T interior +7,97; HR sin cambio; VPD +0,23 | T interior +2,9 (+6,1) porque el calentador compensa; **HR +18,6 puntos y VPD −0,29** |
| Ola de frío −8 °C | T −8,0; estrés por frío y daño por helada suben | T interior −7,97 | T interior −1,7 (−5,5); calefacción +21 kW; HR −19,8 |
| Sequedad | sin efecto (la línea base no llueve) | sin efecto | sin efecto |
| Lluvia 5 mm/h | precipitación +5 mm por paso; el suelo drena todo; nada más cambia | sin efecto (no llueve dentro) | **T interior −1,4 (−7,1); HR +2,3** (superficies mojadas en EnergyPlus) |
| Radiación ×1,5 | radiación +62 W/m²; ET0 +50 %; biomasa sube; T no cambia | radiación +49; **T interior +0,04 K** | radiación +59; T +0,77 (+4,2); calefacción −0,7 kW |
| Radiación ×0,5 | simétrico | T −0,04 | T −1,66 (−7,4) |
| Viento ×3 | **ninguna salida cambia** | **ninguna salida cambia** | T −0,08 (±3,6); calefacción +0,2 kW (+3,6) |
| Riego 2 mm | **ninguna salida cambia** | **ninguna salida cambia** | **ninguna salida cambia** |
| Ventilación 1,0 | no aplica | equivale a **+1 renovación/h**; T −0,02 | equivale a **30 renovaciones/h**; T −4,1 (−9,8); calefacción +33 kW |
| Sombreado 0,6 | no aplica | radiación −58 W/m² (exacto); **T −0,05 K** | radiación −70; T −2,0 (−8,5) |
| CO₂ 0,8 | no aplica | CO₂ +26 ppm; **el cultivo no cambia** | rechazado (no modelado) |

## Lo que funciona correctamente (verificado)

- Los efectos de temperatura, radiación (×1,5 y ×0,5 dan ±62 W/m² exactos), sombreado (radiación × (1 − 0,6)) y precipitación llegan exactamente al forzamiento y con el signo correcto
  a ET0, transpiración, biomasa, estrés por frío, daño por helada y fenología.
- La respuesta es determinista; prefijo más rama reanudada reproduce la ejecución continua (también con clima local).
- EnergyPlus responde de forma físicamente coherente a radiación, sombreado, ventanas y olas de frío/calor (con el calentador compensando), y rechaza el CO₂ con motivo.
- Las salidas que no cambian lo hacen por una causa identificable (más abajo), no por un fallo de cableado, salvo el riego.

## Hallazgos

### Alta gravedad: la intervención no actúa o actúa mal

**1. El riego manual nunca actuaba (CORREGIDO).** `ScenarioRunner._irrigation` devuelve el primer evento de riego activo, y el riego base de la temporada va antes que cualquier evento del usuario.
Evidencia: con el evento "Riego 2 mm", `irrigation_mm`, humedad del suelo y estrés hídrico no cambian en ningún modo. *Corrección propuesta:* gana el último evento activo (el del usuario), coherente
con la regla de que un evento manual anula al controlador. *Corregido:* `ScenarioRunner._irrigation` recorre los eventos en orden inverso; con el evento de 2 mm, `irrigation_mm` pasa de 0,38 a 1,90 mm por paso (2 mm × eficiencia 0,95) solo dentro de su ventana, en campo abierto y en invernadero. La matriz de arriba refleja el estado antes de las correcciones (riego, fase 5.44).

**2. El invernadero simplificado no tenía efecto invernadero (CORREGIDO en la fase 5.44).** El área de intercambio térmico es 1 m² (`thermal_exchange_area_m2 = 1.0`) para un volumen de 1000 m³: la ganancia solar es proporcional a esa
área. Evidencia: al mediodía el interior está **−0,02 K** respecto al exterior (EnergyPlus: **+6,6 K**); radiación ×1,5 sube la T interior +0,04 K; sombrear al 60 % la baja 0,05 K. Consecuencia: en el modelo
simplificado el cultivo ve prácticamente la temperatura exterior, y las intervenciones de radiación o sombreado no tienen efecto térmico. El solucionador es exacto (benchmarks de la fase 5.31), el defecto
está en los parámetros: área, volumen, conductancia y renovaciones no son coherentes entre sí. *Corregido:* el modelo simplificado es ahora un modelo agrupado de dos nodos del MISMO invernadero que simula EnergyPlus (geometría, envolvente, ventilación pasiva y termostato por defecto); al mediodía el interior queda +4,6 K sobre el exterior (EnergyPlus +6,5 K) y el RMSE horario respecto a EnergyPlus es de 2,0 K. Detalle y diferencias residuales en `docs/phase5_44_greenhouse_consistency.md`.

**3. Una orden de ventilación significaba cosas distintas según el modelo (CORREGIDO).** `ActuatorControl(requested, maximum=1)` hace que "ventilación 1,0" sean +1 renovación/h en el simplificado, frente a 30 en
EnergyPlus (30 × más). "Ventanas totalmente abiertas" no hacía nada en el simplificado. *Corregido:* la orden es una fracción de la capacidad de ventanas (30 renovaciones/h) en los dos modelos; ventanas abiertas bajan ahora la temperatura interior 4,0 K en el simplificado y 4,1 K en EnergyPlus, y `greenhouse_ventilation_fraction` es la apertura en ambos.

**4. Las olas de calor y de frío conservaban la humedad relativa, no la humedad absoluta (CORREGIDO para eventos de ejecución).** Una ola de calor de +8 K a HR constante multiplica por 1,68 la presión de vapor del aire. Evidencia (campo abierto,
72 h): VPD del modelo 0,56 kPa frente a **1,20 kPa** si se mantuviera la presión de vapor, es decir, el estrés por VPD de una ola de calor se **subestima 2,1 veces**. En EnergyPlus el aire exterior más cálido y húmedo
**humedece** el invernadero (+18,6 puntos de HR) y baja el estrés por VPD durante una ola de calor: el signo es el contrario al esperado. *Corregido:* los eventos de ola de calor y de frío creados desde la API de ejecución mantienen la presión de vapor del aire (`hold_dew_point`): +8 K en campo abierto baja la HR media 28 puntos en la ventana
y una ola de frío la sube; los escenarios históricos (fases anteriores) conservan su comportamiento y sus hashes. La opción de fijar la HR sigue siendo el evento de humedad.

**5. El viento no hace nada, salvo en EnergyPlus (DOCUMENTADO, no corregido).** El evento promete afectar a `temperature_c` y `et0_mm` pero ninguna salida cambia en campo abierto ni en el simplificado: ET0 es una fórmula tipo Hargreaves con
rango térmico fijo de 10 °C, sin viento, humedad ni VPD, y la ventilación simplificada no depende del viento. En EnergyPlus sí cambia (por la convección exterior de la cubierta). Mismo evento, física distinta según el modelo.
*Decisión:* no se sustituye ET0. Penman-Monteith (FAO-56) horario necesita la geometría solar (latitud, día, hora) para la radiación neta de onda larga y un cociente de nubosidad que el modelo no tiene; elegir esos valores sería inventarlos, y el cambio alteraría la
hidrología de todas las fases y sus hashes. El evento de viento declara ahora que solo actúa mediante EnergyPlus (`affected_variables = temperature_c`, texto en el contrato) y una prueba lo fija. Queda como mejora aparte.

**6. El CO₂ no puede aumentar el crecimiento.** `co2_response = min(1, CO₂/420)`: por encima de 420 ppm no hay efecto, así que el enriquecimiento (práctica habitual en invernadero) es invisible para el cultivo.
EnergyPlus no modela CO₂. La magnitud del evento en el simplificado (+26,7 ppm en equilibrio) es una convención de unidades.

### Media gravedad: coherencia y estructura

**7. Los eventos son capas independientes sobre el forzamiento, sin acoplamiento meteorológico.** La lluvia deja el sol y la humedad intactos; el calor no cambia la radiación; más radiación no calienta el aire exterior. Los
paquetes de la interfaz ("Tormenta", "Caluroso y seco") son la solución manual. Además la lluvia sí enfría EnergyPlus (−7 K en el máximo) y no el simplificado: depende del modelo.

**8. Las líneas base de los dos invernaderos son sistemas físicos distintos.** EnergyPlus lleva siempre un termostato de calefacción (consigna 12 °C y 100 W/m², ambos provisionales), así que su interior nunca baja de 12,0 °C y gasta
9,2 kW de media; el simplificado no tiene calefacción y baja a 3,1 °C. `greenhouse_ventilation_fraction` es una fracción renovada por paso (≈0,95 siempre) en el simplificado y la apertura de ventanas (0–1, media 0,02) en EnergyPlus.
Comparar ambos modos exige saberlo.

**9. Estructura del modelo de cultivo (sin calibrar, documentado en `docs/scientific-limitations.md`).** El crecimiento es radiación interceptada × RUE × producto de factores de estrés; dentro de [mín, máx] el
factor térmico vale 1 (sin curva de temperatura ni respiración), por eso una ola de calor en febrero aumenta la biomasa. RUE (2,0 g/MJ PAR), coeficiente de extinción (0,6) y área foliar específica (0,02) son iguales para todos
los cultivos: solo cambian el LAI máximo y los umbrales del catálogo. La transpiración es ET0 × LAI/3 × factor de fase, sin control estomático ni efecto del VPD o del CO₂. Los parámetros no están calibrados (`docs/parameter_audit_report.md`).

### Baja gravedad

**10. Ventana de los eventos (CORREGIDO para eventos de ejecución).** `ScenarioEvent.active` es cerrado en ambos extremos y el paso se etiqueta con el final del intervalo: un evento de 72 h afecta a **73 pasos** (27-feb 00:00 a 2-mar 00:00), con un
desfase de una hora respecto a la semántica de intervalo (error del 1,4 % en la duración). Además hay una diferencia de **una hora entre tipos de evento**: los de forcing meteorológico (temperatura, radiación, lluvia) actúan en las muestras etiquetadas desde el inicio del evento, y los de actuador (riego, ventilación, sombreado, CO₂) en el paso que *empieza* dentro del evento, es decir, una muestra más tarde.
*Corregido:* los eventos de ejecución son semiabiertos: un evento de N horas actúa sobre exactamente N pasos. Los de forzamiento (muestra etiquetada `t`, la hora que termina en `t`) actúan en `(inicio, fin]` y los de actuador (evaluados al empezar el paso) en `[inicio, fin)`: son los mismos N pasos, sin desfase entre tipos. Los hashes de las ejecuciones con eventos cambian; los escenarios históricos no.

## Plan de corrección sugerido (por impacto)

1. ~~Riego: el último evento activo gana~~ (hecho, con prueba).
2. ~~Invernadero simplificado coherente con EnergyPlus~~ (hecho en la fase 5.44, con prueba de acuerdo entre modelos).
3. ~~Olas de calor/frío: conservar el punto de rocío por defecto~~ (hecho para eventos de ejecución).
4. ~~Semántica común de ventilación y definición única de `greenhouse_ventilation_fraction`~~ (hecho en la fase 5.44).
5. ~~ET0 con viento y VPD o marcar el evento de viento como "solo EnergyPlus"~~ (marcado; Penman-Monteith queda como mejora aparte, ver el hallazgo).
6. Respuesta al CO₂ con efecto de enriquecimiento (con fuente trazable) o avisar de que el evento no afecta al cultivo.
7. ~~Convertir esta matriz en pruebas de regresión~~ (hecho en `tests/test_intervention_effects.py`: las invariantes que ya se cumplen son pruebas normales, y los hallazgos 5 y 6 abiertos son pruebas `xfail` estrictas que fallarán al corregirse el defecto, obligando a actualizar esta nota).

## Límites de esta auditoría

Un solo cultivo (tomate), una sola ventana de 72 h a finales de febrero (poca radiación), una sola tipología de EnergyPlus con valores de envolvente provisionales, sin comparar con mediciones (no existen) y sin
auditar en profundidad la fenología y el modelo de dormancia de los leñosos. Los resultados de EnergyPlus dependen de esos valores provisionales. Que un efecto sea "físicamente plausible" aquí no equivale a validación.
