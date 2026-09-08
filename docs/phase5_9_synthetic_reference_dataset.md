# Phase 5.9: synthetic reference dataset

`SyntheticReferenceDatasetGenerator` (`agri_twin.application.synthetic_dataset`) genera forcing meteorológico y observaciones sintéticas reproducibles sin depender de datos agronómicos reales ni de la fecha del ordenador.

```python
from datetime import datetime, timezone
from agri_twin.application import SyntheticReferenceDatasetGenerator

reference = SyntheticReferenceDatasetGenerator().generate(
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    datetime(2026, 12, 31, tzinfo=timezone.utc),
    seed=5901,
)
reference.write_csv("data/synthetic/phase5_9")
```

La semilla, ventana temporal, orden y valores son deterministas. El generador devuelve objetos de dominio en memoria; CSV es una salida opcional de referencia. `SimulationClock` sigue siendo la autoridad temporal de una simulación en ejecución.

## Separación de categorías

- `weather`: simulation forcing con `weather_source = SYNTHETIC`.
- LAI, biomasa, fenología, suelo y demás filas: observaciones de software con `observation_source = SYNTHETIC_TEST`.
- Ningún CSV sintético se marca como `measured_data`.
- `observation_dataset()` usa el `ObservationIngestion` existente y devuelve un `ObservationDataset` de rol explícito.

El proveedor sintético, el CSV de estación (`REAL_WORLD`), Open-Meteo (`OPEN_METEO`) y `ScenarioWeatherProvider` (`USER_SCENARIO`) comparten el contrato `WeatherProvider`. Un escenario modifica el forcing y conserva provenance de usuario.

## Cobertura

El dataset incluye las cuatro parcelas configuradas del proyecto, tomate RAF, pimiento Lamuyo, uva Monastrell y ciruela Suplum 26, además de lechuga, melocotón y manzana sin inventar variedades. Incluye dos ciclos independientes de lechuga, cultivos anuales, ciclos cortos y perennes. Cada ciclo conserva su estado `NOT_PLANTED`, `ACTIVE`, `HARVESTED`, `POST_HARVEST` o `DORMANCY` según la fecha consultada.

Los valores son coherentes para verificar software, no evidencia fisiológica ni calibración varietal.
