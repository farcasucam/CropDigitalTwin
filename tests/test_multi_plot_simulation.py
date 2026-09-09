from datetime import date, datetime, timezone

from agri_twin.application import (
    CropCycleStatus,
    MultiPlotSimulation,
    SyntheticCropCycle,
    SyntheticPlot,
    SyntheticReferenceDatasetGenerator,
    SimulationClock,
)
from agri_twin.domain import WeatherState


class FixedWeatherProvider:
    source = "SYNTHETIC"

    def __init__(self):
        self.timestamps = []

    def get(self, simulation_time):
        self.timestamps.append(simulation_time)
        return WeatherState(24, 55, 500, 2, 180, 0, 1013)


def cycle(cycle_id, plot_id, crop, variety, planting, harvest, perennial=False):
    return SyntheticCropCycle(cycle_id, plot_id, crop, variety, planting, None, harvest, harvest, "perennial" if perennial else "annual", perennial)


def test_resolves_multiple_cycles_and_common_clock():
    plots = (
        SyntheticPlot("plot-a", "tomato", "RAF", 2026),
        SyntheticPlot("plot-b", "pepper", "Lamuyo", 2026),
        SyntheticPlot("plot-c", "lettuce", "", 2026),
    )
    cycles = (
        cycle("tomato-a", "plot-a", "tomato", "RAF", date(2026, 5, 1), date(2026, 9, 1)),
        cycle("pepper-b", "plot-b", "pepper", "Lamuyo", date(2026, 8, 1), date(2026, 10, 1)),
        cycle("lettuce-1", "plot-c", "lettuce", "", date(2026, 1, 1), date(2026, 2, 1)),
        cycle("lettuce-2", "plot-c", "lettuce", "", date(2026, 3, 1), date(2026, 4, 1)),
    )
    clock = SimulationClock(datetime(2026, 8, 27, 10, tzinfo=timezone.utc))
    weather = FixedWeatherProvider()
    simulation = MultiPlotSimulation(clock, plots, cycles, weather, timestep_seconds=3600)

    assert simulation.active_cycle("plot-a").crop == "tomato"
    assert simulation.active_cycle("plot-b").crop == "pepper"
    assert simulation.active_cycle("plot-c") is None
    simulation.advance(7200)

    assert clock.now() == datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
    assert simulation.last_result is not None
    assert [result.plot.plot_id for result in simulation.last_result.plot_results] == ["plot-a", "plot-b", "plot-c"]
    assert all(result.weather is not None for result in simulation.last_result.plot_results)
    assert all(timestamp.tzinfo is not None for timestamp in weather.timestamps)
    assert simulation.cycle_state("plot-a").ticks == 2
    assert simulation.cycle_state("plot-b").ticks == 2


def test_lifecycle_states_and_post_harvest_do_not_tick():
    plot = SyntheticPlot("plot", "grape", "Monastrell", 2026)
    perennial = cycle("grape-2026", "plot", "grape", "Monastrell", None, date(2026, 7, 1), True)
    clock = SimulationClock(datetime(2026, 8, 1, tzinfo=timezone.utc))
    simulation = MultiPlotSimulation(clock, (plot,), (perennial,), FixedWeatherProvider(), timestep_seconds=3600)

    result = simulation.simulate_at(clock.now()).for_plot("plot")
    assert result.cycle_state.status is CropCycleStatus.POST_HARVEST
    assert result.cycle_state.ticks == 0
    assert simulation.active_cycle("plot") is None


def test_preplanting_has_no_active_cycle_and_cycles_are_independent():
    plot = SyntheticPlot("plot", "lettuce", "", 2026)
    cycles = (
        cycle("lettuce-1", "plot", "lettuce", "", date(2026, 1, 1), date(2026, 2, 1)),
        cycle("lettuce-2", "plot", "lettuce", "", date(2026, 3, 1), date(2026, 4, 1)),
    )
    before = MultiPlotSimulation(SimulationClock(datetime(2025, 12, 1, tzinfo=timezone.utc)), (plot,), cycles)
    assert before.active_cycle("plot") is None
    assert before.simulate_at(before.clock.now()).for_plot("plot").cycle_state.status is CropCycleStatus.PRE_PLANTING

    active = MultiPlotSimulation(SimulationClock(datetime(2026, 3, 15, tzinfo=timezone.utc)), (plot,), cycles)
    active.advance(3600)
    state = active.cycle_state("plot")
    assert state.cycle_id == "lettuce-2"
    assert state.ticks == 1
    assert active._states.get("lettuce-1") is None


def test_phase_5_9_reference_cycles_are_usable():
    dataset = SyntheticReferenceDatasetGenerator().generate(
        datetime(2026, 6, 1, tzinfo=timezone.utc), datetime(2026, 6, 2, tzinfo=timezone.utc), seed=5901
    )
    simulation = MultiPlotSimulation(
        SimulationClock(dataset.simulation_start), dataset.plots, dataset.crop_cycles, FixedWeatherProvider(), timestep_seconds=3600
    )
    simulation.advance(3600)
    assert simulation.last_result.for_plot("plot_12010").cycle.crop == "tomato"
    assert simulation.last_result.for_plot("plot_40811").cycle.variety == "Lamuyo"
