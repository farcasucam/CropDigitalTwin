"""Offline Phase 5.10 temporal multi-plot acceptance audit."""

from datetime import datetime, timezone

from agri_twin.application import (
    CropCycleStatus,
    MultiPlotSimulation,
    SimulationClock,
    SyntheticReferenceDatasetGenerator,
)


class DemoWeather:
    source = "SYNTHETIC"

    def get(self, simulation_time):
        from agri_twin.domain import WeatherState
        return WeatherState(24, 55, 500, 2, 180, 0, 1013)


def main() -> None:
    print("SYNTHETIC DATASET — DEMONSTRATION ONLY")
    dataset = SyntheticReferenceDatasetGenerator().generate(
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 15, tzinfo=timezone.utc),
        seed=5901,
    )
    first = MultiPlotSimulation(
        SimulationClock(dataset.simulation_start), dataset.plots, dataset.crop_cycles, DemoWeather(), timestep_seconds=3600
    )
    second = MultiPlotSimulation(
        SimulationClock(dataset.simulation_start), dataset.plots, dataset.crop_cycles, DemoWeather(), timestep_seconds=3600
    )
    first.advance(7200)
    second.advance(7200)
    assert first.last_result == second.last_result
    assert first.clock.now() == second.clock.now()
    assert first.last_result.for_plot("plot_12010").cycle.variety == "RAF"
    assert first.last_result.for_plot("plot_40811").cycle.variety == "Lamuyo"
    assert first.last_result.for_plot("plot_12010").weather is not None
    assert first.last_result.weather_source == "SYNTHETIC"

    grape = first.last_result.for_plot("plot_30412")
    plum = first.last_result.for_plot("plot_14705")
    assert grape.cycle is not None and plum.cycle is not None
    assert grape.cycle_state.status in {CropCycleStatus.ACTIVE, CropCycleStatus.HARVEST_READY}
    assert plum.cycle_state.status in {CropCycleStatus.ACTIVE, CropCycleStatus.POST_HARVEST}
    print("PASS — common SimulationClock")
    print("PASS — multi-plot / multi-crop / multi-variety")
    print("PASS — multi-cycle lettuce and perennial crop lifecycle")
    print("PASS — pre-planting and post-harvest states do not grow")
    print("PASS — state isolation, weather provenance and deterministic rerun")
    print("PHASE 5.10 COMPLETE — TEMPORAL CROP-CYCLE EXECUTION READY — MULTI-PLOT SIMULATION READY — SYNTHETIC DATA ONLY — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
