# Estrategia de publicación (artículo Q1 de IA explicativa aplicada)

Directriz (2026-10-24): **la parte XAI del proyecto servirá para un artículo científico de calidad Q1 en IA explicativa aplicada**; el resto del proyecto (el gemelo) será un **segundo artículo**. Este documento fija cómo se diseña, se ejecuta y se redacta el trabajo para que sea publicable en ese nivel. No garantiza la aceptación: reduce los motivos de rechazo previsibles.

Las referencias están citadas de memoria y las cuartiles de revista **no están verificadas**: comprobar JCR/Scopus/SJR vigentes antes de decidir destino.

## 1. Pregunta central y contribuciones

**Pregunta:** *¿Se pueden generar explicaciones en lenguaje natural de series temporales multivariantes de un sistema físico que sean **fieles** (a la causalidad real del sistema), **calibradas** (nunca afirman más de lo que su evidencia permite) y **verificables** (cada afirmación se traza a un hecho), y qué aporta cada componente del pipeline?*

Las contribuciones se enuncian como **hipótesis contrastables**, no como hechos:

| ID | Contribución candidata | Evidencia que la sostiene | Riesgo |
|---|---|---|---|
| **C1** | Un **banco de pruebas con verdad interventiva** (efectos causales exactos medidos con pares de ejecuciones de un simulador) para XAI de series temporales multivariantes con errores de sensor realistas | El banco GCTSB y su datasheet, publicados | Que ya exista algo equivalente: exige la revisión sistemática de §3 |
| **C2** | Un **hallazgo de fidelidad con mecanismo**: los previsores basados en datos, incluido un modelo de fundación (TimesFM 3), no reproducen los contrafácticos de un sistema en lazo cerrado cuando la historia no excita el umbral del controlador; la atribución del previsor se mide frente a la verdad interventiva (D14) | RQ3, RQ4 (negativa en desarrollo: signo 0,64; 0 de 19 pares planos) confirmada en prueba; generalidad en el reactor con PLC (6.3e) | Que el mecanismo no se repita en el reactor o en prueba: se informa igual |
| **C3** | Un **pipeline neuro-simbólico con evidencia por niveles y verificación determinista**, cuyo L3 lo aporta un **simulador imperfecto** (doble gemelo, D15), con ablación A0-A4 (A3a previsor frente a A3b gemelo) y robustez ante el desajuste del modelo | RQ4b, RQ5 y RQ6 | Que la ventaja del gemelo desaparezca con poco desajuste, o que la mejora dependa del LLM (≥ 2 LLM y repeticiones) |
| **C4** | Un **módulo abierto, modular e integrable** con pruebas de contrato y, si se decide, un segundo dominio | El paquete `tsxai`, sus ejemplos y su suite de contrato | Se queda en «ingeniería» si no hay evaluación: por eso va ligado a C1-C3 |

**Lo que NO es la contribución:** «un TFG con un LLM»; el gemelo (segundo artículo); previsión por sí misma; una interfaz.

## 2. Qué espera un revisor de XAI aplicada (y cómo se cubre)

| Expectativa del revisor | Cómo la cubre el diseño |
|---|---|
| **Evaluación cuantitativa de la explicación**, no solo ejemplos | Métricas definidas de antemano (`XAI_SCIENTIFIC_DESIGN.md` §4), verdad de terreno, intervalos |
| **Fidelidad frente a plausibilidad** (Jacovi & Goldberg, 2020) | Fidelidad al modelo y al mundo, por separado (§2 del diseño científico) |
| Evaluación humana **bien diseñada** | RQ7 con expertos (sin comité de ética, D17), consentimiento informado, aleatorización, α de Krippendorff, potencia declarada |
| **Líneas base** serias, incluidas simples | Naive, Holt-Winters, regresión con retardos, boosting, modelo entrenado, Chronos-2; atribución aleatoria y modelo lineal transparente |
| **Ablación** | Brazos A0-A4 con el mismo LLM |
| **Generalización** más allá de un caso | 7 cultivos × 3 entornos × 40 temporadas × niveles de ruido; segundo dominio (decisión abierta) |
| **Reproducibilidad** | Preregistro, semillas, hashes, imágenes por digest, código y datos abiertos, registro/reproducción del LLM |
| **Limitaciones honestas** | «Verdad del sistema simulado», ruido supuesto, modelos de 7-8B, licencias; sección propia |
| **Impacto práctico** | Caso de uso real (gestión de invernadero), expertos, vector rendimiento-agua-energía |
| **Ética y datos** | Sin comité de ética (D17; se declara según la norma de la universidad y de la revista); consentimiento y anonimato de los expertos; sin datos personales; el TFG no se redistribuye |

