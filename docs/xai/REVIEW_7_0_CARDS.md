# Fase 7.0: fichas de lectura (texto completo)

Fecha: 2026-10-27. Sustituye, para estos tres trabajos, el método de las revisiones 6.0b (resúmenes y extractos de una herramienta). **Método:** el PDF se descargó de la fuente (arXiv o la editorial) a un directorio propio, se extrajo su texto completo con `pypdf` y se leyó entero el texto. **Lo que no se leyó:** las figuras y las imágenes; en Weilbach, el apéndice que el propio texto cita («see Appendix») **no está en el PDF v1 descargado**. Una sola persona (el asistente); falta la lectura humana. Que un trabajo no haga X significa que no lo hace *en el texto leído*; no prueba que nadie lo haya hecho.

## 1. Weilbach, Gerwinn, Barsim, Fränzle: *Counterfactual-based Root Cause Analysis for Dynamical Systems*

* **Referencia y versión:** arXiv 2406.08106v1, 12 junio 2024, 17 páginas. El PDF no menciona congreso; el listado de mlanthology lo da como ECML PKDD 2024 (no verificado en el PDF).
* **Problema y objeto explicado:** una trayectoria multivariante defectuosa de un sistema dinámico; se pregunta «¿habría ocurrido el fallo si se hubiera sustituido el comportamiento de un subsistema, en un instante, por su comportamiento normal?». El objeto explicado es el **fallo de la trayectoria**, definido por un clasificador de fallo `φ` conocido.
* **Supuestos (los declara):** datos de comportamiento normal; grafo resumen conocido (de expertos o de datos); `φ` conocido; ruido aditivo (para que el modelo sea invertible); **una sola causa raíz** y **ausencia de variables latentes** (§6, trabajo futuro). La mayor parte de la evaluación se hace con el grafo conocido; hay un experimento con aristas añadidas o quitadas.
* **Acceso al simulador:** **ninguno**. El sistema es un modelo causal dinámico **aprendido** de datos normales (regresión lineal o una ResNet de tres capas, 128 neuronas), del que se abduce el ruido de la trayectoria observada.
* **Controlador y variables ocultas:** no hay controlador ni lazo cerrado en los experimentos. Una intervención «estructural» sustituye la función de transición de un nodo por la aprendida con datos normales (cercana en espíritu a sustituir un comportamiento, no a repetir una trayectoria de órdenes). El experimento del río tiene un confusor no observado (aparece como la causa probable de que el contrafactual no corrija el fallo); no se modela.
* **Definición de intervención:** `do` sobre la distribución del ruido (ec. 1) o sobre la ecuación estructural (ec. 2) de un nodo en un instante; «causa raíz» = intervención que baja la tasa de fallo (def. 4).
* **Métodos y evaluación:** la puntuación de cada intervención es `Sh(ξ) := log E[φ(Y)]` bajo la intervención (ec. 7). **No calcula Shapley:** «ignorando interacciones, sólo se consideran conjuntos de una intervención», justificado por tratabilidad y por la suposición de que causas simultáneas son improbables. Evaluación: precisión de identificar la causa inyectada en un sistema lineal sintético (20 facta), el oscilador FitzHugh–Nagumo, el banco de EasyRCA (30 grafos) y un caso real de caudales de un río **sin verdad de terreno**; los intervalos son ± error estándar de la proporción.
* **Diferencia concreta con el proyecto:**
  1. Nosotros usamos el **simulador mismo** como modelo estructural: no hay modelo aprendido, ni abducción (el gemelo es determinista dada la escenario) ni error de ajuste.
  2. Nosotros **medimos las interacciones** (reparto exacto con pocos jugadores y hueco entre retiradas y contraste); ellos las descartan por diseño. En PT-1 el hueco fue del 6 al 12 % de un contraste en un episodio.
  3. Nosotros tratamos la **política de control** como objeto (contraste con política reactiva frente a actuaciones repetidas); ellos no tienen controlador.
  4. Nuestros jugadores son perturbaciones exógenas con una política fija; sus jugadores son (nodo, instante) y la causa es única.
  5. Ellos explican un **fallo**; nosotros, la contribución a un conjunto de resultados.
  Lo que **comparten** y no podemos presentar como novedad: formular la causa como una consulta contrafactual sobre un modelo causal dinámico y puntuar intervenciones; usar Shapley (ellos lo aproximan) sobre intervenciones.

## 2. Budhathoki, Minorics, Blöbaum, Janzing: *Causal structure-based root cause analysis of outliers*

