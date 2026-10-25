# Decisiones de la fase XAI (ADR)

Registro de decisiones del proyecto XAI de series temporales. Cada decisión lleva fecha, motivo y consecuencias. Las pendientes se marcan así y no se asumen.

## Decididas

| # | Decisión | Fecha | Motivo | Consecuencias |
|---|---|---|---|---|
| D1 | Uso de **investigación, no comercial** | 2026-10-23 | Es un proyecto de investigación | Se pueden usar los pesos de TimesFM 3 (licencia no comercial); no se despliega en explotaciones reales ni en producción; no se redistribuyen los pesos; **leer el texto completo de la licencia** antes de compartir resultados (hasta ahora solo se ha leído el resumen del README) |
| D3 | Explicaciones en **español e inglés** | 2026-10-23 | Requisito del usuario | Mismos hechos y `fact_id`, texto en ambos idiomas, verificador sobre cada idioma, paridad ES/EN como métrica (H5c) |
| D4 | Almacén vectorial en **Docker en la Spark** | 2026-10-23 | Requisito del usuario | Imagen arm64 (candidatos Qdrant o Chroma, verificar el tag), volumen persistente, solo red interna |
| D6 | **Sin corpus específico** por ahora | 2026-10-24 | No existe material con licencia clara | El RAG indexa solo `docs/` del proyecto y `src/crop_config.json`; sin manuales externos; el `rag_audit` funciona igual; se amplía cuando el usuario aporte documentos con su licencia |
| D7 | Objetivos: rendimiento, agua y energía; **vector A + coste de recursos C** | 2026-10-23 | Análisis de objetivos | Ver `XAI_TIMESERIES_DESIGN.md` §12bis y la fase 5.47; el producto no tiene precio |
| — | **Sin código del TFG**: se reimplementa desde la descripción de la memoria | 2026-10-24 | No existe el repositorio | Se respeta el comportamiento descrito (STL, PELT, Holt-Winters, degradación elegante, enriquecimiento, verificador) y se **corrigen** las brechas B1-B8 de `XAI_SCIENTIFIC_DESIGN.md` §1 |
| — | **Estudio con expertos (RQ7) dentro del alcance**; la ética está aprobada | 2026-10-24 | Hay expertos y aprobación | El diseño del estudio sigue `XAI_SCIENTIFIC_DESIGN.md` RQ7; se registra el número de expertos y la aprobación en el preregistro |
| — | **Sin fecha límite**: prima el producto | 2026-10-24 | Prioridad del usuario | Alcance completo (RQ1-RQ7), no el mínimo; se prioriza la calidad y la reproducibilidad |
| — | El **TFG no se sube a GitHub** | 2026-10-24 | Decisión del usuario | `docs/xai/TFG.pdf` está en `.gitignore` y una prueba lo vigila |
| — | LLM candidatos ya disponibles en Docker en la Spark: **OLMo, Llama y Qwen** | 2026-10-24 | Inventario del usuario | La elección (D2) se hace con el banco de la fase 6.6 entre estos tres; hay que **inventariar versiones, tamaños, cuantizaciones y licencias** en la Spark |
| — | **El módulo XAI es reutilizable en otros proyectos**: modularidad e integrabilidad forman parte del diseño | 2026-10-24 | Directriz del usuario | Paquete independiente (`xai/`, nombre provisional `tsxai`) con puertos, simulador de juguete, pruebas de contrato y adaptador del gemelo; ver `XAI_MODULE_ARCHITECTURE.md`. **Sustituye la ubicación `agri_twin/*/xai` de la fase 6.0 y 6.1b** (migración antes de commitear) |
| — | **La parte XAI alimenta un artículo Q1 de IA explicativa aplicada; el gemelo será un segundo artículo** | 2026-10-24 | Directriz del usuario | Estrategia en `PUBLICATION_STRATEGY.md`: contribuciones C1-C4 como hipótesis, revisión sistemática previa (nueva fase 6.0b), alineación con Co-12, ciencia abierta, estudio humano, validez externa |
| — | TimesFM: **de acuerdo con el papel propuesto** (comparador y objeto de explicación, con puerta de viabilidad 6.3a) | 2026-10-23 | Evaluación científica | Si falla el uso de covariables, la explicación L2/L3 se construye sobre un modelo agnóstico |
| D8 | **Lector principal: el investigador** (científico de datos, ingeniero de XAI, agrónomo teórico) | 2026-10-25 | Respuesta del usuario | El texto de L4 es técnico, preciso, factual y estructurado como informe pericial o artículo; sin lenguaje comercial ni simplificado. El valor del artículo es mostrar explicaciones válidas y verificables contra el gemelo, no una interfaz para el agricultor |
| D9 | **Contexto principal: invernadero con control (C)**; el resto, como contraste de generalización | 2026-10-25 | Es el reto científico mayor (bucle cerrado y riesgo de circularidad) | El análisis primario se restringe a C (tomate, lechuga y pimiento con control encendido, con y sin realimentación); el exterior, el invernadero sin control y el reactor con PLC son contrastes que muestran la versatilidad de tsxai. El núcleo de la discusión: cómo la XAI separa el forzamiento climático de la reacción automática del controlador |
| D10 | **Prioridad: la escala horaria** (ventanas de 14 a 20 días) | 2026-10-25 | Los previsores, el piloto y los datos están diseñados para ella | La escala de temporada queda como discusión, trabajo futuro o subproducto (el gemelo como optimizador); no consume desarrollo del núcleo de las fases 6.4-6.7 |
| D11 | **En C el objeto a explicar es el controlador**: su consumo y sus activaciones (`greenhouse_heating_kw`, `greenhouse_cooling_kw`, energía) ante el forzamiento exterior | 2026-10-25 | Explicar el interior con las ventanas, que son salidas del controlador, es circular y un revisor lo rechazaría | En C las salidas del controlador no son palancas ni plan (el adaptador ya las degrada a covariables solo pasadas); el clima interior es una consecuencia observada. Los contrafácticos de C son sobre el forzamiento exterior y su efecto en la demanda del controlador. El banco necesita más escenarios en C (el piloto de desarrollo tiene 6 de 22 escenarios y 11 intervenciones en C) |

