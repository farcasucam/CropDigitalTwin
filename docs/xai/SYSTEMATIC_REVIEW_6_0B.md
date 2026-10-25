# Revisión de literatura 6.0b (estado del arte y novedad)

Fecha de ejecución: 2026-10-25. Una sola lectora (el asistente), con búsqueda web y lectura de resúmenes. **No es una revisión sistemática con PRISMA**: es un cribado exploratorio de una sola lectura. Falta la segunda lectura del usuario (pendiente en `DECISIONS_XAI.md`) y las bases bibliográficas del protocolo (Scopus, WoS, IEEE, ACM).

Regla aplicada: solo se citan obras que aparecieron en un resultado de búsqueda o lectura de esta sesión. Los datos de autores, año y sede son los vistos; lo que no se vio se marca «no visto». Casi todo lo de 2026 son **preprints sin revisión por pares verificada**.

## 1. Protocolo tal como se ejecutó

**Preguntas**
* Q1: benchmarks de XAI de series temporales y qué verdad de terreno usan.
* Q2: evaluación de atribución/explicación en modelos de fundación de series temporales.
* Q3: explicaciones o narrativas de series temporales con LLM y cómo se evalúa su fidelidad.
* Q4: niveles de evidencia calibrados y verificación determinista de explicaciones generadas.
* Q5: simulador mecanicista o gemelo digital como fuente de contrafácticos para explicaciones en lenguaje natural, y tratamiento del desajuste simulador-realidad.
* Q6: capacidad de los previsores para responder efectos what-if o de intervención (decisiones controladas, cambios de régimen, umbrales).

**Fuentes realmente usadas:** WebSearch (modo «standard» en todas las consultas; no se escaló a «extended») y WebFetch sobre páginas de arXiv. No se consultaron Scopus, WoS, IEEE Xplore, ACM DL ni Google Scholar (sin acceso), así que el protocolo de `PUBLICATION_STRATEGY.md` §3 queda **parcialmente cumplido**.

**Cadenas ejecutadas** (25 búsquedas; las de verificación de obras de partida combinan varios títulos en una sola consulta):
1. `benchmark interpretability time series ground truth saliency evaluation` (Q1)
2. `time series foundation model attribution explanation evaluation TimesFM Chronos explainability` (Q2)
3. `LLM time series explanation narrative faithfulness evaluation hallucination` (Q3)
4. `LLM explanations verified deterministic verifier evidence levels calibrated claims time series` (Q4)
5. `digital twin simulator counterfactual natural language explanation LLM what-if` (Q5)
6. `time series forecasting foundation models counterfactual intervention effect what-if benchmark` (Q6)
7. `explainable AI time series ground-truth attribution causal structural model benchmark counterfactual synthetic simulator "explanation" multivariate` (Q1)
8. `LLM explanation grounded in physics simulator verification of claims against simulation model mismatch sim-to-real explanations` (Q5)
9. `forecasting under controller feedback closed-loop policy intervention forecasts fail counterfactual thermostat regime switching time series foundation models` (Q6)
10. Verificación de obras de partida (títulos y autores, 10 consultas): Turbé; Schlegel; Nauta Co-12; Time-LLM y LLMTime; FActScore, Turpin y Lanham; Jacovi y Adebayo; Ismail; TimeSHAP, WinIT y Dynamask; TimesFM y Chronos-2 (dos consultas); SelfCheckGPT y RAGAS; Wolfert; Turpin por separado.

**Lecturas de resumen (WebFetch, 11 páginas arXiv):** 2610.08118, 2607.27263, 2405.14411, 2505.17801, 2604.02118, 2601.08509, 2606.04505, 2603.06781, 2607.16236, 2605.23978, 2608.19009.

**Criterios de inclusión:** (i) trata series temporales, explicación/atribución, modelos de fundación de series, explicaciones de LLM con verificación, simulador o gemelo como fuente contrafáctica, o previsión what-if; (ii) tiene identificador verificable (arXiv, sede) visto en esta sesión. **Exclusión:** blogs y agregadores como fuente primaria (solo se usaron para localizar la obra); obras sin relación con series temporales ni verificación de texto; trabajos de LLM sobre razonamiento general salvo los de fidelidad de explicación citados en el protocolo.