* **Referencia y versión:** ICML 2022, PMLR 162 (el PDF es la versión actualizada con tres correcciones menores de notación).
* **Problema y objeto:** el valor de una variable objetivo marcado como atípico (*outlier*); cuánto contribuye cada nodo, a través de su ruido, a la puntuación de atipicidad.
* **Supuestos:** A1 grafo causal dirigido acíclico conocido; A2 modelo causal funcional conocido o estimable con ruidos independientes; A3 invertibilidad (se recupera el ruido de cada nodo a partir de su valor y el de sus padres). Variables **estáticas**; discute qué pasa con confusores no observados y con supuestos violados (§3.4, simulaciones).
* **Simulador:** no hay; los modelos son los funcionales supuestos o ajustados. **Controlador:** no. **Variables ocultas:** caso real de ríos con causas comunes no observadas.
* **Intervención:** sustituir el ruido de un nodo por un valor típico (contrafactual por abducción–acción–predicción); la contribución se reparte con **Shapley** sobre los nodos.
* **Diferencia concreta:** es el antecedente del reparto Shapley sobre intervenciones; **estático** (sin trayectoria ni control). Se evaluó con simulaciones (supuestos válidos e inválidos) y un caso real sin verdad de terreno.

## 3. Ng, Lin, Lu, Liu (Amazon): *Who's to blame? Unraveling causal drivers in supply chain simulations with a Shapley value based attribution mechanism using Gaussian process emulator* (SAGE)

* **Referencia y versión:** Proceedings of the 2025 Winter Simulation Conference, pp. 414 y siguientes (el PDF lista los autores en el orden Lu, Lin, Ng, Liu; la cabecera, Ng, Lin, Lu, Liu).
* **Problema y objeto:** comparar las salidas de **dos simulaciones** de un sistema de inventario que difieren en sus entradas y repartir la diferencia de una métrica (inventario objetivo) entre las entradas.
* **Supuestos:** grafo causal de dominio; la función entrada→salida no cambia entre las dos simulaciones; productos simulados independientes.
* **Acceso al simulador:** sí, pero **no se reejecuta**: «idealmente repetiríamos la simulación para cada instancia permutada, pero es computacionalmente intensivo»; se ajusta un **emulador de procesos gaussianos** y se obtiene Shapley en forma cerrada o por Monte Carlo, con un término de error de estimación explícito (ec. 7).
* **Controlador, dinámica temporal, variables ocultas:** no se tratan; las entradas son magnitudes estáticas por semana de destino. Intervención: sustituir los valores de las entradas por los de la otra simulación.
* **Evaluación:** datos sintéticos y reales de la cadena de suministro; la sección de resultados no se examinó con el detalle de las cifras (el texto leído llega hasta la ec. 7 y los apartados de aplicación; **no contrasté sus tablas**).
* **Diferencia concreta:** hacen **justamente lo que PT-1 evita** (reemplazar las ejecuciones por un emulador para ahorrar coste): para pocos jugadores y ejecuciones de 1,4 s, reejecutar es exacto dentro del simulador; para muchos jugadores un emulador es una vía posible, con su error medido, no una ventaja que reclamemos. No hay política de control, ni series temporales, ni simulador de referencia.

## 4. Lectura de novedad (provisional)

* **No se cubre el núcleo del proyecto**, y por tanto no hay que reposicionar antes de 7.3: ningún trabajo leído tiene a la vez simulador reejecutable como modelo, controlador en lazo cerrado como objeto, reparto exacto con interacciones medidas y un simulador de referencia estructuralmente distinto.
* **Afirmaciones que no se pueden hacer:** «contrafactuales con Shapley para causa raíz en sistemas dinámicos» es antecedente conocido (Budhathoki 2022; Weilbach 2024); «Shapley sobre las salidas de un simulador» también (Ng 2025, con emulador). **Lo que sí queda abierto como pregunta (no como resultado):** el efecto de la política de control sobre la atribución (reactiva frente a repetida), cuánto importan las interacciones que Weilbach descarta, y cómo se recuperan (o no) estos efectos con métodos basados en datos.
* **Cambios al plan:** la ficha corrige mi descripción previa de Weilbach (basada en un resumen de búsqueda): su «Shapley aproximado» es la puntuación de intervenciones **individuales**, sin interacciones. PT-2 añade por eso la comparación entre el reparto exacto y la aproximación por intervención individual.
* **Pendiente:** apéndices (Weilbach), tablas de resultados de SAGE, lectura humana, y los demás trabajos de la fase 7.0 (descubrimiento causal temporal, *data-to-text* de series, verificación de gemelos, mediación longitudinal).
