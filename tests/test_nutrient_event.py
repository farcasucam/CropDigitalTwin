"""Level 0 of the nutrient line: the FERTILIZATION runtime event and the nutrient series of the interactive simulation.

The model behind them is the reduced single-pool nutrient model (uncalibrated); these tests check the CONTRACT (a total dose spread over the interval, events add up, series exposed, the default run unchanged),
not an agronomic response.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application.runtime_events import SPEC_INDEX, RuntimeEventError, event_contract, parse_runtime_events
from agri_twin.application.scenarios import HALF_OPEN_INTERVAL, ScenarioEvent, ScenarioRunner
from tsxai.core import Intervention, ScenarioDescriptor
from agri_twin.interfaces.xai_adapter import TwinSimulator

UTC = timezone.utc
NUTRIENT_SERIES = ("nutrient_available_kg_ha", "nutrient_applied_kg_ha", "nutrient_extracted_kg_ha", "nutrient_leached_kg_ha", "nutrient_status")


@pytest.fixture(scope="module")
def run():
    simulator = TwinSimulator()
    labels = {"crop": "tomato", "environment": "outdoor", "control": "off"}
    descriptor = ScenarioDescriptor(labels, 34, 1500, 120, simulator.scenario_options(labels, 34))
    cache: dict = {}

    def go(*events: Intervention):
        key = tuple((e.factor, e.start, e.duration, e.level) for e in events)
        if key not in cache:
            cache[key] = simulator.run(descriptor, events)
        return cache[key]

    return go


def test_the_nutrient_series_are_exposed_and_the_default_run_has_no_application(run):
    series = run().series
    assert all(name in series for name in NUTRIENT_SERIES)
    assert sum(series["nutrient_applied_kg_ha"]) == 0.0
    assert all(0.0 <= value <= 1.0 for value in series["nutrient_status"])


def test_a_dose_is_a_total_spread_evenly_over_the_interval(run):
    base, dosed = run(), run(Intervention("FERTILIZATION", 30, 24, 24.0))
    applied = dosed.series["nutrient_applied_kg_ha"]
    assert math.isclose(sum(applied), 24.0, rel_tol=1e-9)
    # the series sample j is the step that STARTS at window hour j - 1 (the adapter's trajectory convention), so the 24 steps of an event at hour 30 are the samples 31 to 54
    assert all(math.isclose(value, 1.0, rel_tol=1e-9) for value in applied[31:55]) and sum(applied[:31]) == 0.0 and sum(applied[55:]) == 0.0
    assert dosed.series["nutrient_available_kg_ha"][-1] > base.series["nutrient_available_kg_ha"][-1]
    assert dosed.series["nutrient_available_kg_ha"][:31] == base.series["nutrient_available_kg_ha"][:31]  # nothing before the event changes


def test_events_add_up_instead_of_replacing_each_other(run):
    both = run(Intervention("FERTILIZATION", 30, 24, 12.0), Intervention("FERTILIZATION", 40, 24, 12.0))
    applied = both.series["nutrient_applied_kg_ha"]
    assert math.isclose(sum(applied), 24.0, rel_tol=1e-9)
    assert math.isclose(max(applied), 1.0, rel_tol=1e-9) and math.isclose(applied[45], 1.0, rel_tol=1e-9) and math.isclose(applied[32], 0.5, rel_tol=1e-9)


def test_the_pool_is_capped_at_the_reserve_so_a_larger_dose_is_not_all_retained(run):
    huge = run(Intervention("FERTILIZATION", 30, 24, 900.0))
    reserve_cap = max(huge.series["nutrient_available_kg_ha"])
    assert reserve_cap <= 200.0 + 1e-9  # the baseline reserve of the reduced model
    assert math.isclose(sum(huge.series["nutrient_applied_kg_ha"]), 900.0, rel_tol=1e-9)  # the series is the dose OFFERED to the pool, not the part retained


def test_the_event_contract_lists_the_dose_as_a_total_added_to_the_pool():
    spec = SPEC_INDEX["FERTILIZATION"]
    assert spec.primary_parameter == "amount_kg_ha" and spec.scope == "ALL" and spec.minimum_exclusive and not spec.ramp_supported
    entry = next(item for item in event_contract()["supported"] if item["event_type"] == "FERTILIZATION")
    assert "IN TOTAL" in entry["intensity_unit"] and "ADDED" in entry["intensity_unit"] and entry["environments"] == "outdoor, greenhouse"


def test_a_zero_or_missing_dose_is_refused():
    start = datetime(2026, 5, 1, tzinfo=UTC)
    raw = {"event_type": "FERTILIZATION", "start_simulation_time": (start + timedelta(hours=1)).isoformat(), "duration_hours": 4}
    with pytest.raises(RuntimeEventError):
        parse_runtime_events([raw], environment="outdoor", earliest=start, latest=start + timedelta(days=10))
    with pytest.raises(RuntimeEventError):
        parse_runtime_events([{**raw, "intensity": 0}], environment="outdoor", earliest=start, latest=start + timedelta(days=10))
    assert parse_runtime_events([{**raw, "intensity": 20}], environment="outdoor", earliest=start, latest=start + timedelta(days=10))[0].intensity == 20.0


def test_a_historical_event_keeps_its_old_meaning_and_runtime_events_are_added_on_top():
    start = datetime(2026, 5, 1, tzinfo=UTC)
    historical = ScenarioEvent("h", "fertilization", start, start + timedelta(hours=5), 3.0)
    runtime = ScenarioEvent("r", "fertilization", start, start + timedelta(hours=10), 20.0, {HALF_OPEN_INTERVAL: 1.0})
    assert ScenarioRunner._fertilization([historical], 3600.0).amount_kg_ha == 3.0  # per step while active, as before
    assert math.isclose(ScenarioRunner._fertilization([runtime], 3600.0).amount_kg_ha, 2.0)  # 20 kg/ha over 10 one-hour steps
    assert math.isclose(ScenarioRunner._fertilization([historical, runtime], 3600.0).amount_kg_ha, 5.0)
    assert ScenarioRunner._fertilization([], 3600.0) is None
