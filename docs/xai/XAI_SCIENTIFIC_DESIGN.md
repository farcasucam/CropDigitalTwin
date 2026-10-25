# Diseño científico de la fase XAI de series temporales del invernadero

Complemento de `XAI_TIMESERIES_DESIGN.md` (arquitectura y fases de ingeniería). Este documento fija **la pregunta científica, las hipótesis, el banco de pruebas, las métricas, el análisis estadístico y las amenazas a la validez**. Estado: **PROPUESTA**, a registrar antes de ejecutar experimentos.
Punto de partida: el TFG `docs/xai/TFG.pdf` (Agro-IA Command Center), leído en sus capítulos 2, 3, 6, 7 y 8. Las referencias bibliográficas de este documento están citadas de memoria: **verificar cada una antes de publicar**.

---

> **Publicación:** este diseño es la base metodológica de un artículo Q1 de IA explicativa aplicada; las contribuciones, el posicionamiento, la revisión sistemática, la ciencia abierta y los riesgos de rechazo están en `docs/xai/PUBLICATION_STRATEGY.md`, y la estructura del software en `docs/xai/XAI_MODULE_ARCHITECTURE.md`.

## 1. Qué hizo realmente el TFG en su fase numérica (y qué no)

**Lo implementado** (TFG §6.3.2-6.3.5, 6.10, 6.11):
* `TimeSeriesAnalyzer` con degradación elegante: **STL** (mínimo 2 ciclos = 48 puntos horarios), **PELT** (`mean_shift_up/down`, `variance_shift`) y **Holt-Winters** (proyección a 24 h, p. ej. para anticipar que un secado cruce el punto de marchitez); si faltan `statsmodels`/`ruptures`, un analizador básico (deltas y pendientes lineales).
* `ForecastAnalyzer` sobre el pronóstico a 48 h de Open-Meteo con **umbrales por familia de cultivo** (p. ej. VPD > 1,8 kPa en solanáceas); variables derivadas (GDD, DLI, punto de rocío, VPD); ventana de 72 h de sensores; fusión con series Sentinel-2 (NDVI/NDMI cada ~5 días) por CoT.
* Capa semántica (`SemanticEnricher`/`SemanticFormatter`), RAG con `rag_audit`, `ConsistencyChecker` con reglas duras, Glass Box UI.

**Cómo se validó** (TFG §7.1.4, 7.2, tablas 8-9): escenarios sintéticos de un catálogo, **revisión manual** (10/12 narrativas temporales coherentes, 9/12 recomendaciones coherentes, 4 correcciones del verificador, 17/20 consultas RAG útiles, 4,2/5 de valoración), latencias. El propio TFG dice que **no es un experimento estadístico** ni una certificación agronómica (§7.1.4, §7.2, §8.3).

**Brechas científicas** (esto es lo que el diseño debe cerrar):
| # | Brecha | Consecuencia |
|---|---|---|
| B1 | No hay **verdad de terreno**: no se sabe cuántos cambios reales detecta PELT ni cuántos falsos positivos produce | Imposible afirmar que «distingue un riego de un fallo de sensor» |
| B2 | Sin **línea base** ni ablación: no se muestra que el enriquecimiento mejore al LLM frente a pasarle los datos de otra forma | La tesis central («ceguera matemática» mitigada por el enriquecimiento) está sin contrastar |
| B3 | **Describir no es explicar**: STL/PELT/HW dan *qué pasó*, no *por qué*; la causa la «infiere» el LLM | Riesgo de causalidad inventada, justo lo que el XAI debe evitar |
| B4 | Ventana de **72 h** = 3 ciclos diarios: STL y Holt-Winters con estacionalidad 24 h están en el límite de lo estimable | Componentes inestables; sin análisis de sensibilidad |
| B5 | Univariante por variable; el «multivariante» es la lectura conjunta del LLM | Sin análisis de dependencias ni de confusión (radiación → temperatura → VPD) |
| B6 | Sin **incertidumbre** en las detecciones ni en la proyección; umbrales de «evento» vs «deriva» no justificados | El texto («descenso acelerado») no tiene respaldo cuantitativo |
| B7 | Evaluación de calidad **subjetiva** (estrellas, revisión manual) y N pequeño | Sin medidas de acuerdo entre evaluadores ni intervalos |
| B8 | El «razonamiento» del Glass Box es el que el LLM *genera*; no hay prueba de que refleje lo que el modelo usó | Plausible no implica fiel (ver §3) |

