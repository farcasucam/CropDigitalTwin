"""Typed farm and plot configuration loaded without side effects."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class FarmConfigurationError(ValueError):
    """Raised when farm or plot configuration is invalid."""


@dataclass(frozen=True, slots=True)
class PlotLocation:
    latitude: float
    longitude: float
    elevation_m: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise FarmConfigurationError("latitude must be between -90 and 90")
        if not math.isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise FarmConfigurationError("longitude must be between -180 and 180")
        if self.elevation_m is not None and not math.isfinite(self.elevation_m):
            raise FarmConfigurationError("elevation_m must be finite")


@dataclass(frozen=True, slots=True)
class Plot:
    plot_id: str
    farm_name: str
    name: str
    plot_code: str
    area_ha: float
    location: PlotLocation
    crop_key: str
    variety: str
    current_stage: str
    soil_type: str
    irrigation_type: str
    station_id: str

    @property
    def initial_stage(self) -> str:
        return self.current_stage

    @property
    def latitude(self) -> float:
        return self.location.latitude

    @property
    def longitude(self) -> float:
        return self.location.longitude

    @property
    def elevation(self) -> float | None:
        return self.location.elevation_m

    def __post_init__(self) -> None:
        if not self.plot_id or not self.crop_key or not self.current_stage:
            raise FarmConfigurationError("plot_id, crop_key and current_stage are required")
        if self.area_ha <= 0 or not math.isfinite(self.area_ha):
            raise FarmConfigurationError("area_ha must be positive and finite")


class FarmConfigRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FarmConfigurationError("farm configuration is invalid") from exc
        raw_plots = payload.get("plots") if isinstance(payload, Mapping) else None
        if not isinstance(raw_plots, list):
            raise FarmConfigurationError("farm configuration must contain a plots list")
        self._plots: dict[str, Plot] = {}
        for raw in raw_plots:
            if not isinstance(raw, Mapping):
                raise FarmConfigurationError("plot configuration must be an object")
            try:
                coordinates = raw["coordinates"]
                plot = Plot(
                    plot_id=str(raw["id"]),
                    farm_name=str(raw["farm_name"]),
                    name=str(raw.get("name", raw["id"])),
                    plot_code=str(raw.get("plot_code", raw["id"])),
                    area_ha=float(raw["area_ha"]),
                    location=PlotLocation(
                        latitude=float(coordinates["latitude"]),
                        longitude=float(coordinates["longitude"]),
                        elevation_m=(float(coordinates["elevation_m"]) if coordinates.get("elevation_m") is not None else None),
                    ),
                    crop_key=str(raw["crop_key"]),
                    variety=str(raw.get("crop_variety", raw.get("variety", ""))),
                    current_stage=str(raw["current_stage"]),
                    soil_type=str(raw.get("soil_type", "")),
                    irrigation_type=str(raw.get("irrigation_type", "")),
                    station_id=str(raw.get("station_id", "")),
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise FarmConfigurationError("plot configuration is invalid") from exc
            if plot.plot_id in self._plots:
                raise FarmConfigurationError(f"duplicate plot: {plot.plot_id}")
            self._plots[plot.plot_id] = plot

    def get_plot(self, plot_id: str) -> Plot:
        try:
            return self._plots[plot_id]
        except KeyError as exc:
            raise FarmConfigurationError(f"plot not found: {plot_id}") from exc

    @property
    def plots(self) -> tuple[Plot, ...]:
        return tuple(self._plots.values())