### Marco de evaluación reconocido
Alinear las métricas con propiedades establecidas de la evaluación de XAI evita la acusación de «métricas propias a medida». Se propone mapearlas a las **12 propiedades Co-12** (Nauta et al., 2023: corrección, completitud, consistencia, continuidad, contrastividad, complejidad de covariables, compacidad, composición, confianza, contexto, coherencia, controlabilidad) y a los niveles de evaluación de Doshi-Velez & Kim (2017). Entregable: una tabla propiedad → métrica → hipótesis en el artículo.

## 3. Estado del arte: revisión sistemática previa (nueva fase 6.0b)

Sin una revisión rigurosa no se puede afirmar novedad. Se añade una fase **antes de implementar más** con un protocolo registrado:

* **Preguntas:** ¿qué benchmarks de XAI de series temporales existen y qué verdad usan?; ¿qué se ha evaluado sobre atribución en modelos de fundación de series temporales?; ¿qué trabajos explican series temporales con LLM y cómo evalúan su fidelidad?; ¿qué se hace con evidencia calibrada y verificación determinista? Pregunta añadida (D14): ¿se usa un simulador mecanicista como fuente de contrafácticos para explicaciones en lenguaje natural, y cómo se trata su desajuste con el sistema real? **Estado: Primera pasada (resúmenes) y segunda lectura de los 4 trabajos más cercanos (2026-10-25), ambas del asistente: la segunda con texto completo obtenido mediante extractos de una herramienta, **sin contrastar con los PDF**, y con MechSim (apéndice C.6) y AXIS (apéndices) sin leer entera. Resultado: C2 deja de ser «los modelos de fundación fallan en contrafácticos» (Won, 2610.08118, ya lo muestra sin umbrales, lazo cerrado, atribución ni decisiones controladas) y pasa a ser **el mecanismo de umbral latente en lazo cerrado y las consultas de decisiones controladas**; C3 se mantiene (ninguno de MechSim, AXIS y Won tiene gemelo verdad frente a gemelo de trabajo perturbado, «k de n variantes», ablación previsor-frente-a-gemelo ni verificación determinista); C1 más débil en la generación (DoTime) pero íntegro como XAI evaluada frente a verdad interventiva. Falta la lectura humana y contrastar con los PDF (`docs/xai/SYSTEMATIC_REVIEW_6_0B_SECOND_READING.md`).**
* **Fuentes:** Scopus, Web of Science, IEEE Xplore, ACM DL, arXiv/OpenReview (el estado del arte de TS-XAI y de LLM está en preprints), Google Scholar para la cadena de citas.
* **Cadenas de búsqueda** registradas (por ejemplo: «time series» AND (explainab* OR interpretab*) AND (benchmark OR faithfulness OR ground truth); «foundation model» AND «time series» AND (attribution OR explanation); «LLM» AND «time series» AND (explanation OR narrative) AND (faithful* OR hallucinat*); «counterfactual» AND «time series» AND «simulator»), criterios de inclusión y exclusión, cribado por dos lecturas cuando sea posible, diagrama PRISMA.
* **Obras de partida** (verificar cada una): Ismail et al. (2020, benchmark de interpretabilidad en series temporales); Schlegel et al. (2019, evaluación de XAI en series temporales); Turbé et al. (2023, evaluación de métodos post-hoc en series temporales); Nauta et al. (2023, Co-12); Jacovi & Goldberg (2020); Adebayo et al. (2018); trabajos de TimeSHAP, WinIT, Dynamask; Time-LLM (Jin et al., 2023) y LLMTime (Gruver et al., 2023); TimesFM y Chronos-2; Turpin et al. (2023) y Lanham et al. (2023) sobre fidelidad de la cadena de pensamiento; FActScore (Min et al., 2023), RAGAS y SelfCheckGPT para fidelidad de texto; literatura de agricultura inteligente y IA explicativa (Wolfert et al., 2017 y revisiones posteriores).
* **Salida:** tabla de huecos y declaración de novedad matizada (si algo ya existe, se reposiciona la contribución: la revisión **puede cambiar el enfoque**, y eso es lo esperado).

## 4. Ciencia abierta y reproducibilidad

* **Preregistro** congelado antes de tocar la partición de prueba (`PREREGISTRATION.md`).
* **Artefactos:** código del módulo (licencia permisiva), banco GCTSB con **datasheet** (Gebru et al., «Datasheets for Datasets»), tarjetas de modelo/uso del pipeline, *prompts* y esquemas, scripts de evaluación, manifiestos con hashes, semillas. Archivado con DOI (por ejemplo en Zenodo; verificar política de la revista).
* **Lo que no se puede publicar:** los pesos de TimesFM 3 (licencia no comercial, no redistribuible: se cita el origen) y el TFG (se queda local). Los LLM abiertos se citan por versión y licencia.
* **Lista de verificación de reproducibilidad** (al estilo de las de NeurIPS/ICML): presupuesto de cómputo (la DGX Spark), variación entre semillas e intervalos, versiones de software, partición, hiperparámetros fijados en desarrollo, código y datos disponibles.
* **Ética (D17):** no se requiere comité para el estudio con expertos; se mantienen consentimiento informado, anonimización y ausencia de datos personales, y se declara en el artículo que no hubo evaluación por comité (verificar la política de la revista elegida).

