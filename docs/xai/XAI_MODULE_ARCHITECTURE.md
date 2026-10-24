# Arquitectura del módulo XAI como paquete reutilizable

Directriz de diseño (2026-10-24): **el módulo XAI debe poder usarse en otros proyectos; su modularidad y su capacidad de integración forman parte del diseño**, no un añadido posterior. Este documento sustituye, en lo que afecte a la estructura del código, a la ubicación `agri_twin/{domain,application,infrastructure}/xai` que se usó en la fase 6.0 y que la fase 6.1b continuó. El gemelo pasa a ser **un adaptador** del módulo, no su casa.

## 1. Objetivos de diseño

| Objetivo | Qué significa en la práctica |
|---|---|
| **Independiente** | Se instala y se prueba sin el gemelo. El núcleo no importa `agri_twin` (una prueba automática lo vigila) |
| **Integrable** | Un proyecto nuevo lo conecta implementando **pocos puertos** (≈100 líneas), con un simulador de juguete y un ejemplo completo que lo demuestran |
| **Agnóstico del dominio** | Nada de «cultivo», «invernadero» ni umbrales agronómicos en el núcleo; el conocimiento del dominio entra por un **paquete de dominio** (vocabulario, umbrales, reglas del verificador) |
| **Agnóstico de modelos** | Pronosticador, LLM y recuperador se enchufan por puertos; TimesFM, Chronos, un modelo entrenado, OLMo, Llama o Qwen son adaptadores intercambiables |
| **Estable** | Versionado semántico, API pública declarada (`__all__`), contratos de datos con `schema_version`, política de obsolescencia |
| **Verificable** | Pruebas de contrato que **cualquier adaptador debe pasar**; determinismo con hashes; pruebas de capas |
| **Ligero por defecto** | El núcleo solo exige la biblioteca estándar; el análisis numérico (numpy, statsmodels, ruptures) y los clientes HTTP van como extras opcionales |
| **Citable y abierto** | Licencia permisiva, versión archivable, datos y código del banco publicables (los pesos de TimesFM, no) |

## 2. Estructura propuesta

Un **paquete independiente dentro del mismo repositorio**, con su propio `pyproject.toml`, de modo que pueda extraerse a un repositorio propio sin tocar el código (nombre provisional `tsxai`, ver §10):

```
xai/                                  ← distribución independiente (pip install ./xai)
  pyproject.toml                      núcleo: solo biblioteca estándar; extras: [analysis] [http] [bench] [all]
  README.md  LICENSE  CITATION.cff  CHANGELOG.md
  src/tsxai/
    core/            contratos y tipos: puertos, hashing canónico, esquemas versionados, errores
    analysis/        preprocesado, STL/MSTL, puntos de cambio, suavizado, rasgos      (extra: analysis)
    forecast/        ForecastBackend, líneas base (naive, Holt-Winters, regresión con retardos), adaptador HTTP (TimesFM, Chronos…)
    attribution/     oclusión, permutación por bloques, gradiente, SHAP agrupado, contrafácticos; métricas de fidelidad
    semantics/       Enricher y Formatter con vocabulario cerrado y niveles de evidencia, guiados por un paquete de dominio
    llm/             LanguageModel: cliente compatible con OpenAI (vLLM), salida estructurada, registro/reproducción
    rag/             Retriever, troceado estable, rag_audit, adaptador de almacén vectorial
    verify/          motor del verificador y reglas genéricas (trazabilidad, unidades, nivel de evidencia); los paquetes de dominio añaden las suyas
    bench/           generador de benchmark causal sobre un SimulatorPort, modelos de error de sensor, particiones, métricas, estadística
    report/          «ExplanationBundle» (JSON versionado) y renderizadores (Markdown, HTML Glass Box)
    testing/         pruebas de contrato para adaptadores, simulador de juguete, dobles de LLM y pronosticador
    cli.py           tsxai bench|analyze|forecast|explain|verify  (offline por defecto)
  examples/          toy_simulator/ (sin dependencias), second_domain/ (otro dominio completo), notebook de uso
  docs/              guía de uso, guía de integración «conecta tu simulador», referencia de esquemas
  tests/             del núcleo, sin importar ningún proyecto anfitrión

agri_twin/…/xai_adapter.py            ← adaptador del gemelo (depende de tsxai y de agri_twin; el núcleo no depende de él)
src/*.json                            ← configuración específica del gemelo (roles, diseño del banco, umbrales por etapa)
frontend/bench.*                      ← consume el ExplanationBundle por HTTP (la interfaz es del anfitrión)
```

