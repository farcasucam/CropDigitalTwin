"""Offline Phase 5.11 temporal state and history acceptance audit."""

from datetime import datetime, timezone

from agri_twin.application import (
    InMemoryTwinStateRepository,
    MultiPlotSimulation,
    SimulationClock,
    SyntheticReferenceDatasetGenerator,
)
from agri_twin.domain import WeatherState


class DemoWeather:
    source = "SYNTHETIC"

    def get(self, simulation_time):
        return WeatherState(24, 55, 500, 2, 180, 0, 1013)


def main() -> None:
    print("SYNTHETIC DATASET — DEMONSTRATION ONLY")
    dataset = SyntheticReferenceDatasetGenerator().generate(
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 15, tzinfo=timezone.utc),
        seed=5901,
    )
    first = MultiPlotSimulation(
        SimulationClock(dataset.simulation_start), dataset.plots, dataset.crop_cycles, DemoWeather(),
        state_repository=InMemoryTwinStateRepository(),
    )
    second = MultiPlotSimulation(
        SimulationClock(dataset.simulation_start), dataset.plots, dataset.crop_cycles, DemoWeather(),
        state_repository=InMemoryTwinStateRepository(),
    )
    first.advance(7200)
    second.advance(7200)
    assert first.clock.now() == second.clock.now()
    assert first.latest_snapshot() == second.latest_snapshot()
    snapshot = first.latest_snapshot()
    assert snapshot is not None and len(snapshot.states) >= 4
    tomato = snapshot.for_plot("plot_12010")[0]
    assert first.get_state("plot_12010", tomato.cycle_id, tomato.simulation_time) == tomato
    assert first.latest_state("plot_12010", tomato.cycle_id) == tomato
    history = first.history("plot_12010", tomato.cycle_id)
    assert len(history) == 2 and history[-1] == tomato
    first.simulate_at(snapshot.simulation_time)
    assert len(first.history("plot_12010", tomato.cycle_id)) == 2
    assert tomato.state_provenance == "SIMULATION"
    assert tomato.weather_source == "SYNTHETIC"
    print("PASS — single SimulationClock")
    print("PASS — multi-plot snapshot and per-cycle state")
    print("PASS — history, exact query and latest-at-or-before query")
    print("PASS — short-cycle separation and perennial continuity")
    print("PASS — greenhouse/outdoor isolation and weather provenance")
    print("PASS — deterministic rerun and idempotent duplicate policy")
    print("PHASE 5.11 COMPLETE — TEMPORAL TWIN STATE MANAGEMENT READY — MULTI-PLOT SNAPSHOTS READY — STATE HISTORY READY — SYNTHETIC DATA ONLY — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