Veredicto de suficiencia: como **pretratamiento descriptivo** que da contexto a un LLM, es una base razonable y barata. Como **XAI** es **insuficiente** hasta cerrar B1-B3 y B8. Este diseño lo hace sin perder lo que el TFG ya aporta.

---

## 2. Marco conceptual: qué es «explicar» aquí

Se distinguen **cuatro niveles de explicación**, cada uno con su propia verdad de terreno y su propia métrica. Ninguna afirmación del sistema puede salir con un nivel superior al que tiene respaldo.

| Nivel | Pregunta | Método | Verdad de terreno en el gemelo | Escala de Pearl aproximada |
|---|---|---|---|---|
| **L1 Descriptivo** | ¿Qué ha pasado? | STL/MSTL, puntos de cambio, tendencias por tramo, variables derivadas | Anotaciones: eventos, cambios de actuador, cambios de etapa, fallos inyectados | Asociación |
| **L2 Atributivo** | ¿Qué factores pesan en el estado o en la previsión? | Atribución sobre el pronosticador (oclusión, permutación, gradientes, SHAP agrupado) | Efecto **interventivo** de cada factor medido en pares de ejecuciones del gemelo | Asociación del *modelo* (verificada contra intervención) |
| **L3 Contrafáctico** | ¿Qué pasaría si cambiara X? | **Ejecución pareada del gemelo de trabajo** (D14, D15); la previsión con covariable futura editada queda como objeto de estudio (RQ4) | Ejecución pareada del gemelo verdad con el mismo cambio (EnergyPlus para las series de energía) | Intervención |
| **L4 Lingüístico** | ¿Cómo se lo cuento a una persona sin falsear nada? | LLM con salida estructurada + verificador | Hechos con identificador del L1-L3; reglas del catálogo | (fidelidad del texto) |

**Dos nociones de fidelidad que no se deben mezclar** (Jacovi & Goldberg, 2020; Doshi-Velez & Kim, 2017):
* **Fidelidad al modelo:** ¿la explicación refleja lo que *el pronosticador* usa? Se mide con pruebas de borrado/inserción y pruebas de cordura (Adebayo et al., 2018: aleatorizar pesos y datos).
* **Fidelidad al mundo (aquí, al gemelo):** ¿coincide con el efecto causal real del sistema simulado? Se mide contra la verdad interventiva.
El caso interesante es **alta fidelidad al modelo y baja al mundo**: el modelo usa una correlación espuria. Eso es un hallazgo, no un fallo del método.

**Límite epistemológico que se declara siempre:** el gemelo es un modelo, no la naturaleza. «Verdad de terreno» significa *«verdad del sistema simulado»*. Ninguna conclusión se extiende al invernadero real sin datos intervenidos reales (ver §9).

**Doble gemelo (D15, 2026-10-25).** Para que el L3 no sea circular (verdad y evidencia del mismo modelo), se separan dos papeles:
* **Gemelo verdad:** parámetros del banco; las series de energía (`greenhouse_heating_kw`, `greenhouse_cooling_kw`) con el backend **EnergyPlus**. Genera los datos (con error de sensor) y los efectos verdaderos. El explicador no lo consulta.
* **Gemelo de trabajo:** el que tiene el explicador; parámetros **perturbados** dentro de los rangos declarados (auditoría de parámetros, conjunto de incertidumbre de la fase 5.23; nada inventado) y backend simplificado. Su desajuste con el verdad es a la vez **paramétrico y estructural**.
* **Niveles de desajuste:** 0 (mismo modelo: techo de referencia, nunca resultado principal), pequeño y grande. Un **conjunto** de gemelos de trabajo da evidencia calibrada: «confirmado en k de n variantes».
* Que un previsor falle frente al gemelo **no valida el gemelo**: solo muestra que hace falta un modelo con la estructura del sistema. La validez frente al invernadero real sigue pendiente de datos reales.

---

## 3. Sobre la «cadena de pensamiento» como explicación