## 5. Validez externa: más allá del invernadero

El mayor reproche previsible a un trabajo de IA explicativa aplicada es «un solo caso, simulado». Mitigaciones, de menor a mayor esfuerzo:
1. Varios cultivos, entornos, temporadas (cientos) y niveles de ruido (ya en el diseño).
2. **Segundo dominio** con causalidad conocida, integrado por el mismo módulo (decisión abierta de `XAI_MODULE_ARCHITECTURE.md`). Es la evidencia más fuerte de que el método no es específico del invernadero.
3. Un **conjunto sintético de estructuras causales** (con retardos, regímenes y saturaciones) para aislar las propiedades de los métodos de atribución, complementario al banco del gemelo.
4. Una **prueba de concepto con datos reales** cuando existan (experimentos de escalón); no es condición del primer artículo, se declara como trabajo futuro.

## 6. Estructura prevista del artículo

1. Introducción: la brecha (explicar series temporales con fidelidad y calibración), preguntas, contribuciones C1-C4.
2. Trabajo relacionado (resultado de la revisión sistemática).
3. Marco: cuatro niveles de explicación, dos fidelidades, niveles de evidencia, propiedades Co-12.
4. Banco de pruebas GCTSB (diseño, verdad interventiva, errores de sensor, particiones, datasheet).
5. Método: análisis determinista, previsión, atribución, capa semántica con evidencia calibrada, verificador.
6. Experimentos: RQ1-RQ7, líneas base, ablación, estadística.
7. Resultados (incluidos los negativos), análisis por régimen y por ruido.
8. Estudio con expertos.
9. Discusión, amenazas a la validez, límites.
10. Conclusiones y trabajo futuro (datos reales, el gemelo como segundo artículo).
**Figuras y tablas clave:** arquitectura por capas y puertos; ejemplo de un escenario con sus cuatro verdades; fidelidad de atribución por factor y régimen; ablación A0-A4; mapa Co-12; resultados del estudio humano.

## 7. Riesgos de rechazo y respuesta

| Reproche probable | Respuesta preparada |
|---|---|
| «Solo datos simulados» | Es una elección para tener verdad causal; se compensa con ruido realista, varios dominios y un plan de datos reales; límites declarados |
| «La verdad es del modelo, no del mundo» | Se afirma solo «fidelidad al sistema simulado» |
| «Modelos de lenguaje pequeños (7-8B)» | Se evalúan tres y se reporta la dependencia del modelo; el verificador determinista limita el daño; posibilidad de añadir un modelo mayor de mezcla de expertos |
| «¿Por qué no usar otro LLM como juez?» | Se usa un verificador determinista con reglas explícitas, más evaluación humana; opcionalmente un LLM-juez como análisis secundario |
| «El pipeline es ingeniería» | Las contribuciones C1-C3 son de evaluación y de hallazgo; el pipeline es el objeto de estudio |
| «Poca novedad frente a Time-LLM, etc.» | La revisión sistemática establece el hueco: evidencia calibrada, verificación y verdad interventiva |
| «Resultados negativos de TimesFM» | Son la contribución C2: se presentan con su mecanismo (umbral no excitado), su estratificación y su contraste en un segundo dominio |
| «Circularidad: el gemelo es la verdad y la evidencia» | Doble gemelo (D15): el explicador usa un gemelo de trabajo perturbado y estructuralmente distinto (simplificado frente a EnergyPlus); el desajuste 0 solo es techo de referencia |
| «Si tenéis el gemelo, ¿para qué el previsor?» | Porque en instalaciones sin simulador solo hay datos: el banco mide cuándo un explicador basado en datos es fiable y cuándo hace falta un modelo |
| «Reproducibilidad con pesos no libres» | Código, datos y manifiestos abiertos; pesos citados por origen y hash; alternativa con Chronos-2 (Apache-2.0) |

## 8. Relación con el TFG y con el segundo artículo