## Pendientes

| # | Qué falta | Quién | Bloquea |
|---|---|---|---|
| D2 | Elegir el LLM entre OLMo, Llama y Qwen | banco de la fase 6.6 | 6.6 en adelante |
| — | Nombre del paquete, licencia (propongo Apache-2.0), ubicación (subcarpeta `xai/` propuesta), segundo dominio de ejemplo (recomendado) | usuario | Reorganización del código (6.0 rehecha) |
| — | Autores y filiación, preprint, revista objetivo, segunda lectura de la revisión sistemática; política de la universidad y de la revista sobre el uso de contenido del TFG | usuario | Redacción; no el código |
| D5 | Umbrales de aprobación de la fase 6.9 | se congelan en el preregistro (6.1b) | 6.9 |
| — | Pasar el acceso a la Spark de contraseña a **clave SSH** y rotar la contraseña (ya figura en la conversación) | usuario | Nada: el acceso funciona (ver el inventario) |
| — | Número de expertos y detalle del protocolo ético aprobado | usuario | RQ7 |
| — | Coordenadas de las zonas meteorológicas y de las parcelas tipo (aproximadas) | usuario | Resultados que dependan del sitio (Penman-Monteith) |

## Reglas operativas

* **Credenciales:** no se escriben en archivos, ni en el repositorio, ni en la memoria del asistente. Para el trabajo con la Spark se prefiere **clave SSH** (sin contraseña en texto) y rotar cualquier contraseña compartida por chat.
* **Línea base del gemelo:** antes del banco de pruebas (6.1b) se etiqueta la versión del repositorio; un cambio posterior del modelo físico invalida resultados anteriores.

## Decisiones de módulo y publicación (2026-10-24)

