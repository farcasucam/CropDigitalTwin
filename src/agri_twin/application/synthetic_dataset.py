"""Deterministic synthetic reference data for simulation and software tests.

Synthetic observations are deliberately separate from weather forcing and from
real agricultural observations. The generator never uses wall-clock time.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from agri_twin.domain.calibration import DatasetRole, ObservationDataset
from agri_twin.domain.observation_ingestion import ObservationSourceType, ingest_rows
from agri_twin.domain.models import WeatherState

UTC = timezone.utc


class SyntheticDatasetError(ValueError):
    """Raised when synthetic dataset configuration is invalid."""


@dataclass(frozen=True, slots=True)
class SyntheticPlot:
    plot_id: str
    crop: str
    variety: str
    campaign: int
    environment: str = "outdoor"
    surface_m2: float = 1000.0
    soil_type: str = "loam"
    irrigation_type: str = "drip"
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True, slots=True)
class SyntheticCropCycle:
    crop_cycle_id: str
    plot_id: str
    crop: str
    variety: str
    planting_date: date | None
    transplant_date: date | None
    harvest_start: date | None
    harvest_end: date | None
    cycle_type: str
    perennial: bool = False

    def status_at(self, instant: datetime) -> str:
        current = instant.astimezone(UTC).date()
        if self.planting_date is not None and current < self.planting_date:
            return "NOT_PLANTED"
        if self.harvest_end is not None and current > self.harvest_end:
            return "POST_HARVEST" if self.perennial else "HARVESTED"
        if self.perennial and self.planting_date is None:
            return "DORMANCY" if current.month in {1, 2, 12} else "ACTIVE"
        return "ACTIVE"


@dataclass(frozen=True, slots=True)
class SyntheticReferenceDataset:
    simulation_start: datetime
    simulation_end: datetime
    seed: int
    plots: tuple[SyntheticPlot, ...]
    crop_cycles: tuple[SyntheticCropCycle, ...]
    weather: tuple[Mapping[str, Any], ...]
    observations: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any]

    @property
    def source(self) -> str:
        return "SYNTHETIC"

    @property
    def observation_source_type(self) -> ObservationSourceType:
        return ObservationSourceType.SYNTHETIC_TEST

    def observation_dataset(self, role: DatasetRole = DatasetRole.TEST) -> ObservationDataset:
        result = ingest_rows(
            self.observations,
            dataset_id=f"synthetic-phase5-9-{self.seed}",
            role=role,
            source="synthetic_phase5_9_reference",
            source_type=ObservationSourceType.SYNTHETIC_TEST,
        )
        if result.dataset is None or result.readiness.n_invalid:
            raise SyntheticDatasetError(f"generated observations are not ingestible: {result.qc}")
        return result.dataset

    def write_csv(self, directory: str | Path) -> Path:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        _write_rows(target / "plots.csv", self.plots, (
            "plot_id", "crop", "variety", "campaign", "environment", "surface_m2",
            "soil_type", "irrigation_type", "latitude", "longitude",
        ))
        _write_rows(target / "crop_cycles.csv", self.crop_cycles, (
            "crop_cycle_id", "plot_id", "crop", "variety", "planting_date",
            "transplant_date", "initial_phase", "expected_harvest_date",
            "actual_harvest_start", "actual_harvest_end", "cycle_type", "perennial",
        ), cycle=True)
        _write_dict_rows(target / "weather.csv", self.weather)
        for name in (
            "microclimate", "soil_water", "irrigation", "phenology", "lai",
            "biomass", "fruit_growth", "harvest",
        ):
            _write_dict_rows(target / f"{name}.csv", [row for row in self.observations if row["dataset"] == name])
        (target / "metadata.json").write_text(
            json.dumps(self.metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return target


class SyntheticReferenceDatasetGenerator:
    """Generate reproducible forcing and test observations for a fixed window."""

    DEFAULT_PLOTS = (
        SyntheticPlot("plot_12010", "tomato", "RAF", 2026, "greenhouse", 500.0),
        SyntheticPlot("plot_40811", "pepper", "Lamuyo", 2026, "outdoor", 2500.0),
        SyntheticPlot("plot_30412", "grape", "Monastrell", 2026, "outdoor", 1800.0),
        SyntheticPlot("plot_14705", "plum", "Suplum 26", 2026, "outdoor", 1200.0),
        SyntheticPlot("plot_20500", "lettuce", "", 2026, "greenhouse", 300.0),
        SyntheticPlot("plot_61200", "peach", "", 2026, "outdoor", 1600.0),
        SyntheticPlot("plot_72300", "apple", "", 2026, "outdoor", 1700.0),
    )

    def generate(
        self,
        start: datetime | date,
        end: datetime | date,
        seed: int = 5901,
        plots: Iterable[SyntheticPlot] | None = None,
    ) -> SyntheticReferenceDataset:
        simulation_start = _as_utc(start)
        simulation_end = _as_utc(end)
        if simulation_end < simulation_start:
            raise SyntheticDatasetError("end must not precede start")
        selected = tuple(plots or self.DEFAULT_PLOTS)
        if not selected:
            raise SyntheticDatasetError("at least one plot is required")
        if len({plot.plot_id for plot in selected}) != len(selected):
            raise SyntheticDatasetError("plot_id values must be unique")
        cycles = self._cycles(selected)
        weather = tuple(self._weather(simulation_start, simulation_end, seed))
        observations = tuple(self._observations(simulation_start, simulation_end, seed, selected, cycles))
        metadata = {
            "dataset": "phase5_9_synthetic_reference",
            "seed": seed,
            "simulation_start": simulation_start.isoformat(),
            "simulation_end": simulation_end.isoformat(),
            "weather_source": "SYNTHETIC",
            "observation_source": "SYNTHETIC_TEST",
            "observation_policy": "software_testing_and_demonstration_only",
            "real_agronomic_data": False,
        }
        return SyntheticReferenceDataset(simulation_start, simulation_end, seed, selected, cycles, weather, observations, metadata)

    @staticmethod
    def _cycles(plots: tuple[SyntheticPlot, ...]) -> tuple[SyntheticCropCycle, ...]:
        result: list[SyntheticCropCycle] = []
        for plot in plots:
            if plot.crop == "lettuce":
                result.extend((
                    SyntheticCropCycle("lettuce_001", plot.plot_id, "lettuce", "", date(2026, 1, 10), None, date(2026, 2, 20), date(2026, 2, 20), "short_cycle"),
                    SyntheticCropCycle("lettuce_002", plot.plot_id, "lettuce", "", date(2026, 3, 1), None, date(2026, 4, 10), date(2026, 4, 10), "short_cycle"),
                ))
            elif plot.crop == "tomato":
                result.append(SyntheticCropCycle("tomato_12010_2026", plot.plot_id, plot.crop, plot.variety, date(2026, 2, 15), date(2026, 2, 15), date(2026, 7, 20), date(2026, 7, 20), "annual"))
            elif plot.crop == "pepper":
                result.append(SyntheticCropCycle("pepper_40811_2026", plot.plot_id, plot.crop, plot.variety, date(2026, 3, 1), date(2026, 3, 15), date(2026, 7, 12), date(2026, 9, 10), "annual"))
            elif plot.crop == "grape":
                result.append(SyntheticCropCycle("grape_30412_2026", plot.plot_id, plot.crop, plot.variety, None, None, date(2026, 8, 1), date(2026, 11, 15), "perennial", True))
            elif plot.crop == "plum":
                result.append(SyntheticCropCycle("plum_14705_2026", plot.plot_id, plot.crop, plot.variety, None, None, date(2026, 7, 15), date(2026, 8, 30), "perennial", True))
            else:
                result.append(SyntheticCropCycle(f"{plot.crop}_{plot.plot_id}_{plot.campaign}", plot.plot_id, plot.crop, plot.variety, date(2026, 2, 1), None, date(2026, 8, 15), date(2026, 9, 30), "perennial", True))
        return tuple(result)

    @staticmethod
    def _weather(start: datetime, end: datetime, seed: int) -> Iterable[dict[str, Any]]:
        current = start.replace(minute=0, second=0, microsecond=0)
        random_source = random.Random(seed)
        while current <= end:
            hour = current.hour + current.minute / 60
            daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.0
            seasonal = math.sin(2 * math.pi * (current.timetuple().tm_yday - 80) / 365)
            yield {
                "timestamp": current.isoformat(), "temperature_c": round(18 + 9 * seasonal + 5 * math.sin(2 * math.pi * (hour - 8) / 24), 3),
                "relative_humidity_pct": round(72 - 18 * daylight + random_source.uniform(-2, 2), 3),
                "solar_radiation_w_m2": round(850 * daylight, 3), "wind_speed_m_s": round(1.5 + random_source.random(), 3),
                "wind_direction_deg": 180.0, "rain_rate_mm_h": 0.0, "pressure_hpa": 1013.0,
                "source": "SYNTHETIC", "forcing_type": "SIMULATION_FORCING",
            }
            current += timedelta(hours=1)

    def _observations(self, start: datetime, end: datetime, seed: int, plots: tuple[SyntheticPlot, ...], cycles: tuple[SyntheticCropCycle, ...]) -> Iterable[dict[str, Any]]:
        random_source = random.Random(seed)
        current = start.replace(hour=9, minute=0, second=0, microsecond=0)
        while current <= end:
            for cycle in cycles:
                status = cycle.status_at(current)
                if status not in {"ACTIVE", "POST_HARVEST"}:
                    continue
                progress = self._progress(cycle, current)
                plot = next(plot for plot in plots if plot.plot_id == cycle.plot_id)
                lai = round(max(0.05, 0.3 + 3.0 * math.sin(math.pi * progress)), 3)
                biomass = round(30 + 650 * progress * (1 - 0.2 * progress) + random_source.uniform(-2, 2), 3)
                common = {"timestamp": current.isoformat(), "plot_id": plot.plot_id, "crop": plot.crop, "variety": plot.variety, "environment": plot.environment.upper(), "source": "SYNTHETIC_TEST", "quality": "VALID", "measurement_method": "synthetic_model", "source_type": "synthetic_test_data"}
                for dataset, variable, value, unit in (("lai", "lai", lai, "m2/m2"), ("biomass", "biomass", biomass, "g/m2"), ("soil_water", "soil_water_content", round(0.25 + 0.04 * math.sin(progress * math.pi), 3), "m3/m3")):
                    yield {**common, "dataset": dataset, "variable": variable, "value": value, "unit": unit, "crop_cycle_id": cycle.crop_cycle_id}
                if plot.crop not in {"lettuce"}:
                    yield {**common, "dataset": "phenology", "variable": "maturity", "value": current.date().isoformat(), "unit": "date", "resolution": "event", "observation_type": "event", "crop_cycle_id": cycle.crop_cycle_id}
            current += timedelta(days=7)

    @staticmethod
    def _progress(cycle: SyntheticCropCycle, instant: datetime) -> float:
        if cycle.planting_date is None:
            return min(1.0, max(0.0, (instant.timetuple().tm_yday - 60) / 240))
        total = max(1, ((cycle.harvest_end or cycle.planting_date) - cycle.planting_date).days)
        return min(1.0, max(0.0, (instant.date() - cycle.planting_date).days / total))


def _as_utc(value: datetime | date) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=UTC)
    assert isinstance(value, datetime)
    if value.tzinfo is None:
        raise SyntheticDatasetError("simulation dates must be timezone-aware")
    return value.astimezone(UTC)


def _write_rows(path: Path, rows: Iterable[Any], columns: tuple[str, ...], cycle: bool = False) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for item in rows:
            if cycle:
                row = {"crop_cycle_id": item.crop_cycle_id, "plot_id": item.plot_id, "crop": item.crop, "variety": item.variety, "planting_date": item.planting_date, "transplant_date": item.transplant_date, "initial_phase": "DORMANCY" if item.perennial else "PLANTED", "expected_harvest_date": item.harvest_start, "actual_harvest_start": item.harvest_start, "actual_harvest_end": item.harvest_end, "cycle_type": item.cycle_type, "perennial": item.perennial}
            else:
                row = {column: getattr(item, column) for column in columns}
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def _write_dict_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = tuple(rows)
    columns = tuple(sorted({key for row in rows for key in row}))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


__all__ = ["SyntheticCropCycle", "SyntheticDatasetError", "SyntheticPlot", "SyntheticReferenceDataset", "SyntheticReferenceDatasetGenerator"]
