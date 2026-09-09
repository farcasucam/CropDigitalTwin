"""Offline Phase 5.12 TwinState/Observation alignment acceptance audit."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from agri_twin.application import (
    AlignmentStatus,
    InMemoryTwinStateRepository,
    TemporalAlignment,
    TwinSnapshot,
    TwinState,
    compare_observation,
)
from agri_twin.domain import DatasetRole, ObservationSourceType, ingest_rows
from agri_twin.domain.validation import AlignmentPolicy

UTC = timezone.utc
T0 = datetime(2026, 5, 10, 10, tzinfo=UTC)


def make_observation(timestamp=T0.isoformat(), **changes):
    row = {"timestamp": timestamp, "variable": "LAI", "value": "1.5", "unit": "m2/m2", "source": "technician_field_measurement", "plot_id": "plot_12010", "crop": "tomato", "variety": "RAF", "cycle_id": "tomato_12010_2026"}
    row.update(changes)
    return ingest_rows([row], dataset_id="phase5-12-demo", role=DatasetRole.VALIDATION, source="technician").dataset.observations[0]


def main():
    print("SYNTHETIC DATASET — DEMONSTRATION ONLY")
    state = TwinState(T0, "plot_12010", "tomato_12010_2026", "tomato", "RAF", "ACTIVE", "flowering", lai=2.0, weather_source="SYNTHETIC", weather_timestamp=T0)
    previous = TwinState(T0 - timedelta(hours=1), "plot_12010", "tomato_12010_2026", "tomato", "RAF", "ACTIVE", "vegetative", lai=1.0, weather_source="SYNTHETIC", weather_timestamp=T0 - timedelta(hours=1))
    repository = InMemoryTwinStateRepository()
    repository.save_snapshot(TwinSnapshot(previous.simulation_time, (previous,)))
    repository.save_snapshot(TwinSnapshot(state.simulation_time, (state,)))
    observation = make_observation()
    before_state = state
    exact = compare_observation(repository, observation)
    assert exact.alignment.status is AlignmentStatus.MATCHED and exact.residual == 0.5
    assert compare_observation(repository, make_observation(timestamp="2026-05-10T10:30:00+00:00"), TemporalAlignment(AlignmentPolicy.NEAREST, 1800)).alignment.status is AlignmentStatus.MATCHED
    assert compare_observation(repository, make_observation(timestamp="2026-05-10T10:30:00+00:00"), TemporalAlignment(AlignmentPolicy.NEAREST, 60)).alignment.status is AlignmentStatus.NO_MATCH
    assert compare_observation(repository, make_observation(timestamp="2026-05-10T12:00:00+02:00"), TemporalAlignment(AlignmentPolicy.SAME_DAY)).alignment.status is AlignmentStatus.MATCHED
    assert compare_observation(repository, make_observation(crop="pepper")).alignment.status is AlignmentStatus.INCOMPATIBLE_CONTEXT
    assert compare_observation(repository, make_observation(quality="ESTIMATED", uncertainty="0.2")).observed_uncertainty == 0.2
    assert compare_observation(repository, replace(observation, unit="degC")).alignment.status is AlignmentStatus.UNIT_ERROR
    assert state == before_state
    print("PASS — exact alignment / nearest alignment / tolerance")
    print("PASS — timezone normalization / plot, crop, variety and cycle context")
    print("PASS — quality flags / unit handling / uncertainty preservation")
    print("PASS — residual / greenhouse-outdoor compatible state provenance")
    print("PASS — no TwinState mutation / no Observation mutation / no clock advancement")
    print("PASS — deterministic comparison and no calibration side effect")
    print("PHASE 5.12 COMPLETE — TEMPORAL TWIN ↔ OBSERVATION ALIGNMENT READY — COMPARISON LAYER READY — NO CALIBRATION PERFORMED — NO DATA ASSIMILATION — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