Turpin et al. (2023) y Lanham et al. (2023) muestran que el razonamiento en cadena que un LLM verbaliza **no es necesariamente fiel** a los factores que determinaron su respuesta. Por tanto, el panel «Razonamiento del agente» del Glass Box **no se presenta como el razonamiento del modelo**, sino como una **justificación renderizada y fundamentada**: cada paso cita `fact_id`s verificables, y es el verificador determinista, no el LLM, el que garantiza que lo citado existe y dice lo afirmado. La explicación tiene su valor en la **trazabilidad a la evidencia numérica**, no en la introspección del LLM. Esto debe figurar tal cual en la interfaz y en la memoria.

---

## 4. Preguntas de investigación e hipótesis (a registrar antes de ejecutar)

Cada hipótesis tiene una **métrica primaria**, una **comparación** y un **criterio de rechazo** que se fijan en la partición de desarrollo antes de ver la de prueba. Los umbrales numéricos de este documento son **provisionales** (convención de diseño, no valores agronómicos) y se congelan en `docs/xai/PREREGISTRATION.md`.

### RQ1 (L1): ¿recuperan STL/PELT/Holt-Winters la estructura conocida de las series del gemelo con ruido realista?
* **H1a:** PELT aplicado al **residuo de STL** mejora la detección frente a PELT sobre la serie cruda (que mezcla el ciclo diario con los saltos).
* **H1b:** la detección degrada gradualmente con el ruido y la autocorrelación, y cae en regímenes de **conmutación por umbral** (apertura de ventanas a 24 °C, saturación del termostato), donde el cambio de media no es un salto limpio.
* **H1c:** la ventana de 72 h es **insuficiente** para estimar una estacionalidad estable; 7-14 días mejora la separación tendencia/residuo.
* Métrica primaria: **F1 con margen de tolerancia** y **Covering** (van den Burg & Williams, 2020) frente a las anotaciones; margen justificado por la constante de tiempo del sistema (horas, no muestras sueltas). Secundarias: retardo de detección, falsos positivos por 1000 h sin evento, clasificación *evento discreto* vs *deriva* (matriz de confusión).
* Comparadores: umbral de z-score sobre residuo, CUSUM, BinSeg, BOCPD, MSTL (Bandara et al., 2021) con periodos 24 y 168.

### RQ2 (previsión): ¿qué aporta TimesFM 3 frente a líneas base sobre series del gemelo?
* **H2:** TimesFM supera a naive estacional y Holt-Winters a 24-168 h con covariables futuras, pero **no necesariamente** a un modelo entrenado en el dominio (regresión con retardos, boosting, TFT/N-HiTS entrenados con datos ilimitados del simulador) ni a Chronos-2.
* Métricas: **MASE** (Hyndman & Koehler, 2006), **pérdida por cuantiles/CRPS** (Gneiting & Raftery, 2007), **cobertura empírica** de los cuantiles; orígenes rodantes; por régimen (día/noche, evento/no evento, ventanas abiertas/cerradas).
* Es la **puerta de viabilidad 6.3a** del diseño de ingeniería.

### RQ3 (L2): ¿concuerdan las atribuciones con el efecto interventivo del gemelo?
* **H3a:** la fidelidad al mundo es **alta** para factores fuertemente acoplados y suaves (radiación → temperatura interior) y **baja** para actuadores con umbral (ventilación, termostato) y para variables lentas (agua del suelo).
* **H3b:** los métodos agnósticos (oclusión/permutación **por bloques que preservan el ciclo diario**) son más fieles al mundo que los basados en gradiente en este dominio, porque no dependen de la geometría local del modelo; a comprobar (Ismail et al., 2020, observan que muchos métodos de saliencia fallan en series temporales).
* **H3c:** sustituir por cero o por la media (perturbación fuera de distribución) **infla** la atribución frente a la permutación por bloques.
* Métricas primarias (por ventana y factor): **concordancia de signo**, **Spearman** entre la atribución y el efecto interventivo del gemelo sobre el conjunto de factores, **solapamiento top-k**. Secundarias: error relativo de magnitud, curvas de borrado/inserción (AOPC), **estabilidad** (Spearman entre ventanas adyacentes y bajo ruido pequeño), pruebas de cordura de Adebayo.
* Métodos: oclusión/permutación (agnóstico), ablación de ventanas de contexto, gradientes integrados y gradiente×entrada (TimesFM es PyTorch: caja blanca accesible en la Spark), **KernelSHAP agrupado** por factor y bloque temporal, sustituto lineal local. **Líneas base de XAI:** atribución aleatoria, gradiente de una constante, y el efecto de un modelo lineal con retardos (sustituto transparente).

