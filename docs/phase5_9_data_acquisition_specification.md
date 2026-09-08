# Phase 5.9: data acquisition specification

## Interfaces

Simulation forcing enters through `WeatherProvider` and is selected independently of agronomic observations. Supported provenance values are `REAL_WORLD`, `OPEN_METEO`, `SYNTHETIC` and `USER_SCENARIO`. Weather remains a `WeatherState`; it is never implicitly ingested as an agronomic observation.

Real observations enter through `ObservationIngestion.ingest_csv()` or `ingest_rows()`. The existing contract normalizes supported units, requires timezone-aware timestamps, preserves original units and measurement methods, reports quality flags, rejects forcing datasets, and creates `ObservationDataset` only from valid rows.

Synthetic observations use `ObservationSourceType.SYNTHETIC_TEST`, `DatasetRole.TEST` by default, and source `synthetic_phase5_9_reference`. They are suitable for integration tests and demonstrations only. Passing them to calibration or validation APIs does not constitute scientific calibration or experimental validation.

## Generated artifacts

`SyntheticReferenceDataset.write_csv()` emits `plots.csv`, `crop_cycles.csv`, `weather.csv`, `microclimate.csv`, `soil_water.csv`, `irrigation.csv`, `phenology.csv`, `lai.csv`, `biomass.csv`, `fruit_growth.csv`, `harvest.csv` and deterministic `metadata.json`. Empty applicable files retain their headers. The technician templates are separate under `data/templates/agricultural/` and contain no invented measurements.

## Temporal and lifecycle rules

Generation accepts an explicit start and end. It can start before planting, during a cycle, or after harvest. Cycles are independent even when they share a plot. Perennial post-harvest and dormancy states do not delete the crop instance. Generated data does not introduce a second clock.

## Scientific status

The package prepares software verification and future data arrival. It does not claim real agronomic data, calibrated parameters, or experimental validation.