**Cribado:** una sola lectura, sobre títulos y resúmenes de los resultados devueltos (unas 10 por consulta). No se llevó la cuenta exacta de registros cribados, por eso **no se da cifra PRISMA**. Obras incluidas en la tabla: 36 (obras de partida del protocolo verificadas más hallazgos nuevos; no se separó la cuenta).

## 2. Obras incluidas

Leyenda de «Visto»: **R** = resumen leído por WebFetch; **B** = solo ficha de búsqueda (resumen secundario); no se leyó ningún texto completo.

| ID | Referencia (tal como se vio) | Qué hace | Q | Visto |
|---|---|---|---|---|
| R01 | Ismail, Gunady, Corrada Bravo, Feizi. *Benchmarking Deep Learning Interpretability in Time Series Predictions*. NeurIPS 2020. arXiv:2010.13924 | Benchmark sintético con características informativas conocidas; compara saliencia de gradiente y de perturbación; propone Temporal Saliency Rescaling | Q1 | B |
| R02 | Schlegel, Arnout, El-Assady, Oelke, Keim. *Towards a Rigorous Evaluation of XAI Methods on Time Series*. ICCV Workshop 2019. arXiv:1909.07082 | Evaluación por perturbación de métodos XAI sobre series; sin verdad causal | Q1 | B |
| R03 | Turbé, Bjelogrlic, Lovis, Mengaldo. *Evaluation of post-hoc interpretability methods in time-series classification*. Nature Machine Intelligence 5, 250-260 (2023). arXiv:2202.05656 | Métricas cuantitativas sin reentrenar y conjunto sintético con rasgos discriminativos conocidos | Q1 | B |
| R04 | Nauta et al. *From Anecdotal Evidence to Quantitative Evaluation Methods: A Systematic Review on Evaluating Explainable AI*. ACM Computing Surveys. arXiv:2201.08164 (año de edición no visto) | Propiedades Co-12; 1 de cada 3 trabajos evalúa solo con evidencia anecdótica | Q1 | B |
| R05 | Baer. *xaitimesynth: A Python Package for Evaluating Attribution Methods for Time Series with Synthetic Ground Truth*. arXiv:2603.06781 (2026) | Generador: fondo más patrón local; la ventana es la máscara de verdad; métricas de localización | Q1 | R |
| R06 | Tunyi. *The Failures of Marginal Influence-Based Attribution Methods for Global Time Series Explanations*. IJCAI 2026 XAI Workshop. arXiv:2607.16236 | Define «fidelidad al DAG» respecto al grafo que aprendió el modelo; SHAP no la cumple en general | Q1, Q2 | R |
| R07 | Crabbé, van der Schaar. *Explaining Time Series Predictions with Dynamic Masks*. ICML 2021 (PMLR 139:2166-2177). arXiv:2106.05303 | Método Dynamask de máscaras temporales | Q1 | B |
| R08 | Leung et al. *Temporal dependencies in feature importance for time series predictions* (WinIT). ICLR 2023 | Importancia con dependencia temporal por ventanas | Q1 | B |
| R09 | Bento, Saleiro, Cruz, Figueiredo, Bizarro. *TimeSHAP: Explaining Recurrent Models through Sequence Perturbations*. KDD 2021. arXiv:2012.00073 | Extiende KernelSHAP a secuencias | Q1 | B |
| R10 | Das et al. *A decoder-only foundation model for time-series forecasting* (TimesFM). ICML 2024. arXiv:2310.10688 | Modelo de fundación de previsión | Q2, Q6 | B |
| R11 | Ansari et al. *Chronos-2: From Univariate to Universal Forecasting*. arXiv:2510.15821 (2025) | Previsión multivariante y con covariables mediante atención de grupo | Q2, Q6 | B |
| R12 | *Explainable Load Forecasting with Covariate-Informed Time Series Foundation Models*. arXiv:2604.28149 (autores no vistos) | SHAP sobre Chronos-2 en previsión de carga; los patrones coinciden con el conocimiento del dominio | Q2 | B |
| R13 | *Time series saliency maps: explaining models across multiple domains*. arXiv:2505.13100 (autores no vistos) | Mapas de saliencia con TimesFM como caso, con descomposición STL | Q2 | B |
| R14 | Sivalingam, Mandal, Kumar, Deshpande. *TSQueryBench: LLM-as-a-Judge for Time Series Explanations*. ICML FMSD. arXiv:2604.02118 (2026) | 500 series y 10 tipos de consulta con explicaciones correctas, parciales e incorrectas; el LLM juez es más fiable que el generador | Q3, Q4 | R |
| R15 | Chamroukhi. Póster RAVE (Relevance-Aligned Validation of Explanations). HAL hal-05403229 (2025) | Alinea las variables que cita la narrativa del LLM con las atribuciones tipo SHAP | Q3 | B |
| R16 | Jin et al. *Time-LLM: Time Series Forecasting by Reprogramming Large Language Models*. ICLR 2024. arXiv:2310.01728 | Previsión con LLM congelado | Q3 | B |
| R17 | Gruver, Finzi, Qiu, Wilson. *Large Language Models Are Zero-Shot Time Series Forecasters*. NeurIPS 2023. arXiv:2310.07820 | LLMTime: previsión como completado de texto | Q3 | B |
| R18 | Min et al. *FActScore*. EMNLP 2023. arXiv:2305.14251 | Fidelidad por hechos atómicos frente a una fuente | Q3, Q4 | B |
| R19 | Manakul, Liusie, Gales. *SelfCheckGPT*. EMNLP 2023. arXiv:2303.08896 | Detección de alucinación por consistencia entre muestras | Q3 | B |
| R20 | Es, James, Espinosa-Anke, Schockaert. *Ragas*. EACL 2024 (demo). arXiv:2309.15217 | Evaluación sin referencia de RAG | Q3 | B |
| R21 | Turpin, Michael, Perez, Bowman. *Language Models Don't Always Say What They Think*. NeurIPS 2023. arXiv:2305.04388 | La cadena de pensamiento puede tergiversar la causa real de la predicción | Q3 | B |
| R22 | Lanham et al. *Measuring Faithfulness in Chain-of-Thought Reasoning*. Anthropic, 2023. arXiv:2307.13702 | Mide la fidelidad alterando el razonamiento | Q3 | B |
| R23 | Jacovi, Goldberg. *Towards Faithfully Interpretable NLP Systems*. ACL 2020, pp. 4198-4205. arXiv:2004.03685 | Define fidelidad (graduada) frente a plausibilidad | Q3 | B |
| R24 | Adebayo et al. *Sanity Checks for Saliency Maps*. NeurIPS 2018 | Algunos mapas de saliencia no dependen del modelo ni de los datos | Q1 | B |
| R25 | Yin. *Grading the Graders: Verification Autonomy Levels (L0-L5) for LLM Reasoning*. arXiv:2608.19009 (2026, v3) | Escala L0-L4 según el ancla de verificación; la verificación empírica abierta llega solo a «corrección anclada» (L2) | Q4 | R |
| R26 | *Most claims cannot be checked: coverage limits on instrument-grounded verification of LLM scientific explanations*. NeurIPS 2026, neurips.cc/virtual/2026/159053 (autores no vistos) | Verificador determinista con abstención: el 58-83 % de las afirmaciones queda sin canal verificable | Q4 | B |
| R27 | *Claim-Level Confidence Calibration for Reliable Decision Making with Large Language Models*. arXiv:2608.22483, NeurIPS 2026 (autores no vistos) | Calibra la confianza por afirmación atómica | Q4 | B |
| R28 | Chen et al. *Do Models Explain Themselves? Counterfactual Simulatability of Natural Language Explanations*. ICML 2024. arXiv:2307.08678 | Mide si la explicación permite predecir salidas del modelo ante entradas alteradas | Q3, Q5 | B |
| R29 | Zhang, Vergara-Marcillo, Diamantopoulos, Shen, Tziritas, Bahsoon, Theodoropoulos. *Large Language Models for Explainable Decisions in Dynamic Digital Twins*. DDDAS 2024. arXiv:2405.14411 | Capa de explicación con LLM para gemelos digitales; caso de agricultura inteligente (drones) | Q5 | R |
| R30 | Gyevnár, Lucas, Albrecht, Cohen. *Integrating Counterfactual Simulations with Language Models for Explaining Multi-Agent Behaviour* (AXIS). arXiv:2505.17801 (2025, v2) | El LLM consulta un simulador («what if», «remove») y verbaliza; conducción autónoma | Q5 | R |
| R31 | Yang, Li, Rodríguez. *Simulate, Reason, Decide* (MechSim). arXiv:2606.04505 (2026) | Esquema de simulador (supuestos, variables, trazas) y verificación de que la explicación es fiel a los mecanismos | Q4, Q5 | R (más detalle en la ficha de búsqueda) |
| R32 | Won. *Attenuated in-context identification in time-series foundation models: diagnosis under counterfactual inputs and repair by synthetic forced-system fine-tuning*. arXiv:2610.08118 (6 oct 2026) | Prueba Chronos-2, TimesFM-2.5 y TabPFN-TS con contrafácticos exactos en sistemas forzados | Q2, Q6 | R |
| R33 | Thumm, Anthony, Chen. *DoTime: A Synthetic Benchmark Generator for Interventional and Counterfactual Time Series*. arXiv:2607.27263 (2026) | Generador de SCM temporales con intervenciones, contrafácticos y regímenes conmutados; verdad exacta | Q1, Q6 | R |
| R34 | Jang, Jin, Park, Chae, Kim. *What If TSF*. arXiv:2601.08509 (2026, v2) | Fija el contexto y varía el escenario futuro; mide si el previsor reacciona en el sentido esperado | Q6 | R |
| R35 | Schmitt. *Algometrics: Forecasting Under Algorithmic Feedback*. arXiv:2605.23978 (2026) | Demuestra que el riesgo de despliegue con retroalimentación no es identificable solo con datos pasivos | Q6 | R |
| R36 | Wolfert, Ge, Verdouw, Bogaardt. *Big Data in Smart Farming – A review*. Agricultural Systems 153 (2017) 69-80 | Revisión de datos masivos en agricultura | contexto | B |