### RQ4 (L3): ¿reproduce TimesFM el efecto contrafáctico?
* **H4:** el signo y el orden de magnitud de Δprevisión coinciden con Δgemelo en los factores principales, con dependencia del régimen; el **ancho de los cuantiles** cubre el Δgemelo con la frecuencia nominal solo si está calibrado (se mide, no se supone).
* Métricas: concordancia de signo, error relativo, **cobertura del efecto verdadero por el intervalo contrafáctico**.
* **Estado (D14, desarrollo, 2026-10-25):** negativa. Concordancia de signo 0,64 frente a 0,8 exigido; 0 de 19 pares en contextos sin actividad previa del controlador (mecanismo: el umbral nunca excitado no se puede aprender). Se confirma una sola vez en la partición de prueba; su generalidad se contrastó en el reactor con PLC (6.3e): allí el ridge falla igual haya visto o no disparar el enclavamiento (0,569 frente a 0,556), de modo que la explicación por falta de excitación **no generaliza** (el fallo es genérico de un modelo lineal retardado frente a un lazo cerrado). El previsor deja de ser fuente de L3 en el producto.

### RQ4b (L3 con modelo imperfecto): ¿cuánto se degrada el contrafáctico del gemelo de trabajo frente al verdad?
* **H4b:** con desajuste pequeño, el contrafáctico del gemelo de trabajo supera al del mejor previsor en concordancia de signo y en Spearman de la integral; la ventaja disminuye con el desajuste y puede desaparecer en el grande. La concordancia del conjunto (k de n) está calibrada: cuando k/n es alto, el signo acierta con una frecuencia comparable.
* Métricas: las de RQ4 por nivel de desajuste y por régimen (activo/plano, calefacción/refrigeración), calibración de k/n (diagrama de fiabilidad). Comparador: el mejor previsor de RQ4 sobre los mismos casos.

### RQ5 (L4): ¿es fiel el texto?
* **H5a:** con hechos con identificador y verificador, la tasa de **afirmaciones sin respaldo** tras el verificador es ≤ 2 % (umbral provisional) y la de **cifras inventadas** es 0 % tras *fail-closed*.
* **H5b:** el **nivel de evidencia** declarado en el texto (observado / asociado / estimado por el modelo / confirmado por el gemelo) no supera el respaldado (tasa de *sobreafirmación causal*).
* **H5c:** **paridad ES/EN**: mismos hechos → mismos conjuntos de afirmaciones (acuerdo ≥ 95 %, provisional).
* **H5d:** abstención correcta ante imposibilidades plantadas (umbral ausente, serie constante, datos con huecos).
* Métricas: *claim support rate* (estilo FActScore, Min et al., 2023, pero con verificador **determinista** en lugar de otro LLM), fidelidad numérica, sobreafirmación, paridad, abstención. Además evaluación **humana** (RQ7).

### RQ6 (ablación): ¿qué componente del pipeline reduce la alucinación y mejora la corrección?
Mismo LLM, `temperature=0`, N repeticiones, mismas preguntas:
| Brazo | Qué recibe el LLM |
|---|---|
| A0 | La serie numérica cruda (dígito a dígito, Gruver et al., 2023) |
| A1 | Estadísticos resumen (media, mín., máx., pendiente) |
| A2 | **Enriquecimiento del TFG** (STL, PELT, Holt-Winters, umbrales) en Markdown |
| A3a | A2 + atribución del previsor **con su fidelidad medida** (lenguaje de asociación, nunca causal) |
| A3b | A2 + contrafácticos del **gemelo de trabajo** con su nivel de evidencia (k de n variantes) |
| A4 | A3a + A3b + verificador determinista (*fail-closed*) |
* **H6:** A0 < A1 < A2 < A3b ≤ A4 en corrección y en alucinación, con efecto medible en cada escalón; **A3b > A3a** en las afirmaciones causales (la evidencia del simulador supera a la del previsor); **el escalón A2→A3b es la aportación de este trabajo** (el TFG llega a A2). El RAG no forma parte de ningún brazo (D16).
* Métricas: exactitud de afirmaciones frente a verdad plantada, alucinación (cifras y causas), obediencia al esquema, latencia, coste en tokens.

