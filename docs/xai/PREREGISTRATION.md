# Preregistro de la evaluación XAI (BORRADOR)

Estado: **BORRADOR, no congelado.** Se congela (se anota el hash del documento y del diseño del banco, y se etiqueta el repositorio) cuando termine el desarrollo de cada fase y **antes** de ejecutar nada sobre la partición de prueba. Después de congelar, cualquier cambio es una **desviación** que se anota con fecha y motivo en la sección 8, no una edición silenciosa.

Fuentes: `docs/xai/XAI_SCIENTIFIC_DESIGN.md` (preguntas, hipótesis, métricas, análisis), `src/xai_benchmark_design.json` (diseño del banco, convenciones de muestreo), `src/xai_variable_roles.json` (roles de variable).

## 1. Objeto

Evaluar, sobre series simuladas por el gemelo con verdad conocida, (a) si el análisis determinista recupera los cambios, (b) si TimesFM 3 pronostica y reproduce contrafácticos mejor o peor que líneas base, (c) si las atribuciones concuerdan con el efecto interventivo del gemelo, (d) si el texto generado es fiel y cuánto aporta cada componente, y (e) si ayuda a expertos a identificar causas. **Toda conclusión es «fidelidad al gemelo», no al invernadero real.**

## 2. Material fijo

| Elemento | Valor |
|---|---|
| Versión del gemelo (etiqueta del repositorio) | _a rellenar al congelar_ |
| Diseño del banco (`content_hash`) | _a rellenar_ |
| Roles de variable (`content_hash`) | _a rellenar_ |
| Particiones | por **cultivo y temporada** (`crop\|synthetic-<semilla>`), sal `gctsb-1`, 30 % prueba; la partición de prueba **no se toca** hasta el congelado y se evalúa **una sola vez** |
| Escala del banco | _N escenarios por celda a fijar con análisis de potencia sobre desarrollo_ (objetivo: intervalos de confianza del 95 % de anchura ≤ la fijada por métrica) |
| Verdad | G1 cambios, G2 efectos interventivos (eventos y sondas), G3 observación con errores de sensor, G4 contrafácticos de previsión |

## 3. Hipótesis y métricas primarias

Los umbrales son **provisionales** (convenciones de diseño) y se fijan sobre la partición de desarrollo antes del congelado. «Gana» significa diferencia pareada por escenario con intervalo de confianza que excluye 0.

| ID | Hipótesis | Métrica primaria | Comparador | Criterio provisional |
|---|---|---|---|---|
| H1a | PELT sobre la serie **desestacionalizada** (observada menos componente estacional de STL) detecta mejor que sobre la serie cruda. Variante de ablación: PELT sobre el residuo STL (el tendencia absorbe parte del salto: la 6.2 lo midió así en datos plantados) | F1 con margen (margen = ± 3 h, justificado por la constante de tiempo; el piloto de desarrollo barre ± 2, ± 3 y ± 6) y Covering | PELT crudo, z-score sobre residuo, residuo STL, CUSUM, BinSeg, BOCPD, MSTL | Mejora de F1 con IC > 0 |
| H1b | La detección degrada con ruido y en regímenes de umbral | F1 por nivel de ruido y por régimen | — | Curva informada, sin umbral |
| H1c | 72 h no basta para estimar la estacionalidad; 7-14 d sí | Fuerza de tendencia/estacionalidad y error de recuperación por longitud de ventana | 72 h, 7 d, 14 d | Informe |
| H2 | TimesFM supera a naive estacional y Holt-Winters; no necesariamente a un modelo entrenado en el dominio | MASE y pérdida por cuantiles; cobertura empírica | Naive, HW, regresión con retardos, boosting, modelo entrenado, Chronos-2 | Informe por régimen; la decisión de la puerta 6.3a usa H4 |
| H3a | Fidelidad al mundo alta para factores suaves y baja para umbrales y variables lentas | Concordancia de signo y Spearman con G2 | Atribución aleatoria, modelo lineal con retardos | Signo ≥ 0,8 y Spearman ≥ 0,6 en factores principales (provisional) |
| H3b | Los métodos agnósticos por bloques son más fieles que los de gradiente | Spearman con G2 | Gradiente integrado, gradiente×entrada, KernelSHAP agrupado | Diferencia pareada con IC > 0 |
| H3c | La perturbación fuera de distribución infla la atribución | Diferencia de Spearman entre sustitución por cero/media y permutación por bloques | — | IC > 0 |
| H4 | El contrafáctico de TimesFM coincide en signo y orden con el gemelo; sus cuantiles cubren el efecto | Concordancia de signo; error relativo; cobertura del efecto verdadero | — | **Puerta 6.3a:** signo ≥ 0,8 y Spearman ≥ 0,6 en los factores principales; si no, la explicación L2/L3 se construye sobre un modelo agnóstico |
| H5a | Afirmaciones sin respaldo tras el verificador ≤ 2 %; cifras inventadas 0 % tras *fail-closed* | Tasa de afirmaciones sin respaldo y de cifras huérfanas | A0-A3 | ≤ 2 % y 0 % (provisional) |
| H5b | El nivel de evidencia del texto no supera el respaldado | Tasa de sobreafirmación causal | A2 | ≤ 2 % (provisional) |
| H5c | Paridad ES/EN | Acuerdo de conjuntos de afirmaciones y `fact_id` | — | ≥ 95 % (provisional) |
| H5d | Abstención correcta ante imposibilidades plantadas | Exactitud de la abstención | — | ≥ 90 % (provisional) |
| H6 | A0 < A1 < A2 < A3 ≤ A4 en corrección y alucinación | Exactitud de afirmaciones y alucinación por brazo | Brazos A0-A4 | Escalones con IC > 0; A2→A3 es la aportación del trabajo |
| H7 | Con la explicación completa, los expertos identifican mejor y/o más rápido la causa | Exactitud y tiempo de identificación; confianza | Solo gráficas; narrativa A2 | Estimación con IC; α de Krippendorff informado |

