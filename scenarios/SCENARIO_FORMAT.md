# Formato de Escenarios

```json
{
  "scenario_id": "heatwave-demo",
  "version": "1.0",
  "seed": 42,
  "initial_simulation_time": "2026-08-26T06:00:00",
  "duration_seconds": 86400,
  "events": [
    {
      "time": "2026-08-26T12:00:00",
      "type": "heatwave",
      "parameters": {
        "temperature_c": 40,
        "duration_hours": 6
      }
    }
  ]
}
```

Los escenarios deben ser datos, no código Python.