Todas las obras de partida del protocolo se localizaron; los matices de verificación están en §3.

## 3. Obras de partida del protocolo: estado de verificación

| Obra de partida | Estado |
|---|---|
| Ismail et al. 2020 | Verificada (R01) |
| Schlegel et al. 2019 | Verificada (R02) |
| Turbé et al. 2023 | Verificada (R03) |
| Nauta et al. (Co-12) | Verificada; el año de edición en ACM CSUR **no visto** (R04) |
| Jacovi y Goldberg 2020; Adebayo et al. 2018 | Verificadas (R23, R24) |
| TimeSHAP, WinIT, Dynamask | Verificadas (R09, R08, R07). WinIT: solo se vio «Leung et al.», autores completos no vistos |
| Time-LLM; LLMTime | Verificadas (R16, R17) |
| TimesFM; Chronos-2 | Verificadas (R10, R11); no se leyó el artículo, solo fichas |
| Turpin 2023; Lanham 2023 | Verificadas (R21, R22) |
| FActScore; SelfCheckGPT; RAGAS | Verificadas (R18, R19, R20) |
| Wolfert 2017 | Verificada (R36). Las «revisiones posteriores» de agricultura inteligente y XAI **no se buscaron: no verificado** |
| Co-12 «12 propiedades» tal como las lista la estrategia | La búsqueda confirma «12 propiedades, por ejemplo compactness y correctness»; la lista completa de la estrategia **no se contrastó** |