## 4. Análisis estadístico (fijo)

* Unidad: **escenario** (y ventana dentro del escenario), nunca la hora.
* Intervalos: *bootstrap* por escenario/bloque, 10 000 remuestreos, semilla fija; modelos mixtos con temporada y cultivo como efectos aleatorios cuando haya anidamiento.
* Pareado: Wilcoxon de rangos con signo o *bootstrap* pareado; tamaño de efecto (Cliff's δ o diferencia de medias con IC).
* Comparaciones múltiples: Holm dentro de cada familia de hipótesis.
* Resultados negativos se informan con el mismo detalle.
* Los análisis no previstos se etiquetan **exploratorios**.

## 5. Procedimiento

1. Desarrollar y fijar umbrales **solo** con la partición de desarrollo.
2. Congelar: hash de este documento, del diseño y de los roles; etiqueta del repositorio; imágenes de contenedor por *digest*; semillas.
3. Ejecutar sobre la partición de prueba **una vez**; archivar `manifest.json`, resultados y hashes.
4. Informar todo, incluidas las hipótesis no confirmadas.

## 5b. Contexto principal y escala (decisiones D8-D11, 2026-10-25; borrador)

* **Análisis primario:** invernadero con control encendido (contexto C), escala horaria. Objetivos explicados: `greenhouse_heating_kw`, `greenhouse_cooling_kw` y la energía del controlador, ante el forzamiento exterior. El clima interior es una consecuencia observada, no una palanca.
* **Circularidad:** en C las salidas del controlador (apertura de ventanas, extractor, sombreado, riego) no se dan nunca como covariables futuras ni como plan; solo una intervención que fija una de ellas puede declararla como plan. Medido en el piloto: darlas como plan inflaba la puerta contrafáctica (acuerdo en signo de 0,70 a 0,40 en TimesFM 3.0 al aislarlas).
* **Contrastes de generalización (secundarios):** exterior sin control, invernadero sin control y el reactor con PLC. Los resultados de cada contexto se informan por separado, sin promediarlos con C.
* **Tamaño:** el piloto de desarrollo tiene pocos casos en C; el análisis primario se hace sobre un banco ampliado en C, con intervalos por bloques (cultivo y temporada) y cálculo de potencia antes de congelar.
* **Criterio de volumen (decisión derivada de desarrollo, 2026-10-25):** la demanda del controlador es intermitente (más de la mitad de los contextos cortos no tienen demanda previa), de modo que el pico del efecto y las métricas escaladas (MASE, RMSSE) quedan indefinidos o degenerados en gran parte de los casos. Se adopta como criterio principal del contrafáctico la **integral del efecto** sobre el horizonte comparado (kWh con muestra horaria), con acuerdo en signo, error relativo y Spearman entre casos; el pico queda como criterio secundario. En el backtest se añaden, sin sustituir al MASE (cuyas indeterminaciones se cuentan), la coincidencia de encendidos con tolerancia ±2 h (F1 sobre recuentos agrupados; la tolerancia la declara el anfitrión en `TimeScale`), el MAE condicionado dual (instantes con demanda y, siempre a su lado, instantes sin demanda) y la integral sobre el horizonte. Estas decisiones se toman viendo resultados de desarrollo y así se registran.
* **Estratificación por actividad previa (exploratoria):** pares activos (demanda sumada en la ventana de contexto previa al corte > 0) frente a planos (idénticamente cero); nunca se usa información del horizonte. Celdas con menos de 10 pares: «no estimable». Intervalos al 95 % remuestreando cultivo-temporada. Regla de lectura fijada antes de ver las cifras: si un previsor falla en los planos y acierta en los activos, falla por falta de excitación previa; si falla en ambos, la excitación no lo explica.
* **Fuera del alcance primario:** la escala de temporada (discusión y trabajo futuro).

## 6. Estudio con expertos (RQ7)

La aprobación ética **está concedida**. Se registran aquí, al congelar: número de expertos, criterios de inclusión, consentimiento, casos (plantados, con verdad conocida), orden aleatorizado de condiciones, cálculo de la potencia (modesta: se declara), variables medidas y análisis.

## 7. Qué NO se afirmará

Causalidad sobre el invernadero real; calibración o validación experimental del modelo de cultivo; generalización a cultivos o parcelas no simulados; calidad de previsión en general; que el razonamiento mostrado sea el razonamiento interno del modelo de lenguaje.

## 8. Registro de desviaciones

_Vacío hasta el congelado._

Cambios previos al congelado (no son desviaciones): 2026-10-24, fase 6.2: la señal primaria de PELT pasa del residuo STL a la serie desestacionalizada, y el residuo queda como variante de ablación; el criterio de materialidad de un cambio verdadero (`|efecto| ≥ fracción × DE` de la serie) es una convención provisional que se barre (0,1; 0,25; 0,5).
