import csv
import json
from datetime import datetime, timezone

import pytest

from agri_twin.application import (
    ScenarioWeatherProvider,
    SyntheticWeatherProvider,
    WeatherTimestampNotAvailable,
)
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import WeatherConfiguration, WeatherEventType, WeatherPerturbation
from agri_twin.infrastructure import CsvWeatherProvider, WeatherDatasetError


T0 = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
HEADER = [
    "timestamp", "temperature_c", "relative_humidity_pct",
    "solar_radiation_w_m2", "wind_speed_m_s", "wind_direction_deg",
    "rain_rate_mm_h", "pressure_hpa",
]


def write_dataset(path, rows=None):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows or [[T0.isoformat(), 25, 50, 820, 2.5, 180, 0, 1012]])


def make_event():
    return WeatherPerturbation(
        event_id="rain-1",
        event_type=WeatherEventType.RAIN,
        start_time=T0,
        end_time=T0.replace(hour=13),
        priority=1,
        source="test",
        parameters={"rate_mm_h": 8},
    )


def test_synthetic_provider_delegates_to_existing_engine():
    engine = WeatherEngine(WeatherConfiguration())
    provider = SyntheticWeatherProvider(engine)
    assert provider.get(T0) == engine.generate(T0)


def test_csv_provider_loads_exact_utc_observation(tmp_path):
    path = tmp_path / "weather.csv"
    write_dataset(path)
    provider = CsvWeatherProvider(path)
    assert provider.get(T0).temperature_c == 25
    assert provider.get(T0) == provider.get(T0)


def test_csv_provider_rejects_missing_timestamp_and_invalid_dataset(tmp_path):
    path = tmp_path / "weather.csv"
    write_dataset(path)
    provider = CsvWeatherProvider(path)
    with pytest.raises(WeatherTimestampNotAvailable):
        provider.get(T0.replace(hour=13))
    empty = tmp_path / "empty.csv"
    empty.write_text(",".join(HEADER) + "\n", encoding="utf-8")
    with pytest.raises(WeatherDatasetError):
        CsvWeatherProvider(empty)


def test_csv_provider_rejects_duplicate_and_non_contiguous_timestamps(tmp_path):
    duplicate = tmp_path / "duplicate.csv"
    write_dataset(duplicate, [
        [T0.isoformat(), 25, 50, 820, 2.5, 180, 0, 1012],
        [T0.isoformat(), 25, 50, 820, 2.5, 180, 0, 1012],
    ])
    with pytest.raises(WeatherDatasetError):
        CsvWeatherProvider(duplicate)

    gap = tmp_path / "gap.csv"
    write_dataset(gap, [
        [T0.isoformat(), 25, 50, 820, 2.5, 180, 0, 1012],
        [(T0.replace(hour=14)).isoformat(), 25, 50, 820, 2.5, 180, 0, 1012],
    ])
    with pytest.raises(WeatherDatasetError):
        CsvWeatherProvider(gap)


def test_csv_provider_preserves_real_night_radiation(tmp_path):
    path = tmp_path / "weather.csv"
    write_dataset(path, [["2026-08-27T18:00:00+00:00", 20, 50, 3.53, 1, 180, 0, 1012]])
    assert CsvWeatherProvider(path).get(datetime(2026, 8, 27, 18, tzinfo=timezone.utc)).solar_radiation_w_m2 == 3.53


def test_scenario_provider_applies_rain_without_mutating_csv(tmp_path):
    path = tmp_path / "weather.csv"
    write_dataset(path)
    reference = CsvWeatherProvider(path)
    scenario = ScenarioWeatherProvider(reference)
    scenario.add_perturbation(make_event())

    assert reference.get(T0).rain_rate_mm_h == 0
    assert scenario.get(T0).rain_rate_mm_h == 8
    assert reference.get(T0).rain_rate_mm_h == 0
    scenario.reset()
    assert scenario.get(T0).rain_rate_mm_h == 0
