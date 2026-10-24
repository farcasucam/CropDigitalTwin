"""The twin as a host of tsxai (https://github.com/farcasucam/tsxai): the adapter honours the simulator contract and produces a benchmark with exactly known truth. Skipped when tsxai is not installed."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

tsxai = pytest.importorskip("tsxai")

from tsxai.bench import generate, leakage_report, read_scenario, sample_scenarios, verify  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor  # noqa: E402
from tsxai.testing import check_simulator  # noqa: E402

from agri_twin.application.interactive_simulation import VARIABLES  # noqa: E402
from agri_twin.application.runtime_events import SPEC_INDEX  # noqa: E402
from agri_twin.interfaces.xai_adapter import DESIGN_FILE, ROLES_FILE, TwinSimulator, benchmark_design  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SIM = TwinSimulator()
DESIGN = benchmark_design()


def test_the_twin_honours_the_simulator_contract_of_tsxai():
    assert check_simulator(SIM) == []  # determinism, timing, no side effects, season sensitivity, consistent catalogue


def test_every_catalogue_variable_has_exactly_one_declared_role_and_a_reason():
    roles = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
    names = [variable.name for variable in VARIABLES]
    assert set(roles["variables"]) == set(names) and all(entry["role"] and entry["why"] for entry in roles["variables"].values())
    catalogue = SIM.catalogue()
    not_represented = {variable.name for variable in VARIABLES if variable.scope == "NONE"}
    assert set(catalogue.variables) == set(names) - not_represented  # variables the twin does not represent are not part of its world
    assert roles["status"] == "PROVISIONAL_DESIGN_CONVENTION" and set(catalogue.default_targets) == set(roles["default_targets"]) == set(catalogue.with_role("target"))


def test_derived_stress_and_accumulators_are_never_forecast_and_no_computed_variable_is_a_known_future_covariate():
    catalogue = SIM.catalogue()
    for name in ("water_stress", "heat_stress", "cold_stress", "vpd_stress", "frost_damage", "accumulated_stress"):
        assert catalogue.variables[name].role == "context_only"  # derived with the twin's own rules from a forecast, never forecast directly
    assert catalogue.variables["biomass_fruit_g_m2"].role != "target" and catalogue.variables["control_energy_kwh_cumulative"].role != "target"
    for name in ("temperature_c", "radiation_w_m2", "greenhouse_ventilation_fraction", "et0_mm", "transpiration_mm"):
        assert catalogue.variables[name].role != "known_future_covariate"  # the twin computes them after the cut-off: using them as future covariates would leak
    assert set(catalogue.with_role("known_future_covariate")) == {"precipitation_mm", "outdoor_temperature_c"}


def test_the_factors_are_the_runtime_events_with_their_technical_bounds_and_sampling_inside_them():
    factors = SIM.factors()
    assert set(factors) <= set(SPEC_INDEX)
    for name, factor in factors.items():
        spec = SPEC_INDEX[name]
        if factor.has_level:
            assert spec.minimum <= factor.sample_range[0] < factor.sample_range[1] <= spec.maximum
        assert bool(factor.applies_when) == (spec.scope == "GREENHOUSE")


def test_contexts_group_the_variants_of_a_crop_so_they_cannot_straddle_the_split():
    contexts = SIM.contexts()
    assert {c.labels["crop"] for c in contexts} == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"} and len(contexts) == 13
    assert all(c.group_by == ("crop",) and c.warmup_hours == DESIGN.warmup_days_min * 24 for c in contexts)
    assert {c.group(3) for c in contexts if c.labels["crop"] == "tomato"} == {"crop=tomato|season=3"}
    options = SIM.scenario_options({"crop": "tomato", "environment": "greenhouse", "control": "on"}, 1)
    assert options["control"]["actuators"]["vents"] == "AUTO" and options["control"]["equipment"]["cooling_capacity_kw"] > 0 and SIM.scenario_options({"crop": "tomato", "control": "off"}, 1) == {}


def test_a_run_is_a_window_of_the_twin_with_the_start_index_semantics_of_the_port():
    scenario = ScenarioDescriptor({"crop": "tomato", "environment": "outdoor", "control": "off"}, 1, 240, 120)
    reference = SIM.run(scenario, ())
    heat = SIM.run(scenario, [Intervention("HEAT_WAVE", 48, 24, 8.0)])
    assert len(reference.time) == 120 and reference.run_hash != heat.run_hash and reference.run_hash == SIM.run(scenario, ()).run_hash
    delta = [h - r for h, r in zip(heat.series["temperature_c"], reference.series["temperature_c"])]
    assert all(d == 0.0 for d in delta[:49]) and all(abs(d - 8.0) < 1e-9 for d in delta[49:73]) and all(d == 0.0 for d in delta[73:])  # exactly the 24 samples after the start index
    assert reference.time[0] != reference.time[1] and "crop_stage" in reference.series and not any(None in values for values in reference.series.values())


def test_a_benchmark_built_on_the_twin_has_exact_truth_deterministic_hashes_and_no_leak(tmp_path):
    specs = [s for s in sample_scenarios(SIM, 13, 20261024, DESIGN) if s.scenario.labels["crop"] in ("tomato", "lettuce") and s.scenario.labels["control"] == "off"][:3]
    assert specs
    manifest = generate(SIM, specs, tmp_path / "a", DESIGN, baseline_label="test")
    assert manifest["simulator"] == SIM.name and verify(tmp_path / "a") == [] and leakage_report(manifest)["status"] == "PASS"
    assert generate(SIM, specs, tmp_path / "b", DESIGN, baseline_label="test")["manifest_hash"] == manifest["manifest_hash"]
    checked = 0
    for entry in manifest["scenarios"]:
        record = read_scenario(tmp_path / "a" / "scenarios" / f"{entry['id']}.json.gz")
        for effect in record["g2_intervention_effects"] + record["g2_probe_effects"]:
            if effect["factor"] == "HEAT_WAVE" and record["spec"]["labels"]["environment"] == "outdoor":
                assert effect["effects"]["temperature_c"]["mean"] == pytest.approx(effect["level"], abs=1e-9)  # an outdoor heat wave adds exactly its level
                checked += 1
    assert checked >= 1  # the sample contains at least one outdoor heat wave whose exact effect was verified


def test_only_the_adapter_knows_tsxai_and_the_framework_knows_nothing_of_the_twin():
    importers = []
    for path in (ROOT / "src" / "agri_twin").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if any(name.split(".")[0] == "tsxai" for name in modules):
                importers.append(path.relative_to(ROOT).as_posix())
    assert set(importers) == {"src/agri_twin/interfaces/xai_adapter.py"}
    assert DESIGN_FILE.exists() and ROLES_FILE.exists()
