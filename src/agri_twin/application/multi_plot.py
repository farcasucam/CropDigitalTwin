"""Single-clock temporal execution for independent crop cycles and plots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Callable, Iterable, Mapping

from agri_twin.application.clock import SimulationClock
from agri_twin.application.providers import WeatherProvider
from agri_twin.application.scheduler import SimulationScheduler
from agri_twin.application.synthetic_dataset import SyntheticCropCycle, SyntheticPlot
from agri_twin.domain.models import WeatherState
from agri_twin.application.twin_state import (
    InMemoryTwinStateRepository,
    TwinSnapshot,
    TwinState,
    TwinStateRepository,
)


class CropCycleStatus(StrEnum):
    PLANNED = "PLANNED"
    PRE_PLANTING = "PRE_PLANTING"
    ACTIVE = "ACTIVE"
    HARVEST_READY = "HARVEST_READY"
    HARVESTED = "HARVESTED"
    POST_HARVEST = "POST_HARVEST"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class CropCycleState:
    cycle_id: str
    plot_id: str
    crop: str
    variety: str
    status: CropCycleStatus
    stage: str
    ticks: int = 0
    accumulated_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class PlotSimulationResult:
    simulation_time: datetime
    plot: SyntheticPlot
    cycle: SyntheticCropCycle | None
    cycle_state: CropCycleState | None
    weather: WeatherState | None
    warnings: tuple[str, ...] = ()

    @property
    def weather_source(self) -> str | None:
        return None


@dataclass(frozen=True, slots=True)
class MultiPlotSimulationResult:
    simulation_time: datetime
    plot_results: tuple[PlotSimulationResult, ...]
    weather_source: str | None

    def for_plot(self, plot_id: str) -> PlotSimulationResult:
        for result in self.plot_results:
            if result.plot.plot_id == plot_id:
                return result
        raise KeyError(plot_id)


CycleStep = Callable[[PlotSimulationResult, float], None]


class MultiPlotSimulation:
    """Resolve and tick many crop cycles from one SimulationClock and Scheduler.

    This class owns lifecycle orchestration only. CropGrowthEngine, phenology,
    greenhouse physics and feedback remain existing injected domain services.
    """

    def __init__(
        self,
        clock: SimulationClock,
        plots: Iterable[SyntheticPlot],
        cycles: Iterable[SyntheticCropCycle],
        weather_provider: WeatherProvider | None = None,
        step_handler: CycleStep | None = None,
        timestep_seconds: float = 3600.0,
        state_repository: TwinStateRepository | None = None,
    ) -> None:
        self.clock = clock
        self.scheduler = SimulationScheduler(clock, timestep_seconds)
        self.plots = tuple(sorted(plots, key=lambda plot: plot.plot_id))
        self.cycles = tuple(sorted(cycles, key=lambda cycle: (cycle.plot_id, cycle.crop_cycle_id)))
        self.weather_provider = weather_provider
        self.step_handler = step_handler
        self.state_repository = state_repository or InMemoryTwinStateRepository()
        self._states: dict[str, CropCycleState] = {}
        self._results: dict[datetime, MultiPlotSimulationResult] = {}
        self.last_result: MultiPlotSimulationResult | None = None
        self._validate_configuration()
        self.scheduler.register("multi-plot-cycle-execution", timestep_seconds, self._tick)

    def active_cycle(self, plot_id: str, simulation_time: datetime | None = None) -> SyntheticCropCycle | None:
        instant = simulation_time or self.clock.now()
        candidates = [cycle for cycle in self.cycles if cycle.plot_id == plot_id and self._status(cycle, instant) in {CropCycleStatus.ACTIVE, CropCycleStatus.HARVEST_READY}]
        return min(candidates, key=lambda cycle: (cycle.planting_date or instant.date(), cycle.crop_cycle_id), default=None)

    def cycle_state(self, plot_id: str, simulation_time: datetime | None = None) -> CropCycleState | None:
        cycle = self.active_cycle(plot_id, simulation_time)
        if cycle is None:
            return None
        return self._state_for(cycle, simulation_time or self.clock.now())

    def resolve_active_cycles(self, simulation_time: datetime | None = None) -> tuple[SyntheticCropCycle, ...]:
        instant = simulation_time or self.clock.now()
        return tuple(cycle for plot in self.plots if (cycle := self.active_cycle(plot.plot_id, instant)) is not None)

    def advance(self, seconds: float) -> None:
        self.scheduler.advance(seconds)

    def get_state(self, plot_id: str, cycle_id: str, simulation_time: datetime) -> TwinState:
        return self.state_repository.get_exact(plot_id, cycle_id, simulation_time)

    def latest_state(self, plot_id: str, cycle_id: str) -> TwinState | None:
        return self.state_repository.latest(plot_id, cycle_id)

    def history(self, plot_id: str, cycle_id: str | None = None) -> tuple[TwinState, ...]:
        return self.state_repository.history(plot_id, cycle_id)

    def snapshot(self, simulation_time: datetime) -> TwinSnapshot:
        return self.state_repository.snapshot(simulation_time)

    def latest_snapshot(self) -> TwinSnapshot | None:
        return self.state_repository.latest_snapshot()

    def simulate_at(self, simulation_time: datetime) -> MultiPlotSimulationResult:
        if simulation_time.tzinfo is None:
            raise ValueError("simulation_time must be timezone-aware")
        return self._evaluate(simulation_time.astimezone(self.clock.now().tzinfo))

    def _tick(self, timestamp: datetime) -> None:
        self.last_result = self._evaluate(timestamp)

    def _evaluate(self, simulation_time: datetime) -> MultiPlotSimulationResult:
        existing_result = self._results.get(simulation_time)
        if existing_result is not None:
            return existing_result
        results: list[PlotSimulationResult] = []
        candidate_states = dict(self._states)
        snapshot_states: list[TwinState] = []
        source = getattr(self.weather_provider, "source", None) if self.weather_provider is not None else None
        for plot in self.plots:
            cycle = self.active_cycle(plot.plot_id, simulation_time) or self._current_cycle(plot.plot_id, simulation_time)
            weather = self.weather_provider.get(simulation_time) if self.weather_provider is not None else None
            if cycle is None:
                results.append(PlotSimulationResult(simulation_time, plot, None, None, weather, ("NO_ACTIVE_CYCLE",)))
                continue
            status = self._status(cycle, simulation_time)
            state = self._state_for(cycle, simulation_time, candidate_states)
            if status in {CropCycleStatus.ACTIVE, CropCycleStatus.HARVEST_READY}:
                state = replace(state, ticks=state.ticks + 1, accumulated_seconds=state.accumulated_seconds + self.scheduler.timestep.total_seconds())
                candidate_states[cycle.crop_cycle_id] = state
            result = PlotSimulationResult(simulation_time, plot, cycle, state, weather)
            if self.step_handler is not None and status in {CropCycleStatus.ACTIVE, CropCycleStatus.HARVEST_READY}:
                self.step_handler(result, self.scheduler.timestep.total_seconds())
            snapshot_states.append(self._to_twin_state(result, source))
            results.append(result)
        snapshot = TwinSnapshot(simulation_time, tuple(sorted(snapshot_states, key=lambda state: (state.plot_id, state.cycle_id))))
        self.state_repository.save_snapshot(snapshot)
        self._states = candidate_states
        final_result = MultiPlotSimulationResult(simulation_time, tuple(results), source)
        self._results[simulation_time] = final_result
        self.last_result = final_result
        return final_result

    def _current_cycle(self, plot_id: str, instant: datetime) -> SyntheticCropCycle | None:
        candidates = [
            cycle for cycle in self.cycles
            if cycle.plot_id == plot_id and self._status(cycle, instant) in {
                CropCycleStatus.PRE_PLANTING, CropCycleStatus.HARVESTED, CropCycleStatus.POST_HARVEST,
            }
        ]
        return max(candidates, key=lambda cycle: (cycle.planting_date or instant.date(), cycle.crop_cycle_id), default=None)

    def _state_for(self, cycle: SyntheticCropCycle, instant: datetime, states: dict[str, CropCycleState] | None = None) -> CropCycleState:
        states = self._states if states is None else states
        status = self._status(cycle, instant)
        existing = states.get(cycle.crop_cycle_id)
        if existing is not None:
            return replace(existing, status=status, stage=self._stage(status))
        state = CropCycleState(cycle.crop_cycle_id, cycle.plot_id, cycle.crop, cycle.variety, status, self._stage(status))
        states[cycle.crop_cycle_id] = state
        return state

    @staticmethod
    def _to_twin_state(result: PlotSimulationResult, weather_source: str | None) -> TwinState:
        assert result.cycle is not None and result.cycle_state is not None
        weather = result.weather
        return TwinState(
            simulation_time=result.simulation_time,
            plot_id=result.plot.plot_id,
            cycle_id=result.cycle.crop_cycle_id,
            crop=result.cycle.crop,
            variety=result.cycle.variety,
            cycle_status=result.cycle_state.status.value,
            phenological_stage=result.cycle_state.stage,
            temperature_c=weather.temperature_c if weather else None,
            relative_humidity_pct=weather.relative_humidity_pct if weather else None,
            radiation_w_m2=weather.solar_radiation_w_m2 if weather else None,
            weather_source=weather_source,
            weather_timestamp=result.simulation_time if weather else None,
        )

    @staticmethod
    def _stage(status: CropCycleStatus) -> str:
        return {
            CropCycleStatus.PLANNED: "planned",
            CropCycleStatus.PRE_PLANTING: "pre_planting",
            CropCycleStatus.ACTIVE: "active",
            CropCycleStatus.HARVEST_READY: "harvest_ready",
            CropCycleStatus.HARVESTED: "harvested",
            CropCycleStatus.POST_HARVEST: "post_harvest",
            CropCycleStatus.CANCELLED: "cancelled",
        }[status]

    @staticmethod
    def _status(cycle: SyntheticCropCycle, instant: datetime) -> CropCycleStatus:
        current = instant.date()
        if cycle.planting_date is not None and current < cycle.planting_date:
            return CropCycleStatus.PRE_PLANTING
        if cycle.harvest_start is not None and current >= cycle.harvest_start and (cycle.harvest_end is None or current <= cycle.harvest_end):
            return CropCycleStatus.HARVEST_READY
        if cycle.harvest_end is not None and current > cycle.harvest_end:
            return CropCycleStatus.POST_HARVEST if cycle.perennial else CropCycleStatus.HARVESTED
        if cycle.planting_date is None and current.month in {1, 2, 12}:
            return CropCycleStatus.POST_HARVEST
        return CropCycleStatus.ACTIVE

    def _validate_configuration(self) -> None:
        plot_ids = {plot.plot_id for plot in self.plots}
        if len(plot_ids) != len(self.plots):
            raise ValueError("plot_id values must be unique")
        if any(cycle.plot_id not in plot_ids for cycle in self.cycles):
            raise ValueError("every crop cycle must reference a configured plot")
        cycle_ids = [cycle.crop_cycle_id for cycle in self.cycles]
        if len(cycle_ids) != len(set(cycle_ids)):
            raise ValueError("crop_cycle_id values must be unique")


__all__ = [
    "CropCycleState",
    "CropCycleStatus",
    "MultiPlotSimulation",
    "MultiPlotSimulationResult",
    "PlotSimulationResult",
]
