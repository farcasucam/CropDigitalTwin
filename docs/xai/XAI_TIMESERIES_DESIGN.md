# XAI de series temporales del invernadero: análisis y diseño por fases

Documento de entrada para un agente que diseñe e implemente el proyecto **«análisis multivariante con TimesFM 3.0 + explicabilidad + explicación en lenguaje natural con un LLM»** sobre este repositorio (Gemelo Digital Agrícola).
Estado: **PROPUESTA** (nada implementado). Fecha de redacción: 2026-10-23. Los hechos externos están verificados contra las fuentes citadas y marcados *(verificar)* cuando dependen de versiones que cambian.

---

> **Estructura del código y publicación (2026-10-24):** el módulo XAI es un **paquete independiente y reutilizable** (`docs/xai/XAI_MODULE_ARCHITECTURE.md`): donde este documento dice `agri_twin/domain|application|infrastructure/xai`, léase el paquete `tsxai` y un adaptador del gemelo. La parte XAI alimenta un artículo Q1 (`docs/xai/PUBLICATION_STRATEGY.md`), que añade la **fase 6.0b (revisión sistemática del estado del arte)** antes de seguir implementando, y hace que la 6.1b se construya sobre un `SimulatorPort` genérico.

> **Diseño científico:** las preguntas de investigación, hipótesis, banco de pruebas (GCTSB), métricas, análisis estadístico y amenazas a la validez están en `docs/xai/XAI_SCIENTIFIC_DESIGN.md`, que **prevalece** sobre este documento en todo lo que afecte a la evaluación. Este documento fija la arquitectura y las fases de ingeniería; el TFG (`docs/xai/TFG.pdf`) es el punto de partida de la fase numérica (STL, PELT, Holt-Winters, enriquecimiento semántico, verificador).

## 0. Cómo leer este documento (reglas para el agente)

1. **Respeta `CLAUDE.md` y `docs/architecture/`**: arquitectura por capas (dominio puro → aplicación → infraestructura → interfaces), cadena causal `evento/dato → modelo físico → estado → cultivo → evaluación/control → comando → actuador → modelo físico`, informes deterministas con hash, nada de valores agronómicos inventados.
2. **La capa XAI es de solo lectura.** Analiza series ya producidas por el gemelo; **nunca escribe estado** (temperatura, humedad, VWC…), nunca emite comandos a actuadores y nunca sustituye al motor físico. Una recomendación del LLM es texto con evidencia, no una orden.
3. **Patrón de entrega de cada fase** (el del repo): módulo en `src/agri_twin/...` + exportaciones + `tests/test_<feature>.py` + `manual_phase6_<N>_<feature>_test.py` (offline, aserciones, JSON determinista en `data/xai/`) + `docs/phase6_<N>_<feature>.md` + fila en `docs/architecture/PHASES.md`. Un commit por fase, con la suite completa en verde (`python -m pytest`, ~22 min) antes de commitear.
4. **Honestidad científica obligatoria.** No existe ningún dato `REAL_VERIFIED`. Toda salida debe llevar la clasificación del dato (`SYNTHETIC`, `FORCING`, `SIMULATED_REAL_DATA_SUBSTITUTE`) y la frase de estado: *«explicación de un modelo sobre series simuladas; no es validación experimental ni causalidad demostrada»*. Nunca afirmar calibración, validación ni asimilación de datos.
5. **Umbrales agronómicos**: solo desde `src/crop_config.json` (por cultivo y fase); equipos: solo los definidos por el usuario; convenciones de diseño nuevas, en JSON propio marcado *provisional*. Si falta un umbral, la regla que lo necesita **no actúa** y el informe lo dice.
6. **Sin red durante las pruebas.** Los servicios (TimesFM, LLM, embeddings) se simulan con *dobles deterministas* (record/replay). Los contenedores reales solo se usan en los *manual scripts* y en una suite opcional marcada `@pytest.mark.requires_services`.
7. Las decisiones abiertas están en la sección 12: **pregúntalas antes de la fase 3**, no las decidas.

---

## 1. Qué se pide, traducido al repositorio

El texto pegado describe un TFG de otro sistema (sensores de suelo, Sentinel-2/NDVI, RAG de manuales). Esta tabla fija **qué se reutiliza, qué se adapta y qué no existe aquí**.

| Concepto del texto | En este repositorio | Decisión |
|---|---|---|
| `SemanticEnricher` / `SemanticFormatter` (serie → narrativa Markdown) | No existe | **Nuevo** (fase 6.4). Los hechos salen de series del gemelo y del catálogo de cultivos |
| `TimeSeriesAnalyzer` (STL, PELT, Holt-Winters) | No existe | **Nuevo** (fase 6.2), dominio puro y determinista |
| Previsión | No existe (el gemelo simula, no predice con IA) | **Nuevo**: TimesFM 3.0 como servicio (fase 6.3) |
| Explicabilidad del modelo | No existe | **Nuevo** (fase 6.5): atribución sobre TimesFM **validada contra contrafácticos del gemelo** |
| Chain-of-Thought + validación cruzada suelo↔NDVI | No hay sensores ni Sentinel-2 | **Adaptar**: contraste entre variables del gemelo (p. ej. VWC ↔ transpiración ↔ LAI) tras una interfaz `ObservationSource` preparada para Sentinel-2 cuando existan datos reales |
| Glass Box UI | `frontend/bench.*` (banco de experimentos) | **Extender** el bench con un panel «Explicación» (fase 6.8) |
| `rag_audit` | No existe RAG | **Nuevo** (fase 6.6), corpus = `docs/` del proyecto + catálogo de cultivos; sin manuales inventados |
| `ConsistencyChecker` / `ConsistencyCorrection` | No existe | **Nuevo** (fase 6.7), reglas desde `crop_config.json` y desde las invariantes del gemelo |

**Ventaja diferencial de este proyecto (el núcleo científico):** el gemelo es un **oráculo causal**. Sabemos qué evento o actuador provocó cada cambio (`runtime_events`, `what-if`, backends consistentes). Así la explicabilidad no se queda en «el modelo dice que X importa»: se **mide si la atribución coincide con el efecto causal real** que el gemelo reproduce al aplicar el contrafáctico. Eso convierte la XAI en algo verificable y es lo que hace defendible el trabajo.

---

## 2. Hechos externos verificados

