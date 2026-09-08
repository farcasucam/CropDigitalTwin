from datetime import datetime, timezone

from agri_twin.application import SyntheticReferenceDatasetGenerator
from agri_twin.domain import DatasetRole, ObservationSourceType


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_generator_is_reproducible_and_keeps_forcing_separate():
    generator = SyntheticReferenceDatasetGenerator()
    first = generator.generate(START, END, seed=5901)
    second = generator.generate(START, END, seed=5901)

    assert first == second
    assert first.metadata["weather_source"] == "SYNTHETIC"
    assert first.metadata["observation_source"] == "SYNTHETIC_TEST"
    assert len(first.plots) == 7
    assert len(first.crop_cycles) == 8
    assert {plot.plot_id for plot in first.plots} >= {"plot_12010", "plot_40811", "plot_30412", "plot_14705"}


def test_generator_supports_lifecycle_windows_and_ingestion(tmp_path):
    dataset = SyntheticReferenceDatasetGenerator().generate(START, END, seed=7)
    tomato = next(cycle for cycle in dataset.crop_cycles if cycle.crop == "tomato")
    lettuce = next(cycle for cycle in dataset.crop_cycles if cycle.crop == "lettuce" and cycle.crop_cycle_id == "lettuce_002")
    grape = next(cycle for cycle in dataset.crop_cycles if cycle.crop == "grape")

    assert tomato.status_at(datetime(2026, 1, 1, tzinfo=timezone.utc)) == "NOT_PLANTED"
    assert tomato.status_at(datetime(2026, 6, 1, tzinfo=timezone.utc)) == "ACTIVE"
    assert tomato.status_at(datetime(2026, 8, 1, tzinfo=timezone.utc)) == "HARVESTED"
    assert lettuce.status_at(datetime(2026, 1, 1, tzinfo=timezone.utc)) == "NOT_PLANTED"
    assert grape.status_at(datetime(2026, 12, 1, tzinfo=timezone.utc)) == "POST_HARVEST"

    observations = dataset.observation_dataset(DatasetRole.TEST)
    assert observations.source_type == ObservationSourceType.SYNTHETIC_TEST.value
    assert all(item.source_type == ObservationSourceType.SYNTHETIC_TEST.value for item in observations.observations)

    output = dataset.write_csv(tmp_path)
    assert (output / "weather.csv").exists()
    assert (output / "phenology.csv").exists()
    assert (output / "metadata.json").exists()
