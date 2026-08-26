# Contratos JSON

## Envelope

Todos los mensajes:

```json
{
  "schema_version": "1.0",
  "message_id": "uuid",
  "correlation_id": "uuid",
  "simulation_id": "sim-001",
  "plot_id": "plot-001",
  "timestamp": "2026-08-26T20:00:01Z",
  "simulation_time": "2026-08-27T08:00:00",
  "type": "weather",
  "source": "weather-engine",
  "data": {}
}
```

## Weather

```json
{
  "temperature_c": 31.2,
  "relative_humidity_pct": 42.0,
  "solar_radiation_w_m2": 820.0,
  "wind_speed_m_s": 3.2,
  "wind_direction_deg": 180,
  "rain_rate_mm_h": 0,
  "pressure_hpa": 1012
}
```

## Actuator command

```json
{
  "target": "windows",
  "command": "set_position",
  "value": 0.8,
  "source": "controller"
}
```

## Natural event

```json
{
  "type": "heatwave",
  "start_time": "2026-08-27T12:00:00",
  "duration_seconds": 21600,
  "parameters": {
    "temperature_c": 40
  }
}
```

## Actuator state

```json
{
  "actuator": "hvac",
  "commanded_value": 0.8,
  "actual_value": 0.4,
  "enabled": true,
  "failed": false
}
```

## SemanticContextPacket

```json
{
  "schema_version": "1.0",
  "simulation_id": "sim-001",
  "plot_id": "plot-001",
  "simulation_time": "2026-08-27T14:00:00",
  "severity": "warning",
  "facts": [
    {
      "id": "f-1",
      "kind": "observed",
      "metric": "indoor_temperature_c",
      "value": 34.2,
      "unit": "degC"
    }
  ],
  "derived_metrics": [],
  "events": [],
  "actuator_observations": [],
  "crop_assessment": {},
  "causal_chain": [],
  "narrative": "...",
  "evidence_refs": []
}
```

## Compatibilidad

Los consumidores deben ignorar campos desconocidos y validar `schema_version`.
