"""Initial state boundary for a plot/crop digital twin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from agri_twin.domain.models import CropState, WeatherState


@dataclass(frozen=True, slots=True)
class CropDigitalTwinState:
    plot_id: str
    crop_key: str
    variety: str
    current_stage: str
    timestamp: datetime
    weather_state: WeatherState
    agronomic_state: Mapping[str, Any]
    crop_state: CropState | None = None

    @property
    def initial_stage(self) -> str:
        return self.current_stage