### RQ7 (utilidad humana)
* **H7:** con la explicación completa, expertos identifican la causa de un evento plantado con más exactitud y/o rapidez que con solo gráficas o con la narrativa del TFG.
* Diseño: estudio *within-subject* con asignación aleatoria del orden, casos plantados con verdad conocida, **N** documentado y justificado (potencia modesta: se declara), medidas de acuerdo entre evaluadores (**α de Krippendorff**), escala de confianza y carga cognitiva; resultado = estimación con intervalo, no significación aislada. Niveles de evaluación según Doshi-Velez & Kim: funcional (RQ1-6) y humano/aplicación (RQ7).

---

## 5. El banco de pruebas: «GCTSB» (Greenhouse Causal Time-Series Benchmark)

Un conjunto de escenarios **generados por el gemelo**, con verdad conocida de cuatro tipos. Se publica con el código (no con los pesos de TimesFM, por licencia).

**Factores de generación (cada celda, con semillas):**
* Cultivo (los 7), entorno (campo abierto, invernadero agrupado, EnergyPlus en paso síncrono), opción de realimentación del cultivo, ET0 histórico o Penman-Monteith.
* **Temporadas**: los ciclos sintéticos y los **11 años del archivo local (2015-2025)** de las 6 zonas: tiempo real como forzamiento, lo que da variedad climática genuina.
* **Eventos** (ola de calor/frío, sequedad, lluvia, radiación alta/baja, viento, riego, ventilación, sombreado, CO₂) con instante, duración e intensidad muestreados por hipercubo latino; estrategias de control (sin controlador, termostato por defecto, controlador AUTO).
* **Ruido y fallos de sensor** inyectados **sobre la observación**, nunca sobre el estado: ruido blanco y AR(1), deriva lenta, valor atascado, huecos, picos, retardo. **Los parámetros del modelo de ruido son supuestos declarados**, no mediciones; se hace un barrido de severidad (sin ruido, bajo, medio, alto) y se informa la dependencia.

**Verdad de terreno:**
* **G1 – cambios:** anotación de eventos, conmutaciones de actuador, cambios de etapa fenológica, fallos inyectados, con su instante exacto.
* **G2 – efectos interventivos:** para cada escenario, **pares de ejecuciones** (base frente a base con un factor perturbado) → efecto causal exacto sobre cada variable y retardo; matriz factor × variable × horizonte. Es la referencia de RQ3.
* **G3 – estado verdadero frente a observado:** el estado del gemelo es la verdad; el sensor es la verdad más ruido/fallo. Permite medir detección de fallos de sensor y de «consumo real frente a lectura errónea» (lo que el TFG afirma sin medir).
* **G4 – contrafácticos de previsión:** ejecución del gemelo con la covariable futura editada, para RQ4.

**Particiones y fuga:** división **por temporada y por cultivo**, nunca por hora ni por ventana; desarrollo (fijar umbrales) y prueba (informar una sola vez). Las covariables futuras solo contienen información realmente conocida en el instante de corte (test automático anti-fuga).
**Escala:** cada ejecución cuesta ~1 s (invernadero agrupado) o ~6 s (EnergyPlus síncrono); 1000 escenarios con 10 perturbaciones caben en horas en la Spark o el portátil. El tamaño se fija por **análisis de potencia** para intervalos de confianza de anchura objetivo.

---

## 6. Diseño de la fase numérica (qué se mejora respecto al TFG)

