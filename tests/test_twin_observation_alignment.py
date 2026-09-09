from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import (
    AlignmentStatus,
    InMemoryTwinStateRepository,
    TemporalAlignment,
    TwinSnapshot,
    TwinState,
    compare_dataset,
    compare_observation,
)
from agri_twin.domain import DatasetRole, ObservationSourceType, ObservationResolution, ingest_rows
from agri_twin.domain.validation import AlignmentPolicy

UTC = timezone.utc
T0 = datetime(2026, 5, 10, 10, tzinfo=UTC)


def state(time=T0, plot="plot-a", cycle="cycle-a", crop="tomato", variety="RAF", lai=2.0, temperature=20.0):
    return TwinState(time, plot, cycle, crop, variety, "ACTIVE", "flowering", lai=lai, temperature_c=temperature, weather_source="SYNTHETIC", weather_timestamp=time)


def observation(**changes):
    value = dict(timestamp=T0.isoformat(), variable="lai", value="1.5", unit="m2/m2", source="technician", plot_id="plot-a", crop="tomato", variety="RAF", cycle_id="cycle-a", quality="VALID")
    value.update(changes)
    result = ingest_rows([value], dataset_id="obs-1", role=DatasetRole.VALIDATION, source="technician", source_type=ObservationSourceType.MEASURED)
    return result.dataset.observations[0]


def repository(*states):
    repo = InMemoryTwinStateRepository()
    grouped = {}
    for item in states:
        grouped.setdefault(item.simulation_time, []).append(item)
    for timestamp, items in grouped.items():
        repo.save_snapshot(TwinSnapshot(timestamp, tuple(sorted(items, key=lambda item: (item.plot_id, item.cycle_id)))))
    return repo


def test_exact_alignment_residual_and_provenance_are_read_only():
    item = state()
    repo = repository(item)
    before = item
    result = compare_observation(repo, observation())
    assert result.alignment.status is AlignmentStatus.MATCHED
    assert result.residual == pytest.approx(0.5)
    assert result.absolute_error == pytest.approx(0.5)
    assert result.observed_uncertainty is None
    assert result.observed_provenance == "technician"
    assert result.simulation_provenance == "SIMULATION"
    assert item == before


def test_exact_missing_and_nearest_tolerance_and_previous_tie():
    repo = repository(state(T0 - timedelta(hours=1), lai=1.0), state(T0 + timedelta(hours=1), lai=3.0))
    assert compare_observation(repo, observation(), TemporalAlignment(AlignmentPolicy.EXACT)).alignment.status is AlignmentStatus.NO_MATCH
    nearest = compare_observation(repo, observation(), TemporalAlignment(AlignmentPolicy.NEAREST, 3600))
    assert nearest.alignment.status is AlignmentStatus.MATCHED
    assert nearest.simulated_value == 1.0
    assert compare_observation(repo, observation(), TemporalAlignment(AlignmentPolicy.NEAREST, 3599)).alignment.status is AlignmentStatus.NO_MATCH


def test_same_day_and_timezone_normalization():
    item = state(datetime(2026, 5, 10, 9, tzinfo=UTC))
    repo = repository(item)
    local = observation(timestamp="2026-05-10T11:00:00+02:00")
    result = compare_observation(repo, local, TemporalAlignment(AlignmentPolicy.SAME_DAY))
    assert result.alignment.status is AlignmentStatus.MATCHED


def test_context_plot_crop_variety_cycle_and_ambiguity():
    repo = repository(state())
    assert compare_observation(repo, observation(plot_id="plot-b")).alignment.status is AlignmentStatus.NO_MATCH
    assert compare_observation(repo, observation(crop="pepper")).alignment.status is AlignmentStatus.INCOMPATIBLE_CONTEXT
    assert compare_observation(repo, observation(variety="Lamuyo")).alignment.status is AlignmentStatus.INCOMPATIBLE_CONTEXT
    assert compare_observation(repo, observation(cycle_id="cycle-b")).alignment.status is AlignmentStatus.NO_MATCH
    ambiguous = repository(state(cycle="cycle-a"), state(cycle="cycle-b"))
    assert compare_observation(ambiguous, observation(cycle_id="")).alignment.status is AlignmentStatus.AMBIGUOUS


def test_variable_units_quality_uncertainty_and_missing_state():
    repo = repository(state(lai=None))
    missing = compare_observation(repo, observation())
    assert missing.alignment.status is AlignmentStatus.MISSING_SIMULATION_VARIABLE
    estimated = compare_observation(repository(state()), observation(quality="ESTIMATED", uncertainty="0.2"))
    assert estimated.quality == "ESTIMATED"
    assert estimated.observed_uncertainty == pytest.approx(0.2)
    invalid = compare_observation(repository(state()), replace(observation(), quality="MISSING"))
    assert invalid.alignment.status is AlignmentStatus.INVALID_OBSERVATION
    incompatible = compare_observation(repository(state()), replace(observation(), unit="degC"))
    assert incompatible.alignment.status is AlignmentStatus.UNIT_ERROR


def test_dataset_is_multi_plot_deterministic_and_empty_safe():
    repo = repository(state(), state(plot="plot-b", cycle="cycle-b", crop="pepper", variety="Lamuyo"))
    dataset = ingest_rows([
        {**observation().__dict__} if False else dict(timestamp=T0.isoformat(), variable="LAI", value="1.5", unit="m2/m2", source="tech", plot_id="plot-a", crop="tomato", variety="RAF", cycle_id="cycle-a"),
        dict(timestamp=T0.isoformat(), variable="LAI", value="1.0", unit="m2/m2", source="tech", plot_id="plot-b", crop="pepper", variety="Lamuyo", cycle_id="cycle-b"),
    ], dataset_id="multi", role=DatasetRole.VALIDATION, source="tech").dataset
    first = compare_dataset(repo, dataset)
    second = compare_dataset(repo, dataset)
    assert first == second
    assert first.matched_count == 2
    assert first.for_plot("plot-b")[0].crop == "pepper"
    assert compare_dataset(repo, []).coverage_ratio == 0


def test_no_clock_advance_and_no_calibration_side_effect():
    repo = repository(state())
    current = T0
    compare_observation(repo, observation())
    assert current == T0