## 4. Tabla de huecos por pregunta

| Q | Qué existe | Qué NO se encontró (en estas búsquedas) |
|---|---|---|
| Q1 | Verdad sintética por **máscara de rasgo** (R01, R03, R05); evaluación por perturbación sin verdad (R02); DoTime (R33) da verdad interventiva exacta pero **no evalúa XAI** | Un banco de XAI con **efectos causales interventivos medidos con pares de ejecuciones de un simulador físico en lazo cerrado** y errores de sensor realistas. No encontrado, no demostrado que no exista |
| Q2 | SHAP y saliencia sobre Chronos-2 y TimesFM como demostraciones (R12, R13); análisis interno (hallado en la búsqueda 2, no incluido por ser solo ficha) | Un banco de calidad de atribución para modelos de fundación **frente a verdad interventiva** |
| Q3 | Juez LLM con anclaje numérico (R14); alineación narrativa-atribución sin referencia (R15); fidelidad de cadena de pensamiento (R21, R22) | Evaluación de narrativas de series **contra efectos causales verdaderos** (no solo contra los datos observados) |
| Q4 | Escalas de verificación (R25), verificador determinista con abstención y cobertura limitada (R26), calibración por afirmación (R27), verificación contra mecanismos (R31) | Una combinación de **niveles de evidencia L1-L3 con verificador determinista** para series temporales de un sistema físico; R25-R27 son preprints recientes y no tratan series |
| Q5 | LLM más simulador contrafáctico (R29, R30) y verificación mecanística (R31) | Tratamiento **explícito del desajuste simulador-realidad** (en las fichas leídas no aparece) y un **doble gemelo** con parámetros perturbados y medida de cómo se degrada la explicación |
| Q6 | Previsores y escenarios (R34), what-if con contrafácticos exactos (R32), generador interventivo (R33), retroalimentación algorítmica (R35) | Fallo de previsores específicamente ante **umbral latente o interbloqueo de PLC** con la historia sin excitar el umbral; R32 no menciona umbrales ni lazo cerrado en lo visto |