1. **Preprocesado explícito.** Alineación de frecuencias (sensor 15 min a horario por agregación declarada; Sentinel-2 irregular **sin interpolación ciega**, con retardos explícitos), marcado de huecos (no imputar), y **detección previa de fallos** (límites físicos, tasa de cambio, valor atascado, residuo frente a un pronosticador) para no confundir fallo con fenómeno.
2. **STL → MSTL** robusto con periodos 24 h y 168 h; **fuerza de tendencia y de estacionalidad** (Wang, Smith & Hyndman, 2006) como hechos con su confianza; **análisis de sensibilidad a la longitud de ventana** (72 h, 7 d, 14 d). Si la ventana no soporta la estimación, la salida lo dice y no emite componentes.
3. **Puntos de cambio sobre el residuo STL y sobre la tendencia por separado**; PELT con penalización por **BIC** (no a ojo), costes de media, varianza y **pendiente** (cambio de tendencia por tramos); comparación con BinSeg/BOCPD; regla de decisión *evento discreto frente a deriva* evaluada con matriz de confusión; **retardo de detección** documentado.
4. **Holt-Winters como línea base**, con intervalos; la proyección de referencia pasa a ser TimesFM **solo si** supera la puerta 6.3a. Evaluar cuándo HW con 3 ciclos es degenerado.
5. **Análisis multivariante real:** correlación cruzada con retardos, y causalidad de Granger / descubrimiento causal en series (PCMCI, Runge et al., 2019) **como generadores de hipótesis**, nunca como prueba; el acuerdo con G2 mide cuándo son fiables (la confusión por causa común, p. ej. radiación sobre temperatura y VPD, es el caso de estudio).
6. **Incertidumbre en cada hecho:** cada detección y cada tendencia lleva intervalo o confianza; el vocabulario cerrado («descenso acelerado») tiene **umbrales relativos al ruido** y se prueba con series de forma conocida; el texto solo emite lo que supera su umbral.
7. **Variables derivadas deterministas** (GDD, DLI, punto de rocío, VPD) tomadas del gemelo, con sus unidades y sus umbrales por etapa del catálogo (no por «familia» genérica).
8. **Nivel de evidencia en cada hecho** (observado, asociado, estimado por el modelo, confirmado por el gemelo) que el LLM debe respetar y el verificador comprueba.

---

## 7. Plan de análisis estadístico

