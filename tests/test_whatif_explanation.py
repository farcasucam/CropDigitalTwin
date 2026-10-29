"""The explanation of a what-if of the web bench: events as players, branches from one checkpoint, deterministic text that the checker accepts."""

from __future__ import annotations

import pytest

pytest.importorskip("tsxai")

from agri_twin.application.interactive_simulation import SimulationApiError  # noqa: E402
from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter  # noqa: E402

VARIABLES = ["crop_stage", "biomass_total_g_m2", "temperature_c", "water_stress", "nutrient_status"]
BASE = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-15T00:00:00+00:00", "options": {"variables": VARIABLES, "compute_trajectory_hash": True}}
HEAT = {"event_type": "HEAT_WAVE", "start_simulation_time": "2026-02-27T00:00:00+00:00", "duration_hours": 48, "intensity": 6, "ramp_hours": 6}
FERT = {"event_type": "FERTILIZATION", "start_simulation_time": "2026-02-26T00:00:00+00:00", "duration_hours": 24, "intensity": 20}
DOC = {"request": BASE, "checkpoint_time": "2026-02-25T00:00:00+00:00", "events": [HEAT, FERT]}


@pytest.fixture(scope="module")
def adapter():
    return InteractiveFrontendAdapter()


@pytest.fixture(scope="module")
def english(adapter):
    return adapter.runtime_explain(DOC)


def test_the_text_is_traced_to_the_report_and_the_checker_accepts_it(english):
    assert english["kind"] == "WHAT_IF_EFFECT_EXPLANATION" and english["problems"] == []
    kinds = [c["kind"] for c in english["claims"]]
    assert kinds[0] == "SCOPE" and "TOTAL" in kinds and kinds[-1] == "CAVEAT"
    assert english["branch_runs"] == 4 and len(english["players"]) == 2  # 2^2 combinations, the baseline among them
    assert "not calibrated" in english["text"] and "heat wave" in english["text"]


def test_the_explanation_is_deterministic_and_the_languages_share_the_report(adapter, english):
    again = adapter.runtime_explain(DOC)
    spanish = adapter.runtime_explain({**DOC, "language": "es"})
    assert again["narrative_hash"] == english["narrative_hash"]
    assert spanish["source_report_hash"] == english["source_report_hash"] and spanish["narrative_hash"] != english["narrative_hash"]
    assert [c["kind"] for c in spanish["claims"]] == [c["kind"] for c in english["claims"]] and spanish["problems"] == []


def test_the_effects_match_the_what_if_endpoint(adapter, english):
    what_if = adapter.runtime_what_if(DOC)
    delta = what_if["comparison"]["variables"]["biomass_total_g_m2"]["delta_final"]
    assert english["effects"]["biomass_total_end"]["total_effect"] == pytest.approx(delta)


def test_refusals(adapter):
    def code(document):
        with pytest.raises(SimulationApiError) as caught:
            adapter.runtime_explain(document)
        return caught.value.errors[0].path

    assert code({**DOC, "language": "fr"}) == "language"
    assert code({**DOC, "request": {**BASE, "greenhouse": {"backend": "ENERGYPLUS"}}}) == "request"
    many = [{**HEAT, "event_id": f"h{i}", "start_simulation_time": f"2026-02-{26 + i % 2:02d}T0{i}:00:00+00:00"} for i in range(5)]
    assert code({**DOC, "events": many}) == "events"  # more than MAX_EVENTS