## 5. Declaración de novedad matizada por contribución

**C1, banco con verdad interventiva.** Ya existen bancos de XAI de series con verdad **por rasgo localizado** (R01, R03, R05) y un generador de series con **intervenciones y contrafácticos exactos** pero sin XAI (R33). Lo que no se encontró es la **combinación**: verdad de efecto causal por pares de ejecuciones de un simulador físico multivariante, con controlador y errores de sensor, usada para evaluar atribución. Reposicionar: no «primer benchmark con verdad» (R01 y R05 ya tienen verdad, de otro tipo), sino «verdad **interventiva** de un sistema en lazo cerrado», y citar DoTime como trabajo más cercano en generación. Diferenciar con claridad verdad de rasgo frente a verdad de efecto. Hay que releer DoTime completo antes de afirmar la diferencia (solo se leyó el resumen).

**C2, hallazgo negativo con mecanismo.** **Esto ya existe en parte.** Won (R32, 6 oct 2026) muestra que TimesFM-2.5 se comporta como un modelo **sin memoria** respecto a la covariable y que Chronos-2 subestima los efectos (0,33 a 0,80 de lo verdadero) en sistemas forzados con contrafácticos exactos. Por tanto «los modelos de fundación no reproducen contrafácticos» **no es novedoso**. Lo que sigue pendiente de contraste: (i) el mecanismo del **umbral latente / interbloqueo** con historia que no lo excita (no aparece en lo leído de R32); (ii) la medida de la **atribución** del previsor frente a la verdad interventiva (Q2: no hallada); (iii) el modelo TimesFM 3 del proyecto frente al 2.5 de R32. Reposicionar C2 como **extensión con un mecanismo distinto**, citar R32 como antecedente y reproducir su protocolo (dither de contexto) como línea base. Riesgo: la comparación de la estrategia (signo 0,64; 0 de 19 pares planos) debe discutirse junto a «atenuación» y «sin memoria» de R32. Conviene leer R35 sobre no identificabilidad con retroalimentación: respalda el argumento teórico (la historia de lazo cerrado no identifica el contrafáctico).