* **Unidad de análisis:** el escenario (o la ventana dentro del escenario), **no la hora**: las horas están autocorrelacionadas y inflarían la significación.
* **Intervalos:** *bootstrap* por bloques/escenarios; modelos mixtos con efectos aleatorios de temporada y cultivo cuando haya anidamiento.
* **Comparaciones pareadas** (mismo escenario, distintos métodos): Wilcoxon de rangos con signo o *bootstrap* pareado; **tamaños de efecto** (Cliff's δ, diferencia de medias con IC) por encima del valor p.
* **Comparaciones múltiples:** corrección de Holm o control de la tasa de falsos descubrimientos.
* **Preregistro:** hipótesis, métricas primarias, umbrales y análisis congelados antes de tocar la partición de prueba; los análisis exploratorios se etiquetan.
* **Resultados negativos** se informan con el mismo detalle (p. ej. si TimesFM no usa bien los actuadores).
* **Reproducibilidad:** semillas, hashes de ejecución del gemelo, versiones de imágenes por digest, caché *record/replay* del LLM; el texto del LLM no entra en el hash pero sí `prompt_hash`/`response_hash`.

---

## 8. Amenazas a la validez

| Tipo | Amenaza | Mitigación |
|---|---|---|
| Constructo | La verdad es la del **gemelo**, no la de la naturaleza; el modelo de cultivo no está calibrado | Se declara en cada resultado; «fidelidad al gemelo» es el único término permitido; plan de transición a datos reales (§9) |
| Constructo | El ruido de sensor inyectado es un supuesto | Barrido de severidad y varios modelos de ruido; informar sensibilidad |
| Interna | Fuga entre ajuste y prueba; sobreajuste de umbrales | División por temporada/cultivo, preregistro, test anti-fuga |
| Interna | Perturbaciones fuera de distribución (ceros/medias) en la atribución | Permutación por bloques que preserva el ciclo; comparación explícita (H3c) |
| Externa | Pocos cultivos/zonas; solo datos simulados o reanálisis | 7 cultivos × 6 zonas × 11 años; declarar el alcance |
| Estadística | Autocorrelación, comparaciones múltiples, N pequeño en el estudio humano | Unidad de escenario, Holm, potencia declarada, intervalos |
| LLM | No determinismo, sensibilidad al prompt, cambio de versión | `temperature=0`, esquema, repeticiones, imagen fijada, ≥ 2 modelos en la ablación |
| Operativa | Licencia de pesos TimesFM (no redistribuibles) | Publicar código, datos y resultados; los pesos se obtienen del origen |

---

## 9. De lo simulado a lo real (alcance futuro, no de esta fase)

Con datos reales no hay verdad interventiva gratuita. El camino honesto: (1) **experimentos de escalón planificados** en un invernadero (p. ej. ventilación fija durante varias horas) que dan efectos interventivos reales con los que medir la fidelidad; (2) **experimentos naturales** con cuidado de confusión; (3) el enfoque **híbrido**: el gemelo predice la física y un modelo (TimesFM o similar) predice el residuo respecto al sensor, con detección de anomalías; (4) validación por técnicos con el protocolo de RQ7. Hasta entonces, todo resultado de este trabajo es «explicación de un modelo sobre series simuladas».

---

## 10. Entregables y encaje con las fases de ingeniería

| Entregable | Fase (de `XAI_TIMESERIES_DESIGN.md`) |
|---|---|
| `PREREGISTRATION.md` (hipótesis, métricas, umbrales, plan estadístico) | 6.0 |
| Generador GCTSB (escenarios, perturbaciones pareadas, ruido/fallos, anotaciones G1-G4, particiones) | **nueva 6.1b**, tras 6.1 |
| Analizador con MSTL/PELT sobre residuo/preprocesado + **evaluación RQ1** | 6.2 |
| **Puerta 6.3a** (RQ2, RQ4 parcial) con comparadores (naive, HW, regresión con retardos, boosting, entrenado en dominio, Chronos-2) | 6.3 / 6.3a |
| Capa semántica con niveles de evidencia + **evaluación H5** | 6.4 |
| Atribución y contrafácticos + **evaluación RQ3/RQ4** (informe de fidelidad) | 6.5 |
| Verificador con tasa de detección sobre salidas adversarias | 6.7 |
| **Ablación A0-A4 (RQ6)** y estudio humano (RQ7), informe científico | 6.9 |

**Criterios de parada honestos (decisiones, no promesas):** si RQ4 falla para los factores principales, la explicación L2/L3 se construye sobre un modelo agnóstico (regresión con retardos o modelo entrenado) y TimesFM queda como comparador; si RQ1 muestra que PELT/STL no superan al z-score sobre residuo, el analizador se simplifica y se declara. Ambos resultados son publicables.

---

## 11. Referencias (citadas de memoria: verificar antes de publicar)

* Adebayo et al. (2018). *Sanity checks for saliency maps.* NeurIPS.
* Bandara, Hyndman, Bergmeir (2021). *MSTL: A seasonal-trend decomposition algorithm for time series with multiple seasonal patterns.*
* Cleveland et al. (1990). *STL: a seasonal-trend decomposition procedure based on loess.* J. Official Statistics.
* Doshi-Velez & Kim (2017). *Towards a rigorous science of interpretable machine learning.*
* Gneiting & Raftery (2007). *Strictly proper scoring rules, prediction, and estimation.* JASA.
* Gruver et al. (2023). *Large language models are zero-shot time series forecasters (LLMTime).* NeurIPS.
* Hyndman & Koehler (2006). *Another look at measures of forecast accuracy.* Int. J. Forecasting.
* Ismail et al. (2020). *Benchmarking deep learning interpretability in time series predictions.* NeurIPS.
* Jacovi & Goldberg (2020). *Towards faithfully interpretable NLP systems.* ACL.
* Jin et al. (2023). *Time-LLM: Time series forecasting by reprogramming large language models.*
* Killick, Fearnhead, Eckley (2012). *Optimal detection of changepoints with a linear computational cost (PELT).* JASA.
* Lanham et al. (2023). *Measuring faithfulness in chain-of-thought reasoning.*
* Lundberg & Lee (2017). *A unified approach to interpreting model predictions (SHAP).* NeurIPS.
* Min et al. (2023). *FActScore: fine-grained atomic evaluation of factual precision.* EMNLP.
* Runge et al. (2019). *Detecting and quantifying causal associations in large nonlinear time series datasets (PCMCI).* Science Advances.
* Sundararajan et al. (2017). *Axiomatic attribution for deep networks.* ICML.
* Turpin et al. (2023). *Language models don't always say what they think: unfaithful explanations in chain-of-thought prompting.* NeurIPS.
* van den Burg & Williams (2020). *An evaluation of change point detection algorithms.*
* Wang, Smith, Hyndman (2006). *Characteristic-based clustering for time series data.* Data Mining and Knowledge Discovery.