**Regla de dependencia:** `tsxai` → (nada del anfitrión). `agri_twin` → `tsxai`. Nunca al revés. Si una función necesita saber algo del dominio, lo pide por un puerto.

## 3. Puertos de integración (lo que un proyecto anfitrión implementa)

| Puerto | Qué hace | Obligatorio | En el gemelo | Ejemplo en otro proyecto |
|---|---|---|---|---|
| **`SeriesSource`** | Entrega series con unidades, calidad y metadatos (sin intervenciones) | Sí | Resultado de una simulación o datos reales futuros | Telemetría de un edificio, de una cuenca |
| **`VariableCatalogue`** | Describe cada variable: unidad, rol (objetivo, covariable futura conocida, decisión, solo pasada, contexto, excluida), razón | Sí | `xai_variable_roles.json` + catálogo de la API | Su propio catálogo |
| **`SimulatorPort`** | Ejecuta escenarios y **ejecuciones pareadas con una intervención**, con determinismo (hash) y límites de cada intervención | Solo para el banco causal (G2/G4) | `InteractiveSimulationService` | Cualquier simulador con semilla |
| **`DomainPack`** | Vocabulario (frases y su ES/EN), umbrales por contexto, reglas duras del verificador, prohibiciones de afirmación | Para la capa semántica y el verificador | Umbrales de `crop_config.json`, reglas agronómicas, «sin afirmar calibración» | Reglas de su dominio |
| **`ForecastBackend`** | Pronostica con covariables (cuantiles) | Para previsión y atribución | TimesFM 3 en la Spark | Chronos, un modelo propio |
| **`LanguageModel`** | Genera salida estructurada determinista | Para la capa lingüística | vLLM en la Spark (OLMo, Llama, Qwen) | Cualquier API compatible con OpenAI |
| **`Retriever`** | Recupera fragmentos con puntuación y huella del corpus | Opcional | Documentos del proyecto | Su corpus |
| **`BundleSink`** | Recibe el `ExplanationBundle` | Opcional | API HTTP + Glass Box del bench | Su interfaz o archivo |

Un proyecto nuevo puede empezar con solo `SeriesSource` + `VariableCatalogue` y obtener ya el análisis, la previsión con líneas base y la atribución; el resto se añade por capas.

## 4. Contratos de datos versionados

Todos los objetos que cruzan una frontera (`Frame`, `AnalyticsReport`, `ForecastReport`, `AttributionReport`, `SemanticFact`, `Explanation`, `ConsistencyCorrection`, `RagAudit`, `ExplanationBundle`) son:
* inmutables, con `schema_version` explícito y **JSON Schema** publicado en `xai/schemas/`;
* canónicos (claves ordenadas, sin NaN) con `content_hash` SHA-256, para que un resultado quede atado a lo preguntado y a lo respondido;
* compatibles hacia atrás dentro de una versión mayor (campos nuevos opcionales); un cambio incompatible sube la versión mayor y trae un migrador.

## 5. Configuración, ejecución y CLI

* **Configuración declarativa** (JSON/YAML) que nombra los adaptadores por su ruta (`módulo:Clase`) y también por **puntos de entrada** (`tsxai.adapters`), de modo que un proyecto registra su adaptador sin tocar el núcleo.
* **Offline por defecto**: ningún acceso a red sin que un adaptador de red esté configurado; los servicios pesados (TimesFM, LLM, vector) se alcanzan por HTTP.
* **CLI** `tsxai` para ejecutar el banco, el análisis, la previsión, la explicación y la verificación sobre los datos de cualquier anfitrión.
* **Determinismo**: semillas explícitas, sin reloj de pared, registro/reproducción de las respuestas del LLM para repetir un informe exacto.

## 6. Pruebas de contrato y ejemplos (la prueba de que se integra)