* **El TFG es trabajo previo del mismo autor:** se cita y se declara qué se reutiliza (la idea de enriquecimiento semántico con STL, PELT y Holt-Winters) y qué es nuevo (verdad interventiva, evidencia calibrada, verificador con niveles, atribución validada, ablación, modularidad). Conviene confirmar la política de la universidad y de la revista sobre el uso de contenido de un TFG.
* **Segundo artículo (el gemelo):** contenido distinto (modelo físico, acoplamiento, EnergyPlus síncrono, recursos y KPIs de temporada). El artículo XAI usa el gemelo como banco de pruebas y lo cita como trabajo en preparación o preprint; **no se duplican contribuciones** (evitar la fragmentación artificial). Se coordina el orden: idealmente un preprint del gemelo disponible cuando se envíe el artículo XAI.

## 9. Revistas: criterio y acuerdos de la universidad (la elección se hace con resultados)

**Decisión (2026-10-24):** no se elige revista hasta tener resultados. Criterios del autor: **indexada en JCR**, **poca complejidad de publicación** y **acuerdos de la UCAM** con tres editoriales: **ScienceDirect (Elsevier)**, **American Chemical Society (ACS)** y **Cambridge University Press (CUP)**. El detalle de cada acuerdo (publicación abierta incluida o con descuento, cupos) lo confirma la biblioteca; no lo doy por sabido.

El segundo dominio (industria química con PLC) abre revistas de ingeniería química, además de las de IA aplicada. Candidatas a evaluar (pertenencia a JCR, cuartil y alcance **por verificar** en JCR/SCImago; los agregadores se contradicen):

| Editorial | Revista | Encaje | Reserva |
|---|---|---|---|
| Elsevier | *Information Fusion* | XAI y fusión de evidencia; banco con verdad causal | Muy selectiva |
| Elsevier | *Expert Systems with Applications* | IA aplicada con evaluación | Revisión desigual |
| Elsevier | *Engineering Applications of AI* | IA en ingeniería, dos dominios | Pide aplicación clara |
| Elsevier | *Computers & Chemical Engineering* | Series de procesos y PLC; valida el segundo dominio | Menos peso de XAI general |
| Elsevier | *Computers and Electronics in Agriculture* | Público agrícola | Mejor para el segundo artículo (el gemelo) |
| ACS | *Industrial & Engineering Chemistry Research* | Control y monitorización de procesos químicos | Espera un caso industrial más sólido que un reactor didáctico |
| CUP | *Data-Centric Engineering* | Datos, ingeniería e IA, acceso abierto | Comprobar si está en JCR |

Lectura provisional: Elsevier concentra el mejor encaje (*Information Fusion*, *ESWA*, *EAAI*). ACS exigiría reforzar el dominio químico con un caso realista; CUP tiene pocas revistas de este alcance. Se decide con la revisión sistemática y los resultados de RQ1–RQ3.

## 10. Plan y hitos

| Hito | Contenido | Fase |
|---|---|---|
| M0 | Decisiones de módulo y publicación; revisión sistemática; preregistro borrador | 6.0, 6.0b |
| M1 | Paquete independiente con puertos, simulador de juguete y pruebas de contrato | 6.0 (rehecha) |
| M2 | Banco GCTSB sobre `SimulatorPort` (gemelo + juguete) con datasheet | 6.1b |
| M3 | Analizador y evaluación RQ1 | 6.2 |
| M4 | Puerta de viabilidad de TimesFM y comparadores (RQ2, RQ4): **hecha en desarrollo, negativa** (6.3-6.3d); mecanismo en el reactor (6.3e) | 6.3a-6.3e |
| M5 | Doble gemelo (RQ4b) y fidelidad de la atribución (RQ3) | 6.5r |
| M6 | Capa semántica con niveles de evidencia, LLM, verificador y evaluación lingüística (RQ5), ablación A0-A4 con A3a/A3b (RQ6); RAG solo en el producto (D16) | 6.4, 6.6, 6.7, 6.8 |
| M7 | Estudio con expertos (RQ7) | 6.9 |
| M8 | Congelado, ejecución única sobre prueba, redacción, artefactos archivados | cierre |

## 11. Decisiones

1. **Autores y filiación:** por ahora Francisco Arcas-Túnez (farcas@ucam.edu, UCAM); el reparto de autoría se decide más adelante. El TFG lo dirigió el autor y la universidad es su centro de trabajo: no hace falta permiso para usarlo; el PDF sigue fuera de git por indicación expresa.
2. **Preprint:** por ahora no.
3. **Segundo dominio:** sí, industria química con PLC (`tsxai.examples.PlcReactor`).
4. **Revista objetivo:** se decide con resultados; criterio y acuerdos en §9.
5. **Alcance (D14-D16, 2026-10-25):** L3 por el gemelo, doble gemelo con EnergyPlus para la energía, RAG fuera del artículo y dentro del producto.
6. **Ética (D17):** el estudio con expertos no necesita comité de ética.
5. **Revisión de la revisión sistemática por una segunda persona:** pendiente.
