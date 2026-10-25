# Revisión 6.0b: segunda lectura (texto completo de las cuatro obras más cercanas)

Fecha: 2026-10-25. Complementa `SYSTEMATIC_REVIEW_6_0B.md` (primera pasada, solo resúmenes). Contribuciones de referencia: `PUBLICATION_STRATEGY.md` §1 (C1 a C3).

**Advertencia de método.** El texto se obtuvo con WebFetch sobre la versión HTML de arXiv. La herramienta devuelve un extracto procesado por un modelo pequeño, no el texto bruto. Las citas entre comillas son las que devolvió la herramienta; no se contrastaron contra el PDF. Por eso «LEÍDO EN TEXTO COMPLETO» significa «la página HTML completa pasó por la herramienta», con las limitaciones indicadas en cada obra. Sigue siendo una lectura de una sola persona.

| Obra | Estado |
|---|---|
| Won, 2610.08118 | LEÍDO EN TEXTO COMPLETO (secciones 1-8 y apéndices A-B) |
| Yang, Li, Rodríguez, MechSim, 2606.04505 | LEÍDO EN TEXTO COMPLETO, pero solo los primeros 100 000 de 170 328 caracteres (queda sin leer la parte final del apéndice, incluida la tabla de ablación C.6) |
| Gyevnár et al., AXIS, 2505.17801 | LEÍDO EN TEXTO COMPLETO el cuerpo principal (secciones 1-6); los apéndices no estaban en la página |
| DoTime, 2607.27263 | LEÍDO EN TEXTO COMPLETO, salvo los últimos 8 910 de 108 910 caracteres (cola de las referencias) |

## 1. Won (2610.08118) — LEÍDO EN TEXTO COMPLETO

* **Sistemas (§2, Apéndice A).** Sintéticos: retardo de primer orden con retraso, osciladores de 1 y 2 grados de libertad, Duffing, Wiener-Hammerstein y fricción de Coulomb (esta última excluida del ajuste fino). Bouc-Wen solo en prueba. Medidos: Silverbox, Wiener-Hammerstein, Cascaded Tanks y un banco de viga con stick-slip. EMPS se excluye.
* **Umbral o conmutación de régimen: no.** «No se modelan sistemas con conmutación». La fricción de Coulomb incluye una zona muerta de entrada (Apéndice A), y §7 dice que las clases sintéticas carecen de «switching or strongly non-minimum-phase systems».
* **Lazo cerrado: no.** EMPS se describe como «periodic closed-loop tracking experiment», pero se excluye de las pruebas de respuesta a la entrada.
* **Intervenciones (§2, Apéndice A).** Entrada futura escalada por 0,5 y 2, puesta a cero, con un escalón añadido, sustituida por una sinusoide resonante o por una realización nueva. §3 añade un pulso en el paso 8 del horizonte. En registros medidos, la entrada futura se baraja entre ventanas (ganancia por barajado).
* **Afirmación sobre covariables y memoria.** §3: TimesFM-2.5 y TabPFN-TS son «memoryless» por sus interfaces por defecto. Resumen: «the predicted effect of an input change is a same-time function of that change». §6: «a same-time regression cannot carry a delay or a resonance». §1 resume Chronos-2 como un modelo que «identifies the dynamics but attenuates and distorts the response».
* **Atribución o explicaciones: no se evalúan.** Solo se compara el cambio predicho de la salida con el cambio verdadero bajo entradas contrafácticas. §7: los resultados «do not identify the internal mechanism».
* **Decisiones controladas: no se prueban.** §1 se motiva con control basado en modelo, pero no hay controlador en el bucle ni decisiones en lazo cerrado.
* **Consecuencia.** Won confirma el fallo de respuesta ante entradas contrafácticas (parte del mensaje de C2) pero en sistemas forzados, sin umbral, sin lazo cerrado y sin atribución. Su resultado es «atenuación» y «sin memoria»; el nuestro es de un tipo distinto (fallo de signo/efecto por umbral latente de controlador).