**C3, pipeline neuro-simbólico con evidencia por niveles y simulador imperfecto.** Hay trabajos cercanos en piezas sueltas: LLM más simulador contrafáctico (R29, R30), verificación contra mecanismos (R31), escalas de verificación (R25) y calibración por afirmación (R27). No se encontró, en estas búsquedas, la combinación **series temporales físicas + niveles de evidencia + verificador determinista + L3 desde un simulador imperfecto con ablación frente a un previsor** ni una **medida del desajuste del gemelo de trabajo**. Reposicionar: la novedad probable está en (a) la **ablación A3a (previsor) frente a A3b (gemelo)** y (b) la **robustez al desajuste** (doble gemelo), no en «usar simulador con LLM» (R29 y R30 ya lo hacen; R29 incluso en agricultura). MechSim (R31) es el competidor más cercano: leerlo completo y compararlo en la sección de trabajos relacionados. Evitar el nombre «niveles de evidencia» como si fuera nuevo (R25 usa «niveles» con otro sentido): definir los propios con precisión.

**C4, módulo abierto `tsxai`.** Existe `xaitimesynth` (R05) y el generador DoTime (R33), ambos paquetes abiertos. La contribución por sí sola es de ingeniería; su valor depende de C1-C3. Declararlo así y compararlo en una tabla de funciones con R05 y R33. (El estudio con expertos de C4 en la formulación del encargo no se buscó en esta revisión: **no cubierto**.)

## 6. Cambios sugeridos al diseño (no aplicados)

* Reescribir C2 como «mecanismo de umbral latente en lazo cerrado» citando R32 y R35.
* Añadir a la línea base de C2 el protocolo de R32 (dither de contexto) y comparar Chronos-2 y TimesFM con ARX (R32 muestra que la identificación clásica gana en 3 de 4 plantas reales).
* En C3, comparar contra el esquema de R31 y contra la capa LLM de R29.
* En el artículo, mapear métricas a Co-12 (R04) y cuidar la distinción fidelidad/plausibilidad (R23).

## 7. Limitaciones de esta revisión

* **Una sola lectora**, sin segunda lectura ni acuerdo entre revisores; sesgo de confirmación posible, sobre todo en los huecos.
* **Herramientas:** búsqueda web general (no bases bibliográficas), una lectura de resúmenes; ningún texto completo leído. La herramienta de lectura devuelve resúmenes procesados por un modelo pequeño y puede omitir matices (por ejemplo, que R32 no mencione umbrales se dedujo solo de la página de resumen).
* **No exhaustiva:** 25 consultas en modo «standard»; no se hizo cadena de citas (snowballing) ni búsqueda por sinónimos (por ejemplo «what-if» con «CPS», «PLC», «HVAC»). Dominios cercanos no explorados: edificios y HVAC, control predictivo con modelos, causalidad de series (Granger, SCM) y XAI de control.
* **Preprints recientes:** la mayoría de las obras de 2026 (R05, R06, R12-R14, R25-R27, R31-R35) no tienen revisión por pares verificada; sus cifras no se contrastaron.
* **Fiabilidad de las fichas:** varias obras (marcadas B) se conocen solo por fichas secundarias; la sede y el año son los que mostraron esas fichas.
* No se incluyen cifras de cribado ni diagrama PRISMA porque no se produjeron.
* La ausencia de un resultado en la búsqueda **no prueba** que el trabajo no exista: debe repetirse en Scopus/WoS/Google Scholar antes de afirmar novedad en el artículo.

## 8. Qué leer primero

1. **R32** Won (2610.08118): el antecedente más cercano de C2; reposiciona la contribución.
2. **R33** DoTime (2607.27263): el más cercano a C1 en generación de verdad interventiva.
3. **R31** MechSim (2606.04505) y **R30** AXIS (2505.17801): los más cercanos a C3 (simulador más LLM, verificación).
4. **R35** Algometrics (2605.23978): base teórica para la no identificabilidad en lazo cerrado.
5. **R14** TSQueryBench (2604.02118) y **R25** Verification Autonomy Levels (2608.19009): para Q3 y Q4.
6. **R01** Ismail et al. y **R05** xaitimesynth: para posicionar C1 frente a la verdad de rasgo.
7. **R04** Nauta et al. (Co-12): marco de métricas.