* **`tsxai.testing.contract`**: una batería que cualquier adaptador (de un simulador, un dominio, un LLM, un pronosticador) ejecuta para demostrar que cumple el puerto: determinismo, hashes estables, límites respetados, ausencia de efectos laterales, errores tipificados.
* **Simulador de juguete** (`examples/toy_simulator`, solo biblioteca estándar): un sistema con causalidad conocida (estructura causal con retardos, regímenes con umbral y saturación) que permite ejecutar **todo el pipeline y el banco** sin el gemelo. Sirve de documentación viva y de prueba de independencia.
* **Segundo dominio** (`examples/second_domain`): una integración completa de otro dominio (por ejemplo, un modelo térmico simple de un edificio o un depósito de agua) que demuestra la generalidad. **Decisión abierta (§10)**: aporta validez externa al artículo a cambio de trabajo.
* **Pruebas de capas** automáticas: el núcleo no importa ningún anfitrión; `analysis`/`attribution`/`semantics`/`verify` no hacen red ni usan reloj; solo `llm`, `rag` y `forecast` (adaptadores) pueden tener E/S.

## 7. Empaquetado, versiones y calidad

* Versionado **semántico**; `CHANGELOG.md`; API pública = lo exportado en `__all__` (lo demás es privado); política de obsolescencia de dos versiones menores.
* **Licencia permisiva** (Apache-2.0 o MIT, a decidir) y `CITATION.cff`; aviso de que **los pesos de TimesFM tienen licencia propia** (no comercial) y no se distribuyen con el paquete.
* **CI** reproducible: tests del núcleo con solo la biblioteca estándar, tests con extras, pruebas de contrato con el simulador de juguete, comprobación de tipos y de estilo cuando se adopten.
* **Documentación**: guía de uso, guía «conecta tu simulador» con un ejemplo mínimo, referencia de esquemas, cómo añadir un `DomainPack`, cómo cambiar de pronosticador o de LLM.

## 8. Cómo encaja el gemelo

El gemelo implementa `SeriesSource`, `VariableCatalogue`, `SimulatorPort` y `DomainPack` en un único módulo adaptador (`agri_twin/interfaces/xai_adapter.py` y sus JSON). El frontend del bench consume el `ExplanationBundle` por HTTP y lo pinta (Glass Box). El segundo artículo (el gemelo) cita al módulo como una de sus capacidades; el módulo no sabe que existe el gemelo.

## 9. Migración (hecha el 2026-10-24)

El código provisional de las fases 6.0 y 6.1b dentro del gemelo (`domain/xai`, `application/xai`, `infrastructure/xai`) se **eliminó** y se rehízo en el paquete independiente **TSXAI** (`tsxai`, repositorio `https://github.com/farcasucam/tsxai`, Apache-2.0, versión 0.1.0), con su simulador de juguete y las pruebas de contrato (`check_simulator`). En el gemelo queda:

| Pieza | Dónde |
|---|---|
| Adaptador `SimulatorPort` del gemelo (catálogo, factores, contextos, ejecución) | `src/agri_twin/interfaces/xai_adapter.py` (único módulo que importa `tsxai`, vigilado por prueba) |
| Roles de variables (convención provisional) | `src/xai_variable_roles.json` |
| Convenciones de muestreo del banco (no son valores agronómicos) | `src/xai_benchmark_design.json` |
| Pruebas del anfitrión | `tests/test_xai_adapter.py` (se omite si `tsxai` no está instalado) |
| Verificación de entrega | `manual_phase6_1b_xai_benchmark_test.py` |

Dependencia: `tsxai` es opcional para el gemelo (`pip install -e ../tsxai`); el gemelo no funciona peor sin él.

## 10. Decisiones

| # | Decisión | Respuesta (2026-10-24) |
|---|---|---|
| 1 | Nombre | **TSXAI** (`tsxai`) |
| 2 | Licencia | **Apache-2.0** |
| 3 | Ubicación | **Repositorio nuevo** `https://github.com/farcasucam/tsxai` (local en `../tsxai`; sin publicar todavía) |
| 4 | Segundo dominio de ejemplo | **Sí**: uno sencillo de industria química controlada por PLC. Hecho en `tsxai.examples.PlcReactor` (reactor encamisado exotérmico, lazo PI de válvula con límite de velocidad y enclavamiento de alta temperatura enclavado con rearme; pasa el contrato y el banco; constantes ilustrativas, no es una planta real) |
| 5 | Datos reales | El puerto `SeriesSource` queda preparado y sin uso hasta que haya datos reales |