* **Módulo independiente TSXAI** (`tsxai`), **Apache-2.0**, **repositorio nuevo** `https://github.com/farcasucam/tsxai` (privado y sin publicar por ahora). El gemelo lo usa solo a través de `interfaces/xai_adapter.py`.
* **Artículos:** XAI de series temporales (Q1, aplicado) y, aparte, el gemelo. Sin preprint por ahora; revista objetivo sin fijar (sugerencias en `PUBLICATION_STRATEGY.md` §9).
* **Autoría:** Francisco Arcas-Túnez (farcas@ucam.edu); detalles más adelante.
* **TFG:** dirigido por el autor, en su universidad; no se requiere permiso. **El PDF no se sube a GitHub** (`.gitignore`).
* **Segundo dominio:** industria química controlada por PLC, sencillo (`tsxai.examples.PlcReactor`).
* **Revistas:** se eligen con resultados; JCR, poca complejidad de publicación y acuerdos UCAM (ScienceDirect/Elsevier, ACS, CUP).
* **Medido:** generar el banco cuesta unos **11-15 s por escenario** (cada ejecución repite la temporada desde el inicio de la campaña); la estimación anterior de 2-4 s era errónea. Mejora prevista: reutilizar el prefijo con puntos de control.

## Inventario de la DGX Spark (2026-10-24, solo lectura)

* **Equipo:** `spark-b6fe`, Ubuntu 24.04.5, **aarch64**, GPU **NVIDIA GB10**, controlador 580.178.04, **CUDA 13.0**, 121 GiB de memoria unificada (al hacer el inventario: 88 GiB en uso, ~32 GiB disponibles), disco de 3,7 TB con 3,2 TB libres; Docker 29.6.2; Python 3.12.3 del sistema.
* **Red:** salida a Hugging Face y PyPI (la página de `google/timesfm-3.0-pytorch` responde 200; no se ha descargado nada ni comprobado si el modelo exige aceptar la licencia o un token).
* **Contenedores LLM en marcha** (imagen `nvcr.io/nvidia/vllm:26.09-py3`, que trae PyTorch 2.14 con CUDA y reconoce la GB10; nombres `fgkb-*`, que **no se tocan**: no son de este proyecto):
  | Contenedor | Puerto | Modelo | Configuración |
  |---|---|---|---|
  | `fgkb-qwen` | 8000 | `Qwen/Qwen2.5-7B-Instruct` | bf16, contexto 8192, 22 % de memoria de GPU, semilla 0 |
  | `fgkb-llama` | 8001 | `meta-llama/Llama-3.1-8B-Instruct` | bf16, contexto 8192, 22 %, semilla 0 |
  | `fgkb-olmo` | 8002 | `allenai/Olmo-3-7B-Instruct` | bf16, contexto 8192, 22 %, semilla 0 |
* También hay `open-webui` (puertos 3000 y 11434), `ollama` y `traefik` parados, y en la caché de Hugging Face (167 GB) `Mistral-Small-3.2-24B-Instruct` y modelos de imagen.
* **Consecuencias para el diseño:**
  1. Los tres LLM son **densos de 7-8B en bf16**: caben, pero tienen menos fiabilidad que modelos mayores y el decodificado está limitado por el ancho de banda; se evalúan tal cual en el banco de la fase 6.6 y se deja abierta la comparación con un modelo mayor de mezcla de expertos si ninguno cumple.
  2. **El contexto es de 8192 tokens** (entrada + salida): el prompt semántico se diseña para **≤ ~5 000 tokens** y la respuesta para ≤ 2 000. Un contexto mayor exige reiniciar el contenedor con más memoria de caché, y con tres modelos cargados (~66 % de la GPU reservada) hay poco margen: **no se reinicia nada sin permiso del usuario**.
  3. El servicio TimesFM (330 M parámetros, ~1,3 GB) cabe en la memoria libre; se construirá un contenedor propio (`agritwin-timesfm`) basado en la imagen de vLLM o en una imagen NGC de PyTorch, con otro puerto y otro nombre, sin tocar los existentes.
  4. Idiomas: Llama 3.1 y Qwen2.5 declaran español; OLMo 3 es principalmente inglés (hipótesis: peor en español, a medir con la paridad ES/EN). Licencias (de memoria, **verificar en cada ficha**): Qwen2.5-7B y OLMo 3 Apache-2.0; Llama 3.1 con su licencia propia (atribución y uso aceptable), válida para investigación.