### 2.1 TimesFM 3.0 (Google Research, agosto de 2026)
Fuentes: [README oficial](https://github.com/google-research/timesfm), [MarkTechPost](https://www.marktechpost.com/2026/08/31/google-ai-releases-timesfm-3-a-330m-parameter-zero-shot-foundation-model-for-multivariate-time-series-forecasting/), [datanorth](https://datanorth.ai/news/google-releases-timesfm-3).

* Checkpoint `google/timesfm-3.0-pytorch`; **330 M parámetros**; decoder-only; contexto de ~16 k (el README indica truncado a las últimas **15 360** muestras).
* **Multivariante nativo**: varios objetivos, **covariables solo pasadas** (`past_only_covariates`) y **pasadas+futuras** (`past_future_covariates`), sin ajuste por tarea. Es la diferencia clave con 2.5 (univariante).
* Salida: previsión puntual (mediana) + **9 cuantiles** (0,1…0,9).
* Backends: PyTorch (CUDA) y MLX (Apple). Instalación: `pip install timesfm[torch]`.
* API según el README *(verificar contra la versión instalada; aislar tras un adaptador)*:
  ```python
  from timesfm3 import TimesFM3Evaluator, ModelConfig
  forecaster = TimesFM3Evaluator(ModelConfig(checkpoint_path="google/timesfm-3.0-pytorch", per_core_batch_size=32, device="cuda"))
  outputs = list(forecaster.predict_batch(contexts=[target], horizon=H, past_only_covariates=[...], past_future_covariates=[...], return_quantiles=True, use_symmetric_averaging=False))
  ```
* **LICENCIA (restricción dura):** código Apache-2.0, pero los **pesos 3.0** están bajo `timesfm-non-commercial-license-v1.0`: *«restricted to non-commercial, non-production use»*; el uso comercial/producción se permite solo a través de servicios autorizados de Google Cloud (BigQuery ML). Las fuentes secundarias son contradictorias en matices → **leer el texto de la licencia antes de desplegar** (decisión D1).

### 2.2 NVIDIA DGX Spark
Fuentes: guías de la comunidad y foros NVIDIA ([technotim](https://technotim.com/posts/vllm-gb10-docker/), [collabnix](https://collabnix.com/running-vllm-on-nvidia-dgx-spark-with-docker-zero-compilation-guide-for-cuda-13/), [foro NVIDIA](https://forums.developer.nvidia.com/t/dgx-spark-13-49-tok-s-with-qwen3-5-35b-native-sm121-kernel-build-guide/365083)).

* Chip **GB10 Grace Blackwell**: CPU **aarch64**, GPU **SM121**, **128 GB de memoria unificada** (compartida CPU/GPU), CUDA 13. Consecuencias: **todas las imágenes deben ser `linux/arm64` con soporte CUDA 13/SM121**; usar contenedores NGC como base por defecto; no hay VRAM dedicada (el presupuesto de memoria es único).
* NVIDIA publica imágenes NGC de vLLM (`nvcr.io/nvidia/vllm`); suelen ir por detrás de upstream y **el mismo tag puede cambiar de contenido** → fijar por *digest*. Hay problemas conocidos de `torch` pip sin soporte CUDA 13 y de kernels SM121 ausentes en imágenes genéricas *(verificar el estado actual antes de elegir imagen)*.
* El ancho de banda de memoria es el límite del *decoding* de LLMs grandes: dimensionar el LLM por latencia aceptable, no solo por «cabe».

---

## 3. Arquitectura objetivo

```
                    ┌────────────── DGX Spark (docker compose, red interna, solo loopback) ──────────────┐
 gemelo (este repo) │  timesfm-svc     llm-svc (vLLM, API OpenAI)     embed-svc (RAG)      vector-store     │
 API frontend ──────┼─►  :8101            :8102                         :8103               (fichero/SQLite) │
        ▲           └──────────▲───────────────▲──────────────────────────▲───────────────────────────────┘
        │                      │ HTTP/JSON     │ HTTP/JSON                 │
 ┌──────┴──────────────────────┴───────────────┴──────────────────────────┴─────────┐
 │ interfaces/xai_api.py   (rutas /api/xai/*, estado de servicios, Glass Box payload)│
 │ application/xai/        orquestación del pipeline (determinista salvo el LLM)     │
 │ infrastructure/xai/     clientes HTTP (TimesFM, LLM, embeddings), caché, grabadora│
 │ domain/xai/             TimeSeriesAnalyzer (STL/PELT/HW), SemanticEnricher,       │
 │                         SemanticFormatter, atribución, ConsistencyChecker (puros) │
 └───────────────────────────────────────────────────────────────────────────────────┘
```

Reglas de dependencia: `domain/xai` **no** importa HTTP, LLM, TimesFM ni `application`; los servicios entran por *puertos* (`ForecastBackend`, `LanguageModel`, `Retriever`) definidos en dominio/aplicación, con adaptadores en infraestructura y dobles de prueba.

**Flujo (un «caso de explicación»):**
1. *Selección*: ventana temporal + variables + (opcional) intervención del gemelo.
2. *Dataset*: `MultivariateFrame` desde la API del gemelo (nunca de ficheros ad hoc).
3. *Análisis determinista*: STL, PELT, Holt-Winters → `AnalyticsReport`.
4. *Previsión*: TimesFM 3.0 → `ForecastReport` (puntual + cuantiles).
5. *Atribución*: ablación/oclusión/contrafácticos → `AttributionReport` validado contra el gemelo.
6. *Enriquecimiento semántico*: hechos con ID, unidades y umbrales del catálogo → Markdown.
7. *RAG*: fragmentos del corpus del proyecto con `rag_audit`.
8. *LLM (CoT)*: salida **estructurada** (JSON) con afirmaciones que citan `fact_id`.
9. *Consistency Checker*: reglas duras; correcciones registradas; reintento acotado o rechazo.
10. *Glass Box*: razonamiento, evidencias, correcciones y auditoría visibles.

---

## 4. Contratos de datos (la base de todo)

Todos son `dataclass` inmutables con `to_dict()` canónico y `content_hash` (SHA-256 del JSON ordenado), como el resto del repo.

* **`MultivariateFrame`**: `time[]` (UTC, horario), `variables{name: {values[], unit, role, classification}}`, `source` (`simulation_id`, `request_hash`, `trajectory_hash`), `clock` (paso 3600 s).
  Roles de variable para TimesFM (decidir con una tabla en `src/xai_variable_roles.json`, **provisional**):
  | Rol | Qué entra | Ejemplos del gemelo |
  |---|---|---|
  | `target` | lo que se predice | `temperature_c`, `relative_humidity_pct`, `vpd_kpa`, `soil_water_vwc_m3_m3`, `co2_ppm` |
  | `past_future_covariate` | conocido en el futuro (forzamiento y plan de actuación) | `outdoor_temperature_c`, `radiation_w_m2` exterior, viento, plan de ventanas/toldo/riego/CO₂ programados |
  | `past_only_covariate` | solo conocido hasta ahora | estado interior no programado, `greenhouse_*_kw`, estrés del cultivo |
  | `context_only` | no entra en el modelo, sí en la narrativa | etapa fenológica, LAI, `control_layer` |
  Regla: lo que el gemelo calcula **después** del instante de decisión nunca puede ser covariable futura (anti-fuga; hay test).
* **`AnalyticsReport`**: por variable → `stl{trend, seasonal, residual, period, strength_trend, strength_seasonal}`, `changepoints[{index, time, kind: MEAN|VARIANCE, magnitude, penalty}]`, `holt_winters{fitted, forecast, params, sse}`, `segments[]` (tendencias por tramo con pendiente y unidad/hora).
* **`ForecastReport`**: `horizon`, `median[]`, `quantiles{0.1..0.9}[]`, `context_used`, `model{checkpoint, version, license_status}`, `backend_request_hash`.
* **`AttributionReport`**: ver fase 6.5 (importancias por covariable/ventana + métricas de fidelidad frente al gemelo).
* **`SemanticFact`**: `fact_id` (estable: hash del contenido), `statement` (texto), `variable`, `window`, `value`, `unit`, `kind` (`TREND|CHANGEPOINT|THRESHOLD_EXCEEDANCE|FORECAST|ATTRIBUTION|EVENT|STAGE|DATA_QUALITY`), `evidence_ref` (puntero al informe origen), `classification`.
* **`Explanation`** (salida del LLM, validada por esquema): `summary`, `reasoning_steps[{step, text, fact_ids[]}]`, `claims[{claim_id, text, fact_ids[], numeric_values[{value, unit, fact_id}], confidence}]`, `recommendations[{action, rationale_claim_ids[], blocked_by[]}]`, `caveats[]`.
* **`ConsistencyCorrection`**: `rule_id`, `severity`, `claim_id`, `original`, `corrected`, `reason`, `fact_ids`, `action` (`REWRITTEN|REMOVED|ANNOTATED|BLOCKED`).
* **`rag_audit`**: `query`, `retrieved[{doc_id, chunk_id, score, text_hash, used_in_claims[]}]`, `index_fingerprint`, `unused_chunks[]`.

JSON Schemas de estos objetos en `schemas/xai/` (el repo ya valida contratos con `agri_twin/contracts.py`).

---

## 5. Fases

Numeración **6.x** (la familia 5.x es el marco científico del gemelo). Orden obligatorio; cada fase es independiente de la siguiente en pruebas gracias a los dobles.

### Fase 6.0 — Decisiones y andamiaje *(0,5 jornada)*
**Objetivo:** dejar por escrito las decisiones y preparar el esqueleto sin lógica.
**Entregables**
* `docs/xai/DECISIONS_XAI.md` (ADR): D1 licencia, D2 LLM elegido, D3 idioma, D4 almacén de vectores, D5 política de determinismo del LLM (ver §9).
* Extra opcional `[xai]` en `pyproject.toml`: `statsmodels` (STL, Holt-Winters), `ruptures` (PELT), `httpx`, `jsonschema`, `numpy`; cada dependencia con versión fijada y licencia anotada. **No** añadir `torch`/`timesfm` al paquete: viven en el contenedor.
* Paquetes vacíos con `__init__.py` y puertos (`Protocol`) `ForecastBackend`, `LanguageModel`, `Retriever`.
* `src/xai_variable_roles.json` (provisional) y `schemas/xai/*.json`.
**Aceptación:** `python -m pytest` verde; la auditoría estática del proyecto (sin reloj de pared en `application/`, sin imports prohibidos en `domain/`) sigue en PASS; las importaciones de `xai` no arrastran red.

### Fase 6.1 — Constructor de datasets multivariantes *(1–2 jornadas)*
**Objetivo:** `MultivariateFrame` reproducible desde el gemelo, con roles y anti-fuga.
**Diseño**
* `application/xai/frames.py`: construye el frame desde `InteractiveSimulationService` (resultado de una simulación o `what-if`), no desde ficheros. Soporta: mismo run, rama baseline vs intervención, ventana arbitraria.
* Cubrir los tres entornos (campo abierto, invernadero agrupado, EnergyPlus con/sin control) y la opción de realimentación del cultivo.
* Etiqueta de clasificación por variable (forzamiento = `FORCING`; salidas del modelo = `SYNTHETIC`/`SIMULATED_…`).
* Control de calidad: huecos, constantes (p. ej. refrigeración siempre 0), valores centinela; se reportan como `DATA_QUALITY` facts, no se «arreglan».
**Pruebas:** determinismo del hash; anti-fuga (ninguna covariable futura contiene información posterior al instante de corte); el frame de una rama de `what-if` coincide con el de la ejecución continua en el prefijo.
**Aceptación:** `manual_phase6_1_frames_test.py` genera frames de 4 escenarios (tomate/pimiento, outdoor/greenhouse/EnergyPlus-control) con hashes estables.

### Fase 6.1b — Banco de pruebas GCTSB y preregistro *(3–4 jornadas; antes de 6.2)*
**Objetivo:** el generador de escenarios con verdad de terreno que hace evaluables todas las fases siguientes (detalle y justificación en `XAI_SCIENTIFIC_DESIGN.md` §5).
**Entregables:** `application/xai/benchmark.py` (hipercubo latino de eventos, perturbaciones **pareadas** del gemelo para la verdad interventiva, inyección de ruido y fallos de sensor **sobre la observación**, anotaciones de cambios, particiones por temporada y cultivo), `docs/xai/PREREGISTRATION.md` (hipótesis, métricas primarias, umbrales provisionales, plan estadístico) y `manual_phase6_1b_benchmark_test.py` con hashes estables.
**Pruebas:** determinismo; la perturbación pareada afecta solo a lo posterior al instante del evento; el ruido no altera el estado verdadero; sin fuga entre particiones; cada anotación coincide con el evento del gemelo.
**Aceptación:** ≥ 1000 escenarios reproducibles con las cuatro verdades (G1-G4) y una tabla de cobertura de factores.

### Fase 6.2 — `TimeSeriesAnalyzer` determinista (STL, PELT, Holt-Winters) *(2–3 jornadas)*
**Objetivo:** el «análisis algorítmico determinista» previo al LLM.
**Diseño**
* `domain/xai/timeseries_analyzer.py`, funciones puras sobre `numpy`:
  * **STL**: periodo diario = 24 (paso horario); robusto; devuelve fuerza de tendencia/estacionalidad (Wang, Smith, Hyndman: `1 − Var(R)/Var(T+R)` y análogo). Periodo **fenológico** no se estima con STL (series de semanas): se trata con tendencia por tramos.
  * **PELT** (`ruptures`): coste `rbf`/`l2` para media y `normal` para varianza; **la penalización no se inventa**: se fija por BIC `k·log(n)·σ²` y se reporta; se aplica sobre el **residuo STL** (no sobre la señal con ciclo circadiano, que daría falsos saltos). Distingue *evento discreto* (salto > umbral relativo al ruido y persistente) de *variación progresiva* (pendiente por tramo).
  * **Holt-Winters** aditivo/multiplicativo con estacionalidad 24; reportar parámetros ajustados y SSE; la proyección es una **línea base clásica** (no sustituye a TimesFM: sirve de comparación y de entrada narrativa).
* Detección de **eventos del gemelo**: cruzar los puntos de ruptura con `runtime_events` y con cambios de actuador (`control_*`) para etiquetar *causa conocida* vs *sin causa conocida*.
* Casos límite documentados: series constantes, huecos, longitud < 2 periodos (no se ejecuta STL: se informa).
**Pruebas (con verdad de terreno):** serie sintética con ciclo + salto + rampa plantados → PELT recupera el salto ±2 muestras; STL recupera el ciclo; ola de calor del gemelo → ruptura en el inicio del evento (±1 h); determinismo de hash.
**Aceptación:** `manual_phase6_2_analyzer_test.py` sobre las pruebas de intervención existentes (`tests/test_intervention_effects.py` como escenarios): el analizador marca las ventanas de evento con precisión/recobrado ≥ umbral documentado.

### Fase 6.3 — Servicio TimesFM 3.0 en la DGX Spark *(3–4 jornadas)*
**Objetivo:** previsión multivariante por API, reproducible y con licencia gestionada.
**Contenedor `timesfm-svc`**
* Base NGC PyTorch **arm64/CUDA 13**, imagen fijada por *digest*; instala `timesfm[torch]` (versión fijada); pesos descargados una vez a un volumen (`/models`), arranque posterior **sin red**.
* API (FastAPI, solo loopback o red interna del compose):
  * `GET /health` (modelo cargado, dispositivo, versión de librería, **estado de licencia**).
  * `POST /v1/forecast` → entrada: lista de series con `targets`, `past_only_covariates`, `past_future_covariates`, `horizon`, `quantiles=true`; salida: mediana + 9 cuantiles + metadatos. Límites explícitos (contexto 15 360, horizonte máximo configurable).
  * Determinismo: sin muestreo (TimesFM produce la misma salida para la misma entrada); registrar `request_hash`/`response_hash`.
* **Puerta de licencia (D1):** el servicio **no arranca** sin `TIMESFM_LICENSE_ACK=non-commercial-research` y expone la licencia en `/health`; el informe de cada previsión incluye `license_status`. Si D1 resulta ser «uso comercial», el adaptador cambia a una alternativa (§11) sin tocar el resto.
**Adaptador** `infrastructure/xai/timesfm_client.py` implementa `ForecastBackend`; **doble de prueba** `RecordedForecastBackend` (JSON grabado, mismo contrato) y un `SeasonalNaiveBackend`/`HoltWintersBackend` determinista para pruebas sin servicio.
**Evaluación honesta (sin dato real):** *backtesting* sobre series del gemelo con orígenes rodantes: MASE/sMAPE y **cobertura empírica de cuantiles** frente a Holt-Winters y naive estacional; casos con y sin covariables; casos con evento (ola de frío) para ver si las covariables futuras (forzamiento conocido) mejoran. Resultado = informe, **no** afirmación de calidad general.
**Pruebas:** contrato del cliente con el doble; errores (timeout, 5xx, respuesta malformada) → excepciones tipificadas; límites de entrada; hash estable.
**Aceptación:** `manual_phase6_3_forecast_test.py` (con servicio real si está disponible; si no, con el doble y lo declara).

### Fase 6.3a — Puerta de viabilidad de TimesFM 3 *(incluida en 6.3; 2 jornadas)*
Antes de construir la atribución: ejecutar RQ2 y la parte contrafáctica de RQ4 sobre el banco GCTSB frente a naive estacional, Holt-Winters, regresión con retardos, boosting, un modelo entrenado en el dominio y Chronos-2, con orígenes rodantes, intervalos por bloques y cobertura de cuantiles. **Regla de decisión (preregistrada):** si el uso de covariables no concuerda con el gemelo en los factores principales, la explicación L2/L3 se construye sobre un modelo agnóstico y TimesFM queda como comparador; el resultado negativo se publica.

### Fase 6.4 — Capa semántica: `SemanticEnricher` y `SemanticFormatter` *(3 jornadas)*
**Objetivo:** convertir números en hechos verificables y en Markdown que un LLM pueda razonar sin «ceguera matemática».
**Diseño**
* `SemanticEnricher` (dominio puro): entrada = `AnalyticsReport` + `ForecastReport` + `AttributionReport` + estado fenológico + umbrales; salida = lista de `SemanticFact` con `fact_id` estable.
  * Tendencias a lenguaje con **vocabulario cerrado** y umbrales relativos al ruido (p. ej. «descenso acelerado» = pendiente de tramo < −k·σ_residual/h y curvatura negativa; el `k` es una convención de diseño en `src/xai_semantics.json`, *provisional*, documentada).
  * Umbrales de cultivo **solo** de `crop_config.json` por etapa (`optimal_min/max`, `critical_*`): hechos del tipo «T interior superó 28,0 °C (max_temp de la etapa X) durante 6 h»; si falta, el hecho es `THRESHOLD_UNDEFINED` y se declara.
  * Eventos del gemelo y actuadores como hechos `EVENT`.
  * Previsión: cuantiles → incertidumbre explícita («80 % de probabilidad de que T esté entre a y b»; **solo** si la cobertura empírica de 6.3 lo respalda, si no se dice «intervalo nominal del modelo, no calibrado»).
* `SemanticFormatter`: Markdown con secciones fijas (Contexto · Estado actual · Cambios detectados · Previsión · Atribución · Calidad del dato), cada línea con `[F:<fact_id>]`; formato estable (golden files).
* **Regla de oro:** el LLM **no recibe arrays numéricos crudos**; recibe hechos con ID y, si necesita un valor, el valor ya formateado con unidad.
**Pruebas:** golden Markdown por escenario; cada número del Markdown es trazable a un `SemanticFact`; ningún texto sin `fact_id`; idempotencia.
**Aceptación:** `manual_phase6_4_semantics_test.py` imprime el Markdown de los 4 escenarios y comprueba trazabilidad 100 %.

### Fase 6.5 — Explicabilidad del modelo con validación causal contra el gemelo *(4–5 jornadas; la fase científica)*
**Objetivo:** atribuciones de la previsión **y** medida de su fidelidad frente a la causalidad conocida.
**Métodos (todos *model-agnostic*, sobre la caja negra TimesFM vía `ForecastBackend`):**
1. **Importancia por covariable (ablación/permutación):** repetir la previsión sustituyendo una covariable por (a) su media de contexto, (b) una permutación por bloques (preserva autocorrelación). Métrica: cambio del error y del valor previsto. Determinista (semillas fijas, bloques de 24 h).
2. **Saliencia temporal (oclusión de ventanas):** ocluir ventanas deslizantes del contexto y medir la variación de la previsión → «qué horas del pasado pesan».
3. **Contrafácticos de covariable futura:** editar una covariable futura *conocida* (p. ej. +2 renovaciones/h de ventilación, −40 % radiación) y obtener Δprevisión de TimesFM.
4. **Contrafáctico causal del gemelo (verdad de terreno):** la misma edición se ejecuta en el **gemelo** (`what-if` con el evento equivalente) → Δ real.
5. **Atribución de residuos (diagnóstico):** previsión de TimesFM con covariables «normales» frente a lo observado en el gemelo con evento → qué covariable/evento explica la desviación.
**Métricas de fidelidad (resultado central):** concordancia de **signo** y de **orden** (Spearman) entre Δ de TimesFM y Δ del gemelo por intervención; error relativo de magnitud; fracción de intervenciones donde el ranking de covariables coincide. Se publican **por variable objetivo** y se reportan también los fallos (p. ej. ventilación ↔ HR).
**Honestidad:** la atribución explica **al modelo**, no a la fisiología del invernadero; una covariable «importante» puede serlo por correlación. Por eso la fidelidad frente al gemelo es obligatoria y el informe la incluye siempre; si la fidelidad de una variable es baja, el Enricher **degrada** el lenguaje («asociación del modelo, no confirmada por el gemelo»).
**Pruebas:** casos sintéticos donde la importancia verdadera es conocida (serie generada por una ecuación con covariable controlada); determinismo; no mutación de entradas (patrón del repo: evaluación no muta `ParameterSet`/`TwinState`).
**Aceptación:** `manual_phase6_5_attribution_test.py` produce `data/xai/attribution_fidelity.json` con las métricas sobre el catálogo de intervenciones de `tests/test_intervention_effects.py` (calor, frío, radiación, ventilación, sombreado, CO₂, riego).

### Fase 6.6 — Servicio LLM en la DGX Spark + RAG con `rag_audit` *(3–4 jornadas)*
**Contenedor `llm-svc` (vLLM, API compatible OpenAI)**
* Imagen NGC vLLM **arm64/CUDA 13** fijada por digest; modelo configurable (D2); `--max-model-len` y `--gpu-memory-utilization` dimensionados al presupuesto de 128 GB unificados **menos** TimesFM, embeddings y el sistema.
* **Salida estructurada** (JSON Schema / `guided_json`) para `Explanation`; temperatura 0, `seed` fijo; el servicio devuelve `model`, `system_fingerprint` y *token counts*.
* Cliente `infrastructure/xai/llm_client.py` (`LanguageModel`) con reintentos acotados, *timeouts* y grabadora **record/replay** (hash del prompt → respuesta) para pruebas deterministas.
**RAG** (`embed-svc` + almacén local)
* Corpus **solo del proyecto**: `docs/` (arquitectura, límites científicos, informe de parámetros), `src/crop_config.json` (fichas por etapa), documentos que el usuario añada explícitamente. **No se descargan manuales externos.**
* Fragmentación por cabeceras Markdown con IDs estables; metadatos `[DOC: doc_id | CHUNK: chunk_id | score=0.85]` inyectados en el prompt; `rag_audit` devuelve qué fragmentos se recuperaron, cuáles se citaron en qué afirmaciones y cuáles no se usaron. `index_fingerprint` = hash del corpus.
* Recuperación determinista (empates por `chunk_id`); k configurable; umbral mínimo de similitud (si nada lo supera, **no se inyecta contexto** y se dice).
**Pruebas:** troceado estable; `rag_audit` completo (todo fragmento citado existe; ningún fragmento citado sin pasar el umbral); cliente con respuesta grabada; límites de contexto (poda determinista de hechos por prioridad).
**Aceptación:** `manual_phase6_6_llm_rag_test.py` (servicio real si hay; si no, doble y lo declara).

### Fase 6.7 — `ConsistencyChecker` y `ConsistencyCorrection` *(3 jornadas)*
**Objetivo:** que ninguna afirmación del LLM salga sin pasar reglas duras; transparencia de cada corrección.
**Reglas (cada una con `rule_id`, severidad y prueba):**
| Familia | Regla |
|---|---|
| Trazabilidad | toda afirmación cita ≥1 `fact_id` existente; todo número del texto coincide con el del hecho (tolerancia por unidad); sin cifras huérfanas |
| Unidades/rangos | valores dentro de rangos físicos plausibles (HR 0–100 %, VWC 0–1…); unidades coherentes con el hecho |
| Umbrales agronómicos | cualquier umbral citado = el de `crop_config.json` para la etapa; umbral inexistente → afirmación `BLOCKED` («no definido en el catálogo»), nunca inventado |
| Causalidad | no se afirma «A causa B» si el hecho solo es `ATTRIBUTION` con fidelidad baja o sin contraste en el gemelo → se reescribe como asociación |
| Dirección/magnitud | el signo de cada cambio afirmado coincide con el hecho (`TREND`, `EVENT`) |
| Recomendaciones | solo sobre actuadores **disponibles y con equipo definido** por el usuario; ninguna orden de escritura de estado; respeta la cadena causal; el texto es sugerencia con justificación |
| Estado científico | prohibido afirmar calibración, validación experimental, `REAL_VERIFIED` o asimilación de datos; frase de estado obligatoria |
| Incertidumbre | previsión sin cobertura empírica respaldada → debe llevar la salvedad |
| Datos | si hay `DATA_QUALITY` (serie constante, huecos), no se explican «variaciones» inexistentes |
**Comportamiento:** el checker devuelve `Explanation` corregida + lista de `ConsistencyCorrection`; si hay violaciones graves se hace **un reintento** al LLM con las correcciones como instrucciones; si persisten, el resultado se publica **con las afirmaciones bloqueadas retiradas** y el motivo visible (*fail-closed*). Todo queda en el informe.
**Pruebas:** batería de salidas del LLM **adversarias** (grabadas): umbral inventado, número alterado, causalidad sin base, recomendación sobre equipo no definido, afirmación de validación → cada una detectada y corregida con la `ConsistencyCorrection` esperada; idempotencia (pasar el checker dos veces no cambia nada).
**Aceptación:** `manual_phase6_7_consistency_test.py` con tasa de detección 100 % en la batería adversaria y 0 falsos positivos en las salidas válidas.

### Fase 6.8 — Pipeline orquestado, API y Glass Box UI *(4–5 jornadas)*
**Orquestador** `application/xai/pipeline.py`: ejecuta los pasos 1–10 de §3; cada paso produce su informe hasheado; el `ExplanationBundle` final = {frame, analytics, forecast, attribution, facts, markdown, rag_audit, explanation, corrections, hashes, estado científico}. **Determinista salvo el texto del LLM**; el hash del bundle excluye el texto libre pero incluye `prompt_hash` y `response_hash`.
**API** (`interfaces/xai_api.py`, mismo servidor del frontend): `POST /api/xai/explain`, `GET /api/xai/status` (estado de los 3 servicios, licencia, versiones), `GET /api/xai/bundle/<id>`. Degradación elegante: sin LLM → se devuelve hechos + Markdown + análisis (útil por sí solo); sin TimesFM → análisis determinista y Holt-Winters rotulado como tal.
**Glass Box UI** (extender `frontend/bench.*`, sin saltos de layout, patrón del bench):
* Panel «Explicación» bajo los gráficos: **Razonamiento del agente** (pasos CoT), **Afirmaciones** con chips de evidencia (`F:…`) que **resaltan en los gráficos** la ventana del hecho, **Contrafácticos** (chips con Δ de TimesFM frente a Δ del gemelo y fidelidad), **Correcciones del verificador** (qué se reescribió/retiró y por qué), pestaña **Auditoría** (`rag_audit`, hashes, versiones de modelo, licencia).
* Estados claros: servicios caídos, ejecución en curso (progreso por paso), resultado desactualizado (misma lógica roja del botón Run).
* La explicación se invalida si cambia la simulación (firma canónica de la petición, ya existente).
**Pruebas:** contratos de la API con dobles; pruebas estáticas del frontend (patrón de `tests/test_bench.py`); snapshot de `ExplanationBundle` con LLM grabado; auditoría estática (sin `new Date(` ni reloj de pared).
**Aceptación:** `manual_phase6_8_pipeline_test.py` ejecuta el caso de punta a punta con dobles y, si hay servicios, con los reales.

### Fase 6.9 — Evaluación, informe científico y operación *(3–4 jornadas)*
**Evaluación (todas sobre series del gemelo; ninguna sobre datos reales):**
| Métrica | Cómo | Criterio de aprobación (a fijar en D5) |
|---|---|---|
| Fidelidad causal de la atribución | fase 6.5 | por variable, informada; umbral mínimo para usar lenguaje causal |
| Calidad de previsión | MASE/sMAPE vs Holt-Winters y naive; cobertura de cuantiles | informada, sin afirmación general |
| Fundamentación (faithfulness) | % de afirmaciones con evidencia correcta tras el checker | ≥ umbral; 100 % tras *fail-closed* |
| Robustez a premisas falsas | prompts con datos manipulados (p. ej. serie constante «con variación») | 0 afirmaciones sin base en la salida final |
| Estabilidad | repetir N veces con `temperature=0` y seed | variación del texto medida; los hechos y el verificador deben ser idénticos |
| Latencia/recursos | p50/p95 por paso en la Spark; memoria | informe |
**Operación:** `docker-compose.xai.yml` con perfiles (`timesfm`, `llm`, `embed`), healthchecks, volúmenes de modelos, `restart: unless-stopped`, redes internas, **sin puertos públicos**; `docs/xai/RUNBOOK_DGX_SPARK.md` (arranque, actualización por digest, descarga de pesos, licencias, diagnóstico de `SM121`/CUDA 13, límites de memoria unificada); modo **offline** completo tras la primera descarga.
**Entregable científico:** `docs/phase6_9_xai_report.md`: resultados, **límites** (explicación del modelo ≠ causalidad fisiológica; solo datos simulados; licencia; sensibilidad al LLM) y tabla de qué se afirma y qué no.

---

## 6. Qué pasa con Sentinel-2/NDVI y los sensores de suelo
No hay datos reales ni satelitales en el repositorio. Se define el puerto `ObservationSource` (series con clasificación y calidad). Mientras no haya `REAL_VERIFIED`, la «validación cruzada» del texto se implementa **entre variables del gemelo** (VWC ↔ transpiración ↔ LAI como sustituto de «NDVI»), etiquetada `SIMULATED_REAL_DATA_SUBSTITUTE`, y el CoT sigue las mismas etapas (tendencia física → contraste → diferenciación consumo real vs. fallo de lectura, **simulando fallos de sensor como eventos del gemelo** para tener verdad de terreno). Cuando existan datos reales, solo se añade un adaptador; el checker y los informes ya distinguen la clasificación.

## 7. Estructura de repositorio propuesta
```
src/agri_twin/domain/xai/{timeseries_analyzer,semantics,attribution,consistency}.py
src/agri_twin/application/xai/{frames,pipeline,rag,prompts}.py
src/agri_twin/infrastructure/xai/{timesfm_client,llm_client,embedding_client,recorder}.py
src/agri_twin/interfaces/xai_api.py
src/{xai_variable_roles,xai_semantics,xai_consistency_rules}.json     # provisionales, con fuente/estado
schemas/xai/*.json
services/{timesfm,llm,embed}/Dockerfile + app/                        # contenedores (arm64 / CUDA 13)
docker-compose.xai.yml
docs/xai/{XAI_TIMESERIES_DESIGN,DECISIONS_XAI,RUNBOOK_DGX_SPARK}.md
tests/test_xai_*.py   manual_phase6_*_test.py   data/xai/
```

## 8. Calendario orientativo (1 agente, jornadas de trabajo)
6.0 (0,5) → 6.1 (1–2) → 6.2 (2–3) → 6.3 (3–4) → 6.4 (3) → 6.5 (4–5) → 6.6 (3–4) → 6.7 (3) → 6.8 (4–5) → 6.9 (3–4). **Total 27–34 jornadas.** Camino crítico: 6.3 → 6.5 → 6.8. Las fases 6.2 y 6.4 pueden avanzar en paralelo a 6.3 si hay dos agentes (dominios disjuntos).

## 9. Determinismo, reproducibilidad y auditoría
* **Determinista de extremo a extremo:** frames, analytics, atribución, hechos, Markdown, RAG (recuperación), checker. **No determinista por naturaleza:** el texto del LLM → se mitiga con `temperature=0`, `seed`, salida estructurada, y se **audita** (prompt/response hash, modelo, fingerprint). La caché *record/replay* permite reproducir exactamente un informe.
* Toda salida lleva: versiones (imágenes por digest, `timesfm`, `vllm`, modelo), `index_fingerprint`, `trajectory_hash` del gemelo, `request_hash`, estado científico y clasificación del dato.
* Los informes no incluyen marcas de tiempo de pared; el reloj de simulación es el único tiempo.

## 10. Riesgos y mitigaciones
| Riesgo | Mitigación |
|---|---|
| **Licencia de los pesos TimesFM 3.0** (no comercial) | D1 antes de 6.3; puerta de licencia; adaptador intercambiable; alternativas §11 |
| Imágenes arm64/SM121 inestables | fijar por digest; runbook; probar `torch.cuda.is_available()` y un forecast mínimo en `/health` |
| API de TimesFM cambia | adaptador único + prueba de contrato con el doble; fijar versión |
| El LLM alucina o parafrasea cifras | hechos con ID, salida estructurada, checker *fail-closed*, retirada de afirmaciones sin base |
| «Importancia» del modelo ≠ causa física | validación frente al gemelo obligatoria; degradación del lenguaje |
| Sobreinterpretar series simuladas como reales | clasificación y frase de estado en cada salida; test que la exige |
| Memoria unificada insuficiente | presupuesto en 6.6; LLM dimensionado; `embed` pequeño; TimesFM ocupa ~1,3 GB |
| Falsa confianza en cuantiles | cobertura empírica de 6.3; si no está respaldada, se dice «nominal» |
| Deriva del contrato de variables | `xai_variable_roles.json` versionado + prueba de anti-fuga |

## 11. Alternativas si D1 impide usar los pesos 3.0
* **TimesFM 2.5** (pesos Apache-2.0, univariante con regresión de covariables XReg) *(verificar capacidades actuales)*.
* **Chronos-2** (Amazon, multivariante con covariables, Apache-2.0) *(verificar)*.
* **BigQuery ML con TimesFM 3.0** (uso comercial autorizado vía Google Cloud; exige red y cuenta: rompe el modo offline).
La arquitectura (puerto `ForecastBackend`) hace el cambio local a `infrastructure/xai/` y a la fase 6.3.

## 12. Decisiones que debe tomar el usuario (preguntar al agente antes de la fase 6.3)
* ~~**D1 – Uso y licencia:**~~ (resuelta: investigación, ver §12bis) ¿el trabajo es investigación/TFG no comercial, o se desplegará en explotaciones reales? Determina si se pueden usar los pesos 3.0 en la Spark.
* ~~**D2 – LLM:**~~ (criterios y procedimiento fijados en §12bis; la elección se hace con el banco de la fase 6.6) ¿qué modelo ejecutar (tamaño/familia, licencia, español)? Criterios: cabe en la memoria unificada junto al resto, soporte de salida estructurada en vLLM/SM121, latencia aceptable.
* ~~**D3 – Idioma de las explicaciones:**~~ (resuelta: ES + EN) español (propuesto), inglés o ambos.
* ~~**D4 – Almacén vectorial:**~~ (resuelta: Docker en la Spark) fichero/SQLite local (propuesto, sin servicio extra) o un servicio dedicado.
* **D5 – Umbrales de aprobación** de la fase 6.9 (fidelidad mínima para lenguaje causal, tasa de fundamentación).
* **D6 – Alcance del corpus RAG:** solo `docs/` y catálogo (propuesto) o también documentos que usted aporte (¿cuáles, con qué licencia?).
* ~~**D7 – Variables objetivo prioritarias**~~ (propuesta en §12bis, pendiente de que el usuario elija entre A/B/C y aporte precios) para empezar (propuesta: `temperature_c`, `relative_humidity_pct`, `vpd_kpa`, `soil_water_vwc_m3_m3`).

## 12bis. Decisiones del usuario (2026-10-23) y su efecto en el diseño

| Decisión | Respuesta | Efecto |
|---|---|---|
| D1 Uso y licencia | **Investigación, no comercial** | Se pueden usar los pesos TimesFM 3.0 en la Spark con `TIMESFM_LICENSE_ACK=non-commercial-research`. Quedan fuera el despliegue en explotaciones reales y el uso de producción; documentar la restricción en cada informe y **leer el texto de la licencia antes de compartir resultados o pesos** |
| D3 Idioma | **Español e inglés** | Las explicaciones se generan en ambos idiomas con el mismo `Explanation` estructurado (los hechos y `fact_id` son idénticos; solo cambia el texto); el verificador se ejecuta sobre cada idioma; el vocabulario cerrado de tendencias (`xai_semantics.json`) lleva etiquetas ES/EN |
| D4 Almacén vectorial | **Docker en la Spark** | Servicio `vector-store` en `docker-compose.xai.yml` (imagen **arm64**; candidatos Qdrant o Chroma *(verificar tag arm64)*), volumen persistente, solo red interna; `index_fingerprint` sigue siendo el hash del corpus |
| D6 Corpus RAG | **Sin corpus específico** (2026-10-24) | El RAG indexa solo `docs/` y `src/crop_config.json` hasta que el usuario aporte documentos con licencia |
| LLM (D2) | Disponibles en Docker en la Spark: **OLMo, Llama y Qwen** (2026-10-24) | La elección se hace con el banco de la fase 6.6 entre estos tres; inventariar versiones, cuantizaciones y licencias |
| Estudio con expertos (RQ7) | **En el alcance; ética aprobada** (2026-10-24) | Alcance completo, sin fecha límite: prima el producto |
| Código del TFG | **No existe**: se reimplementa desde la memoria (2026-10-24) | Se corrigen las brechas B1-B8 de `XAI_SCIENTIFIC_DESIGN.md` |
| Alcance | **Invernadero y campo abierto** | `MultivariateFrame` y los roles de variable cubren ambos; en campo abierto no hay `greenhouse_*`, `co2_ppm` ni control climático, y el riego es la única palanca de control |
| Horizonte | **Temporada completa** | Dos escalas, ver abajo |
| Precios | **El usuario aporta rendimiento y precios de energía y agua** | Ver «Objetivos de temporada» |

### Escalas temporales
* **Operativa (horaria, previsión móvil de 24-168 h):** TimesFM 3.0 con covariables futuras (forzamiento y plan de actuación). Sirve para explicar «qué va a pasar y por qué» a corto plazo.
* **Temporada (diaria, 100-300 pasos):** TimesFM sobre series **agregadas a día** (medias, máximos, sumas) para tendencias de la temporada completa, y **el gemelo** como optimizador/oráculo de estrategias. TimesFM no se usa para predecir miles de horas seguidas (el error se acumula); la previsión horaria larga se descarta por diseño.

### Objetivos de temporada (resuelve D7)
* **Variables que predice TimesFM** (horarias y diarias): `temperature_c`, `vpd_kpa`, `soil_water_vwc_m3_m3`, `greenhouse_heating_kw`/`greenhouse_cooling_kw` (invernadero), `growth_factor` como puente explicativo. Los estrés se derivan con las reglas del gemelo.
* **KPIs de temporada (calculados, no predichos), sobre la misma simulación:**
  1. **Rendimiento:** `Δbiomass_fruit_g_m2` acumulado (materia seca); en kg de fruto fresco solo con el **% de materia seca definido por el usuario** (no existe en el repositorio) y la superficie.
  2. **Agua:** `irrigation_mm` acumulado (y m³ = mm × superficie / 1000), fracción drenada, eficiencia = fruto por litro.
  3. **Energía:** `control_energy_kwh` (solo con controlador y rendimientos del usuario) y su coste con la tarifa (`application/energy_cost.py`).
  4. **Riesgo/estrés:** horas fuera del rango óptimo de la etapa (de `crop_config.json`), días de estrés por calor/agua/VPD y daño por helada.
* **Ya implementado (fase 5.47, `docs/phase5_47_site_resources.md`):** configuración conjunta `src/site_resources.json` (equipos y rendimientos, precios de electricidad, combustible de calefacción y **agua**, % de materia seca del producto) y `application/season_kpis.py` (`POST /api/kpis/season`) con el vector A y el **coste de recursos** (vista C, sin precio del fruto: €/m², €/kg de producto). La fase 6.1 del XAI **reutiliza** estos KPIs; no se reimplementan.
* **Precios del usuario:** energía (ya existe: precio único, tabla por año y franjas), **agua** (€/m³, a añadir con el mismo esquema que la tarifa) y **fruto** (€/kg, a añadir). Sin precio, el coste queda vacío; ninguna conversión se supone.
* **Salida de resultados (tres vistas sobre las mismas simulaciones):**
  * **A. Vector** (rendimiento, agua, energía, riesgo) por estrategia, con la línea base (termostato por defecto) y sin pesos: informe principal; incluye las estrategias dominadas y el frente de compromisos.
  * **C. Margen económico** con los precios del usuario (los precios hacen de pesos, ninguno inventado), con sensibilidad a escenarios de precio.
  * **B. Un objetivo con restricciones** (p. ej. máximo rendimiento con cupo de agua y energía fijados por el usuario) como herramienta opcional, también para trazar el frente variando el límite.
  Con el modelo de cultivo sin calibrar, las comparaciones valen en **orden y dirección**, no en valores absolutos de gramos o euros; los informes lo dicen.
* **Qué no existe y no se inventa:** calidad del fruto (calibre, azúcar, firmeza; `fruit_count` no está representado) y precio por calidad. «Mejor fruto» significa más materia seca de fruto.

### D2 – Criterios y procedimiento de selección del LLM

**Requisitos del usuario:** bilingüe español/inglés, buen rendimiento por token en la Spark, **pesos abiertos**, y buena evidencia de fiabilidad y ausencia de alucinaciones.

**Lo que se sabe (fuentes secundarias, contrastar con las primarias antes de decidir):**
* **El rendimiento lo limita el ancho de banda de memoria (~273 GB/s), no la capacidad.** Los modelos **densos grandes** son impracticables (Llama 3.1 70B: ~3-4 tok/s) y los **MoE de pocos parámetros activos** son los viables: gpt-oss-120b ~33-61 tok/s según motor y longitud de contexto; un MoE de ~30B (familia Qwen3) ~44-81 tok/s. Las cifras varían casi 2× entre motores (llama.cpp, SGLang, vLLM) y con la longitud del prompt y la salida JSON restringida. Fuentes: [discusión llama.cpp #16578](https://github.com/ggml-org/llama.cpp/discussions/16578), [LMSYS](https://www.lmsys.org/blog/2025-11-03-gpt-oss-on-nvidia-dgx-spark/), [gpuwerk](https://gpuwerk.com/docs/benchmarks/).
* **Los rankings de alucinación se contradicen y miden cosas distintas.** Vectara HHEM mide consistencia **con un texto dado** (resumen fundamentado: lo más parecido a esta tarea); AA-Omniscience mide conocimiento factual **sin contexto** y un % bajo de alucinación puede venir de **negarse a responder**. Las tablas agregadas se contradicen entre sí (el mismo modelo con ~3 % y ~10,6 %). Ninguno sirve para decidir, solo para **preseleccionar**.

**Conclusión de diseño:** no se elige por un ranking público. Se **preselecciona por criterios duros** y se decide con una **evaluación propia en la fase 6.6**, que mide exactamente lo que importa aquí.

**1. Filtro duro (preselección):**
| Criterio | Regla |
|---|---|
| Pesos abiertos y licencia | Descargables; leer la licencia (Apache-2.0/MIT preferibles; licencias propias o no comerciales son válidas para investigación **si se documentan**, pero no se pueden redistribuir sin revisarlas) |
| Arquitectura | **MoE con pocos parámetros activos** (o denso ≤ ~14B) para cumplir la latencia en la Spark; descartar densos ≥ 30B |
| Idiomas | Español e inglés **declarados** por el autor y comprobados en la evaluación propia |
| Salida estructurada | Soporte de JSON Schema/`guided_json` en el motor elegido (vLLM/SGLang/llama.cpp en arm64 + SM121) |
| Contexto | ≥ 16 k tokens útiles (el prompt lleva hechos, Markdown y fragmentos RAG) |
| Cuantización | FP8/MXFP4/Q8 oficial o de calidad contrastada; se evalúa **la cuantización que se desplegará**, no la de referencia |

**2. Banco de evaluación propio (entregable de la fase 6.6, sin servicios externos y con los hechos del gemelo):** todo con `temperature=0`, ES y EN, N repeticiones.
| Prueba | Qué mide | Cómo |
|---|---|---|
| **Fundamentación** | % de afirmaciones con `fact_id` correcto | Los casos de la fase 6.4; el verificador de la fase 6.7 como juez determinista, no otro LLM |
| **Cifras inventadas** | tasa de números sin hecho | extracción de cifras del texto frente a los hechos |
| **Abstención útil** | ¿dice «no definido» cuando falta un umbral o un dato? | casos con umbral ausente, serie constante, datos con huecos |
| **Premisas falsas** | ¿acepta una premisa incorrecta del prompt? | casos adversarios grabados (p. ej. «explica la variación» de una serie constante) |
| **Paridad ES/EN** | mismas afirmaciones con los mismos hechos en ambos idiomas | comparación de conjuntos de `claim` y `fact_id` entre idiomas |
| **Obediencia al esquema** | JSON válido a la primera | % de respuestas que pasan `jsonschema` sin reintento |
| **Rendimiento en la Spark** | tok/s de generación y de prefill con **prompts reales de 4-12 k tokens**, memoria, latencia p50/p95 | el motor y el contenedor que se desplegarán |
| **Estabilidad** | variación entre repeticiones | misma entrada N veces |
Criterio de aceptación a fijar en D5; regla de desempate: **menos afirmaciones sin base tras el verificador**, después latencia, después licencia.

**3. Procedimiento:** preseleccionar 3-4 modelos con el filtro duro (idealmente de familias distintas, p. ej. un MoE de OpenAI de pesos abiertos, uno de la familia Qwen3, uno de Gemma y uno de Mistral, **verificando vigencia, licencia y soporte en la Spark en el momento de elegir**), ejecutar el banco, publicar la tabla en `docs/xai/LLM_SELECTION.md` y fijar el ganador y un **segundo de reserva** en el ADR. El modelo es una **variable de configuración** (`LLM_MODEL`, imagen por digest) y todo el pipeline funciona con cualquiera gracias a la salida estructurada y al verificador.

**4. Lo que no se hará:** confiar en que un LLM «no alucina» por su posición en un ranking; el sistema asume que **alucinará** y lo contiene con hechos con identificador, salida estructurada, verificador determinista (*fail-closed*) y retirada de afirmaciones sin base. La fiabilidad del sistema depende de esa arquitectura más que del modelo.

## 13. Instrucciones de arranque para el agente
1. Lee `CLAUDE.md`, `docs/architecture/ARCHITECTURE_REQUIREMENTS.md`, `EVENTS_AND_CAUSALITY.md`, `docs/scientific-limitations.md`, `docs/phase5_44_greenhouse_consistency.md`, `docs/phase5_45_et0_penman_monteith.md`, `docs/phase5_46_energyplus_lockstep.md` y este documento.
2. Haz la **fase 6.0** y presenta el ADR con las preguntas D1–D7; **espera respuesta** antes de la 6.3.
3. Avanza fase a fase con el patrón de entrega (§0.3), un commit por fase, suite completa en verde, sin editar archivos mientras corre.
4. Ante cualquier conflicto entre este documento y `CLAUDE.md`, gana `CLAUDE.md`; documenta la discrepancia.
5. Nunca inventes: umbrales, parámetros agronómicos, resultados de servicios no ejecutados ni fuentes. Si un dato no existe, la salida dice «no definido» o «no ejecutado».
