# Motor de Enriquecimiento y Serialización Semántica

## Objetivo

Traducir señales numéricas, métricas derivadas y eventos del gemelo en una representación semántica estructurada y legible por un LLM, sin perder trazabilidad ni permitir al LLM modificar el estado directamente.

## Posición

```text
MQTT state/events
       ↓
Semantic Enrichment Engine
       ├── metric derivation
       ├── threshold evaluation
       ├── trend detection
       ├── event correlation
       ├── anomaly/context detection
       ├── semantic classification
       └── serialization
       ↓
semantic/context
       ↓
LLM / API / UI
```

## Principios

1. Determinista por defecto.
2. No inventar valores.
3. Cada afirmación debe tener evidencia.
4. Diferenciar `observed`, `derived`, `inferred`.
5. Nunca emitir acciones ejecutables como salida semántica.
6. El LLM recibe contexto, no autoridad.
7. El LLM no es dependencia del simulador.
8. Las narrativas deben poder regenerarse desde datos históricos.

## Pipeline

### 1. Normalización
Validar y normalizar unidades.

### 2. Derivación
Calcular:
- VPD;
- deltas;
- medias;
- máximos;
- mínimos;
- tiempo fuera de rango;
- tasa de cambio;
- tendencia;
- consumo;
- estrés.

### 3. Evaluación contextual
Comparar con:
- thresholds del cultivo;
- fase fenológica;
- configuración de parcela;
- límites del sistema.

### 4. Correlación
Relacionar:
- evento;
- señal;
- actuación;
- consecuencia.

Ejemplo:

```text
heatwave
 -> outdoor_temperature ↑
 -> indoor_temperature ↑
 -> HVAC command ↑
 -> HVAC actual != command
 -> temperature remains high
```

### 5. Clasificación semántica

Categorías:
- `normal`
- `attention`
- `warning`
- `critical`
- `event`
- `recovery`
- `actuator_mismatch`
- `sensor_quality`
- `crop_stress`

### 6. Narrativa

Formato controlado:

```text
La parcela P experimenta estrés térmico moderado.
La temperatura interior alcanzó 34.2 °C durante 25 min.
El umbral crítico configurado para la fase actual es 35 °C.
El HVAC fue solicitado al 80 %, pero su estado real fue 40 %.
```

No afirmar causalidad fuerte si solo existe correlación.

## SemanticContextPacket

Campos mínimos:

```json
{
  "schema_version": "1.0",
  "simulation_id": "...",
  "plot_id": "...",
  "simulation_time": "...",
  "severity": "warning",
  "facts": [],
  "derived_metrics": [],
  "events": [],
  "actuator_observations": [],
  "crop_assessment": {},
  "causal_chain": [],
  "narrative": "...",
  "evidence_refs": []
}
```

## LLM Adapter

Crear interfaz:

```python
class LLMNarrativeProvider(Protocol):
    def generate(self, semantic_packet: SemanticContextPacket) -> str: ...
```

Implementar primero:
- `TemplateNarrativeProvider`.

Preparar posteriormente:
- OpenAI;
- modelos locales;
- otros proveedores.

El proveedor LLM nunca publica comandos de actuadores directamente.

## Seguridad semántica

Separar:
- datos;
- instrucciones;
- narrativa.

Nunca incorporar texto no confiable del entorno dentro de un prompt como instrucciones de sistema.

## Tests

- mismo estado -> mismo packet;
- threshold correctamente clasificado;
- evidencia presente;
- ausencia de datos -> no inventar;
- fallo de LLM no bloquea MQTT;
- causalidad no afirmada sin evidencia.
