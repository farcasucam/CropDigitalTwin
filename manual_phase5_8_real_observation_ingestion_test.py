"""Synthetic-only demonstration of Phase 5.8 observation ingestion."""

from agri_twin.domain import DatasetRole, ObservationSourceType, ParameterRegistry, ingest_rows, parameter_readiness, crop_variety_readiness
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    print("SYNTHETIC DATASET — DEMONSTRATION ONLY")
    print("REAL AGRONOMIC DATA AVAILABLE: NO / INSUFFICIENT")
    rows = [
        {"timestamp": "2026-07-01T10:00:00+00:00", "variable": "LAI", "value": "2.0", "unit": "m2 m-2", "source": "synthetic_test_sensor", "plot_id": "plot-12010", "crop": "tomato", "variety": "RAF", "environment": "GREENHOUSE", "measurement_method": "sensor"},
        {"timestamp": "2026-07-01T11:00:00+00:00", "variable": "air_temperature", "value": "25", "unit": "degC", "source": "synthetic_test_sensor", "plot_id": "plot-12010", "crop": "tomato", "variety": "RAF", "environment": "GREENHOUSE", "measurement_method": "sensor"},
        {"timestamp": "2026-07-01T11:00:00+00:00", "variable": "LAI", "value": "2.1", "unit": "m2 m-2", "source": "synthetic_test_sensor", "plot_id": "plot-12010", "crop": "tomato", "variety": "RAF", "environment": "GREENHOUSE", "measurement_method": "sensor"},
        {"timestamp": "2026-07-01T11:00:00+00:00", "variable": "LAI", "value": "2.1", "unit": "m2 m-2", "source": "synthetic_test_sensor", "plot_id": "plot-12010", "crop": "tomato", "variety": "RAF", "environment": "GREENHOUSE", "measurement_method": "sensor"},
        {"timestamp": "2026-07-01T12:00:00+00:00", "variable": "biomass", "value": "NA", "unit": "g/m2", "source": "synthetic_test_sensor", "plot_id": "plot-12010", "crop": "tomato", "variety": "RAF", "environment": "GREENHOUSE", "measurement_method": "manual"},
    ]
    result = ingest_rows(rows, dataset_id="synthetic_phase5_8", role=DatasetRole.VALIDATION, source="synthetic_test_fixture", source_type=ObservationSourceType.SYNTHETIC_TEST)
    print(f"dataset_id={result.dataset.name} source={result.dataset.source}")
    print(f"observations={result.readiness.n_observations} valid={result.readiness.n_valid} invalid={result.readiness.n_invalid} missing={result.readiness.n_missing} duplicates={result.readiness.n_duplicates}")
    print(f"readiness={result.readiness.status.value} variables={result.readiness.n_variables} plots={result.readiness.n_plots}")
    print(f"qc={[issue.quality.value for issue in result.qc]}")
    print(f"linkage={result.dataset.observations[0].plot_id}/{result.dataset.observations[0].crop}/{result.dataset.observations[0].variety}/{result.dataset.observations[0].environment}")
    print("forcing_to_observation=blocked_forcing_is_not_an_observation")
    print("derived_observation=must_be_marked_derived_and_not_independent")
    readiness = parameter_readiness(ParameterRegistry.from_repository(ROOT), result.dataset)
    print(f"parameter_readiness={[ (item.parameter_id, item.status.value) for item in readiness if item.status.value != 'NOT_READY' ]}")
    print(f"crop_variety_readiness={crop_variety_readiness(result.dataset)}")
    print("calibration_validation=compatible ObservationDataset contract; no calibration executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
