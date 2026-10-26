# Instrucciones para la revisión experta (fase 6.6)

Qué hay que revisar, por qué y cómo. Lo que no está aquí no necesita revisión de experto. Estado de las cifras y límites: `docs/phase6_6_real_llm.md`.

## Resumen: qué necesita ojos de experto

| # | Qué | Quién | Esfuerzo | Por qué importa |
|---|---|---|---|---|
| 1 | **Auditoría de 52 afirmaciones** (`data/xai/audit/audit_blind.csv`) | 1 revisor, mejor 2 independientes | 1-1,5 h cada uno | Es lo único que mide si el verificador acierta. Hasta hacerla, la precisión del verificador es una lectura mía, no una medida |
| 2 | **Umbrales y convenciones agronómicas** que usa el gemelo al explicar | Agrónomo | 1-2 h | Las explicaciones citan umbrales (p. ej. temperatura mínima de 14 °C, VPD máximo de 1,4 kPa); si no son correctos, todo lo demás lo es sobre una base falsa |
| 3 | **Utilidad de las explicaciones** | Agrónomo u operario | 30-45 min | El verificador solo comprueba coherencia con los hechos, no que lo dicho sea útil o completo |
| 4 | **Criterio sobre errores "con matices"** | Quien dirija la investigación | 15 min | Decide qué cuenta como error (ver el punto 4) |

No se pide a nadie que evalúe los modelos (Qwen, Llama, OLMo): las cifras actuales no sostienen ninguna comparación.

## 1. Auditoría de las 52 afirmaciones

**Material:** `data/xai/audit/audit_blind.csv` (se abre en Excel o LibreOffice, codificación UTF-8). Cada fila es una afirmación escrita por un modelo, con los hechos en los que dice apoyarse.
**No abrir** antes de terminar: `audit_key.csv`, `audit_key_corrected_verifier.csv` y `audit_assistant_firstpass.csv`. Contienen lo que dijo el verificador y mis propios veredictos, y sesgarían la revisión.

**Columnas que se leen:** `text` (la afirmación), `cited_facts` (los hechos que cita, con su redacción exacta; cada uno termina en `[observado]`, `[asociado]`, `[estimado por el modelo]` o `[confirmado por el gemelo]`), `declared_numbers` (los números que el modelo declara aparte).
**Columnas que se rellenan:** `verdict` y `note`.

**Qué se juzga:** solo si la afirmación es coherente **con los hechos que cita**. No se juzga si es cierta en el mundo real, ni si el gemelo es correcto, ni si es útil (eso es el punto 3).

**Niveles de evidencia** (cómo debe leerse cada hecho):
* `observado`: está en los datos. Se puede afirmar que ocurrió.
* `asociado`: coincide en el tiempo con otra cosa. **No** se puede decir que una causó la otra.
* `estimado por el modelo`: lo dice un modelo de previsión. Hay que decirlo como estimación.
* `confirmado por el gemelo`: la **dirección** del efecto se mantuvo en las variantes del simulador. **No** confirma el tamaño ni nada sobre el sistema real.

**Códigos de veredicto** (uno por fila):

| Código | Cuándo |
|---|---|
| `OK` | Coherente con los hechos citados |
| `NUMBER` | Contiene un número que no está en los hechos citados (inventado, calculado, redondeado o de otro hecho) |
| `UNIT` | Unidad equivocada |
| `OVERCLAIM` | Afirma más de lo que da la evidencia: una causa o una confirmación que los hechos no dan, o el tamaño de un efecto dado por confirmado |
| `UNSUPPORTED` | Dice algo que los hechos citados no dicen: dirección invertida, causa inventada aunque sea con "posiblemente", conclusión sin base |
| `OTHER` | Otro problema; describirlo en `note` |

Si una fila tiene varios problemas, se pone el más grave y se anotan los demás en `note`. Si dudas entre `OK` y un error, pon el error y explica la duda en `note`: las dudas son información.
Ejemplos inventados (no son filas de la hoja): "la temperatura sube 2 °C" cuando el hecho dice que baja → `UNSUPPORTED`; "el calor provoca la subida" cuando el hecho es `asociado` → `OVERCLAIM`; "cayó 1,2 °C" cuando el hecho dice 1,13 → `NUMBER`.

**Reglas prácticas:**
* Mira siempre el texto de los hechos citados, no el resto de la hoja.
* Los números pueden venir con coma o con punto decimal; eso no es un error.
* Una afirmación que repite el hecho casi literal es `OK` aunque sea aburrida.
* Anota el tiempo que tardas en la primera y la última fila, para planificar futuras auditorías.

**Cómo devolverlo:** guarda una copia como `audit_blind_<iniciales>.csv` (UTF-8, mismas columnas) y envíala. Si hay dos revisores, trabajan **por separado y sin comentar** las filas hasta terminar. Con las dos hojas se calcula el acuerdo entre revisores (kappa de Cohen), y solo entonces se compara con el verificador.

## 2. Umbrales y convenciones agronómicas

Revisar que lo que el gemelo da por umbral o convención es razonable, y de dónde sale:
* **Umbrales por cultivo y etapa** en `src/crop_config.json`: por ejemplo, tomate en establecimiento: temperatura mínima `min_temp_c` = 14 °C; VPD máximo `stress_max_kpa` = 1,4 kPa. Para cada uno: ¿es el valor correcto? ¿es el nombre de etapa correcto? ¿cuál es la fuente?
* **Convenciones provisionales**, marcadas como tales en los hechos (por ejemplo, considerar "encendido" un actuador por encima del 5 % de su potencia nominal, `src/xai_variable_roles.json`): ¿tienen sentido para un invernadero real?
* Principio del proyecto: **no se inventan valores agronómicos sin fuente trazable**. Si un valor no tiene fuente, el revisor lo marca como "sin fuente" en vez de aceptarlo.

Entrega: una lista con el valor, el veredicto (correcto / dudoso / incorrecto / sin fuente) y la referencia si la hay.

## 3. Utilidad de las explicaciones

Con las afirmaciones del diseño v2 (hasta 6 por escenario, en español e inglés) un agrónomo u operario responde, por escenario:
* ¿Qué le falta que necesitaría saber? ¿Qué le sobra?
* ¿El orden de prioridad (efectos confirmados, previsiones, superaciones de umbral, cambios mayores) es el que seguiría un operario?
* ¿La redacción en español usa los términos correctos del oficio?
* ¿Haría algo distinto por haber leído la explicación? (si la respuesta es no en todos los casos, la explicación no sirve aunque sea correcta)

Material: `data/xai/llm_records_v2_agritwin/` (respuestas crudas) o pedir al equipo una hoja legible por escenario.

## 4. Criterio sobre errores con matices (decisión de investigación)

El revisor del punto 1 aplicará los códigos tal cual; pero hay que decidir **de antemano** cómo contar estos casos, porque cambian las cifras:
* Redondear un número (−0,188 → −0,19): ¿error o aceptable?
* Un número que el modelo deriva (cuenta de muestras entre dos índices): ¿error o aceptable?
* Una hipótesis con "posiblemente" sin hecho detrás: ¿error o aceptable?
* Usar "confirmado" como sinónimo de "observado": ¿error o aceptable?

Recomendación: contarlos como errores **menores**, en una categoría aparte, y no mezclarlos con los sustanciales (número inventado, dirección invertida, causa o confirmación sin base).

## Qué no hay que revisar ahora
La infraestructura (cliente, grabación y reproducción de respuestas, contenedores) está cubierta por pruebas automáticas, y la comparación entre modelos no se puede interpretar con estas muestras.
