"""Phase 6.5r: the working-twin variants (parameters of the simplified greenhouse) and the two-twin scenarios. EnergyPlus is not needed."""

from __future__ import annotations

import pytest
from tsxai.core import Intervention, ScenarioDescriptor

from agri_twin.application.greenhouse_backend import GreenhouseBackendError, parse_greenhouse_backend, simplified_configuration
from agri_twin.interfaces.xai_adapter import TwinSimulator
from agri_twin.interfaces.xai_double_twin import load_design, nominal_values, truth_scenario, variants, working_scenario


def test_parameters_are_part_of_the_request_only_when_given_so_earlier_hashes_are_untouched():
    plain = parse_greenhouse_backend({"backend": "SIMPLIFIED"}, "greenhouse")
    assert plain == parse_greenhouse_backend(None, "greenhouse") and "parameters" not in plain.to_dict()
    varied = parse_greenhouse_backend({"backend": "SIMPLIFIED", "parameters": {"cover_u_w_m2k": 6.5}}, "greenhouse")
    assert varied != plain and varied.to_dict()["parameters"] == {"cover_u_w_m2k": 6.5} and hash(varied) != hash(plain)


@pytest.mark.parametrize("document, environment, path", [
    ({"backend": "SIMPLIFIED", "parameters": {"made_up": 1.0}}, "greenhouse", "greenhouse.parameters.made_up"),
    ({"backend": "SIMPLIFIED", "parameters": {"cover_u_w_m2k": 0}}, "greenhouse", "greenhouse.parameters.cover_u_w_m2k"),
    ({"backend": "SIMPLIFIED", "parameters": {"cover_shgc": 1.2}}, "greenhouse", "greenhouse.parameters.cover_shgc"),
    ({"backend": "SIMPLIFIED", "parameters": {"cover_u_w_m2k": float("nan")}}, "greenhouse", "greenhouse.parameters.cover_u_w_m2k"),
    ({"backend": "SIMPLIFIED", "parameters": [1]}, "greenhouse", "greenhouse.parameters"),
    ({"backend": "SIMPLIFIED", "parameters": {"cover_u_w_m2k": 6.0}}, "outdoor", "greenhouse.parameters"),
    ({"backend": "ENERGYPLUS", "parameters": {"cover_u_w_m2k": 6.0}}, "greenhouse", "greenhouse.parameters"),
])
def test_invalid_parameters_are_refused_with_their_path(document, environment, path):
    with pytest.raises(GreenhouseBackendError) as caught:
        parse_greenhouse_backend(document, environment)
    assert caught.value.path == path


def test_a_parameter_variant_changes_the_lumped_configuration_and_says_so():
    base, _ = simplified_configuration(parse_greenhouse_backend(None, "greenhouse"))
    request = parse_greenhouse_backend({"backend": "SIMPLIFIED", "parameters": {"cover_u_w_m2k": 11.6, "infiltration_ach": 1.0}}, "greenhouse")
    varied, description = simplified_configuration(request)
    assert varied.heat_loss_w_k == pytest.approx(2.0 * base.heat_loss_w_k) and varied.ventilation_ach == 1.0 and base.ventilation_ach == 0.5
    assert description["parameter_overrides"] == {"cover_u_w_m2k": 11.6, "infiltration_ach": 1.0}


def test_variants_are_deterministic_spread_over_the_range_and_capped_where_a_fraction_cannot_exceed_one():
    design = load_design()
    nominal = nominal_values(design["parameters"])
    assert variants("0") == [{}] and variants("small") == variants("small") and variants("small") != variants("large")
    n = design["variants_per_level"]
    for level, width in (("small", 0.1), ("large", 0.3)):
        points = variants(level)
        assert len(points) == n
        for name in design["parameters"]:
            values = sorted(p[name] for p in points)
            low, high = nominal[name] * (1 - width), nominal[name] * (1 + width)
            assert all(min(low, high) - 1e-6 <= v <= (1.0 if name in design["fractions_capped_at_one"] else high) + 1e-6 for v in values)
            if name not in design["fractions_capped_at_one"]:  # one point in each of the n strata of the range
                strata = sorted(int((v - low) / (high - low) * n) for v in values)
                assert strata == list(range(n))
    with pytest.raises(KeyError):
        variants("huge")


def test_the_two_twin_scenarios_keep_the_labels_and_window_and_the_truth_refuses_the_crop_feedback():
    simulator = TwinSimulator()
    labels = {"crop": "tomato", "environment": "greenhouse", "control": "on"}
    scenario = ScenarioDescriptor(labels, 3, 480, 240, simulator.scenario_options(labels, 3))
    truth, working = truth_scenario(scenario), working_scenario(scenario, {"cover_u_w_m2k": 6.0})
    assert truth.options["greenhouse"] == {"backend": "ENERGYPLUS"} and working.options["greenhouse"] == {"backend": "SIMPLIFIED", "parameters": {"cover_u_w_m2k": 6.0}}
    assert (truth.labels, truth.season, truth.window_start, truth.window_hours) == (labels, 3, 480, 240) == (working.labels, working.season, working.window_start, working.window_hours)
    assert truth.options["control"] == working.options["control"] == scenario.options["control"]  # the controller and its equipment are the same in both twins
    feedback = {**labels, "feedback": "on"}
    fed = ScenarioDescriptor(feedback, 3, 480, 240, simulator.scenario_options(feedback, 3))
    assert working_scenario(fed, {"cover_u_w_m2k": 6.0}).options["greenhouse"]["crop_exchange"] is True  # a variant keeps the crop feedback of its scenario
    with pytest.raises(ValueError):
        truth_scenario(fed)


def test_two_variants_give_two_different_runs_of_the_working_twin_and_a_variant_is_reproducible():
    simulator = TwinSimulator()
    labels = {"crop": "tomato", "environment": "greenhouse", "control": "on"}
    scenario = ScenarioDescriptor(labels, 1, 480, 48, simulator.scenario_options(labels, 1))
    first = simulator.run(working_scenario(scenario, {"cover_u_w_m2k": 9.0}))
    again = simulator.run(working_scenario(scenario, {"cover_u_w_m2k": 9.0}))
    other = simulator.run(working_scenario(scenario, {"cover_u_w_m2k": 3.0}))
    assert first.run_hash == again.run_hash != other.run_hash and first.series["temperature_c"] != other.series["temperature_c"]
    paired = simulator.run(working_scenario(scenario, {"cover_u_w_m2k": 9.0}), [Intervention("COLD_WAVE", 10, 12, 8.0)])
    assert paired.run_hash != first.run_hash