## 2. MechSim (2606.04505) — LEÍDO EN TEXTO COMPLETO (parcial, 100 000 de 170 328 caracteres)

* **Uso del simulador: ambos, con más peso en fuente contrafáctica.** §3.2: «MechSim re-executes simulator S_i under alternative configurations of ϕ»; la ec. (1) define la sensibilidad como diferencia de salida esperada entre dos configuraciones; el agente «evaluates whether proposed explanations are empirically supported through controlled interventions on simulator parameters and assumptions». §3.4 exige que las afirmaciones estén «supported by executable verification through sensitivity analysis when available»: la verificación es opcional («cuando esté disponible»).
* **Desajuste simulador-realidad: nombrado, no tratado.** §2 reconoce que las recomendaciones «may depend critically on latent simulator assumptions and their alignment with the deployment environment». §3.2 trata la incertidumbre de parámetros por calibración ABC (distribuciones posteriores). §4.1: la verdad de las políticas viene de un simulador oráculo, así que nunca se contrasta con resultados reales. Solo la tarea de previsión de COVID-19 usa datos reales. No hay métrica de desajuste ni gemelo de verdad distinto del de trabajo.
* **Ablación previsor frente a simulador: no hallada en lo leído.** §5.4 solo ablaciona componentes del pipeline de explicación (razonamiento mecanicista, comprensión de contexto, recuperación de conocimiento). Las líneas base son métodos de razonamiento con LLM. La tabla C.6 quedó truncada: **no verificado**.
* **Niveles de evidencia: no.** §3.1 describe recuperación densa con reordenación; §3.3 dice que la evidencia se referencia explícitamente y que la incertidumbre se representa «when evidence is incomplete, conflicting, or insufficient». No hay jerarquía graduada de calidad de evidencia.
* **Consecuencia.** MechSim usa el simulador como fuente contrafáctica y verificación (cercano a C3), pero su verdad es el propio simulador oráculo, no trata el desajuste y no tiene niveles ni ablación frente a un previsor. No son series temporales de un sistema físico con controlador.

## 3. AXIS (2505.17801) — LEÍDO EN TEXTO COMPLETO (cuerpo principal; sin apéndices)

* **Simulador como oráculo contrafáctico: sí.** §3: el LLM propone intervenciones y se «forward-simulat[es] the counterfactual system to observe whether the query still occurs». §3: «the main assumption of AXIS is the existence of a simulator». §4: el simulador se basa en IGP2 (Albrecht et al., 2021), con vehículos que planifican con A* o MCTS. Dominio: conducción autónoma multiagente.
* **Error del simulador: no tratado.** El texto no analiza cuánto pueden divergir los contrafácticos del sistema real; solo menciona que un modelo «could be learned» o construirse con planificadores si faltan datos. Las limitaciones de §6.2 son cuatro (LLM como juez, fragilidad multi-turno, disponibilidad de líneas base, escalado), ninguna sobre la fidelidad del simulador. La «robustness to variations» de §4 es sobre hiperparámetros y elección de LLM.
* **Verificación determinista: no.** Las explicaciones no se comprueban contra las salidas del simulador; corrección y preferencia las puntúa un LLM juez (§4), con sesgo del juez reconocido (§5.2, §6.2). No se discute el efecto de la estocasticidad ni de las semillas.
* **Consecuencia.** AXIS fija el antecedente «LLM más simulador contrafáctico», pero sin desajuste, sin verificador determinista y con juez LLM: justo lo que C3 añade.

## 4. DoTime (2607.27263) — LEÍDO EN TEXTO COMPLETO (salvo cola de referencias)

