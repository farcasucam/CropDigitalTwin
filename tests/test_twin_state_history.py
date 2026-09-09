from datetime import date, datetime, timedelta, timezone

import pytest

from agri_twin.application import (
    CropCycleStatus,
    InMemoryTwinStateRepository,
    MultiPlotSimulation,
    SyntheticCropCycle,
    SyntheticPlot,
    TwinSnapshot,
    TwinState,
    TwinStateConflict,
    SimulationClock,
)
from agri_twin.domain import WeatherState


UTC = timezone.utc
T0 = datetime(2026, 12, 31, 23, tzinfo=UTC)


class FixedWeather:
    source = "SYNTHETIC"

    def get(self, simulation_time):
        return WeatherState(20, 60, 300, 1, 90, 0, 1013)


def make_state(timestamp=T0, cycle_id="cycle-a", plot_id="plot-a", lai=1.2):
    return TwinState(timestamp, plot_id, cycle_id, "tomato", "RAF", "ACTIVE", "active", lai=lai, weather_source="SYNTHETIC", weather_timestamp=timestamp)


def make_cycle(cycle_id, plot_id, planting, harvest, crop="lettuce", variety=""):
    return SyntheticCropCycle(cycle_id, plot_id, crop, variety, planting, None, harvest, harvest, "short_cycle")


def test_repository_serialization_queries_and_idempotent_duplicate_policy():
    repository = InMemoryTwinStateRepository()
    state = make_state()
    assert TwinState.from_dict(state.to_dict()) == state
    repository.save(state)
    repository.save(state)
    assert repository.get_exact("plot-a", "cycle-a", T0) == state
    assert repository.latest_at_or_before("plot-a", "cycle-a", T0 + timedelta(hours=1)) == state
    assert repository.latest("plot-a", "cycle-a") == state
    assert repository.history("plot-a", "cycle-a") == (state,)

    with pytest.raises(TwinStateConflict):
        repository.save(make_state(lai=9.0))


def test_snapshot_orders_states_and_rejects_mixed_timestamps():
    first = make_state(plot_id="plot-a")
    second = make_state(plot_id="plot-b", cycle_id="cycle-b")
    repository = InMemoryTwinStateRepository()
    snapshot = TwinSnapshot(T0, (first, second))
    assert repository.save_snapshot(snapshot) == snapshot
    assert snapshot.for_plot("plot-a") == (first,)
    with pytest.raises(ValueError):
        TwinSnapshot(T0, (make_state(timestamp=T0 + timedelta(hours=1)),))


def test_snapshot_conflict_does_not_partially_commit_other_states():
    repository = InMemoryTwinStateRepository()
    existing = make_state(plot_id="plot-b")
    repository.save(existing)
    candidate = make_state(plot_id="plot-a")
    conflicting = make_state(plot_id="plot-b", lai=8.0)
    with pytest.raises(TwinStateConflict):
        repository.save_snapshot(TwinSnapshot(T0, tuple(sorted((candidate, conflicting), key=lambda state: state.plot_id))))
    assert repository.history("plot-a") == ()
    assert repository.get_exact("plot-b", "cycle-a", T0) == existing


def test_multi_plot_commits_history_for_short_cycles_and_post_harvest():
    plot = SyntheticPlot("plot-a", "lettuce", "", 2026)
    cycles = (
        make_cycle("lettuce-a", "plot-a", date(2026, 12, 1), date(2027, 1, 1)),
        make_cycle("lettuce-b", "plot-a", date(2027, 1, 2), date(2027, 1, 20)),
    )
    clock = SimulationClock(T0)
    simulation = MultiPlotSimulation(clock, (plot,), cycles, FixedWeather(), timestep_seconds=3600)
    simulation.advance(3600)
    first = simulation.latest_snapshot()
    assert first is not None
    assert first.states[0].cycle_id == "lettuce-a"
    assert simulation.history("plot-a", "lettuce-a") == first.states

    simulation.advance(48 * 3600)
    second = simulation.latest_snapshot()
    assert second is not None
    assert second.simulation_time == datetime(2027, 1, 3, 0, tzinfo=UTC)
    assert second.states[0].cycle_id == "lettuce-b"
    assert simulation.history("plot-a")
    assert {state.cycle_id for state in simulation.history("plot-a")} == {"lettuce-a", "lettuce-b"}
    assert simulation.history("plot-a", "lettuce-a")[-1].cycle_status == CropCycleStatus.HARVEST_READY.value


def test_same_tick_is_idempotent_and_deterministic():
    plot = SyntheticPlot("plot-a", "tomato", "RAF", 2026)
    cycle = make_cycle("tomato-a", "plot-a", date(2026, 12, 1), date(2027, 2, 1), "tomato", "RAF")
    simulation = MultiPlotSimulation(SimulationClock(T0), (plot,), (cycle,), FixedWeather())
    first = simulation.simulate_at(T0)
    second = simulation.simulate_at(T0)
    assert first == second
    assert len(simulation.history("plot-a", "tomato-a")) == 1


def test_failed_tick_is_atomic():
    plot = SyntheticPlot("plot-a", "tomato", "RAF", 2026)
    cycle = make_cycle("tomato-a", "plot-a", date(2026, 12, 1), date(2027, 2, 1), "tomato", "RAF")

    def fail(_result, _seconds):
        raise RuntimeError("controlled calculation failure")

    simulation = MultiPlotSimulation(SimulationClock(T0), (plot,), (cycle,), FixedWeather(), fail)
    with pytest.raises(RuntimeError):
        simulation.advance(3600)
    assert simulation.latest_snapshot() is None
    assert simulation.history("plot-a") == ()


def test_state_provenance_is_not_observation_provenance():
    state = make_state()
    assert state.state_provenance == "SIMULATION"
    assert state.to_dict()["state_provenance"] == "SIMULATION"