* **¿Evalúa algún método XAI frente a su verdad interventiva? No.** El artículo no menciona XAI, atribución ni métodos de explicación. Los métodos evaluados (§6.2): líneas base heurísticas y de series (Zero, TrajMean, AR1, VAR), estimadores causales clásicos (BackDoorOLS, IV2SLS), redes ajustadas a priori (Do-Over-Time-PFN, entrenada con intervenciones u observacional) y un oráculo que «reads off the released ground-truth target».
* Lo más parecido a interpretabilidad es la Figura 7 (Apéndice E): densidad predictiva frente a distribución interventiva condicional verdadera en un solo SCM por estructura, descrita como «a qualitative single-SCM illustration, not an aggregate». Evalúa distribuciones predichas, no atribuciones.
* **Lo que esta lectura no confirma:** no se extrajo qué sistemas incluye (SCM sintéticos frente a simulador físico), ni si tiene lazo cerrado o controlador. La primera pasada decía que incluye regímenes conmutados (solo resumen). Si DoTime tiene controlador con histéresis, C1 y C2 deben releerse: **no verificado**.

## 5. Declaración de novedad revisada

**C1 (banco con verdad interventiva).** Debilitada en generación, intacta en uso. DoTime da verdad interventiva exacta pero no evalúa ningún método XAI contra ella (lectura completa). xaitimesynth y Ismail et al. dan verdad por rasgo (primera pasada, solo resumen). Formulación defendible: «primer banco que evalúa **atribución/explicación** de series temporales frente a efectos interventivos medidos con pares de ejecuciones de un simulador físico multivariante con controlador». Ligar la afirmación a «según nuestra búsqueda», no a «no existe». Citar DoTime como el trabajo más cercano en generación de verdad.

**C2 (fallo de previsores con mecanismo de umbral latente en lazo cerrado).** La novedad **sube** respecto a la primera pasada. Won lo confirma parcialmente (fallo ante entradas contrafácticas, atenuación, TimesFM sin memoria) pero en sistemas forzados sin umbral, sin conmutación, sin lazo cerrado y sin decisiones controladas ni atribución (lectura completa; §7 declara la ausencia de conmutación). Por tanto, el hallazgo genérico «los modelos de fundación no reproducen contrafácticos» **no es novedoso**; lo novedoso es el mecanismo (umbral latente, controlador, historia que no lo excita) y el tipo de consulta (efecto de una **decisión controlada**). Won pasa de «competidor» a «antecedente que acota el terreno». Citarlo y comparar atenuación (0,33-0,80 en Chronos-2 según la primera pasada, no releído aquí) con nuestro signo 0,64.

**C3 (pipeline con evidencia por niveles, simulador imperfecto, verificador determinista, ablación).** La novedad **se mantiene o sube**. Tres cercanos leídos: AXIS (sin error del simulador, sin verificación determinista, juez LLM), MechSim (simulador oráculo como verdad, desajuste solo nombrado, sin niveles de evidencia, sin ablación previsor/simulador en lo leído) y Zhang et al. (primera pasada). Ninguno tiene: (a) gemelo de verdad distinto del gemelo de trabajo con parámetros perturbados, (b) evidencia graduada «dirección confirmada en k de n variantes», (c) ablación previsor frente a gemelo, (d) verificador determinista de cada afirmación. Condición: la tabla C.6 de MechSim no se leyó; si contiene una ablación contra un previsor estadístico, (c) se debilita.

## 6. Qué sigue sin verificar

1. El texto de las tres obras pasó por un extractor automático; las citas literales no se contrastaron con el PDF. Antes de citarlas en el artículo hay que abrirlas.
2. MechSim: últimos 70 328 caracteres (apéndices, tabla C.6 de ablación) sin leer.
3. AXIS: apéndices no disponibles; DoTime: últimos 8 910 caracteres no leídos y su lista exacta de sistemas (¿lazo cerrado, histéresis?) no extraída.
4. Cifras de Won (0,33-0,80, ARX gana en 3 de 4 plantas) proceden de la primera pasada y no se releyeron aquí.
5. Persisten todas las limitaciones de §7 de la primera pasada: sin Scopus/WoS/IEEE/ACM, sin snowballing, una sola lectora, preprints sin revisión por pares verificada. Los resultados negativos de búsqueda no prueban ausencia.
6. Sigue pendiente la lectura de Algometrics (2605.23978), TSQueryBench y Verification Autonomy Levels.
