"""Contract checks of the Tennessee Eastman host. Skipped unless TEP_SRC points to the source directory of the third-party `tep` package (it is not a dependency of the repository)."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
pytest.importorskip("tsxai")
if not os.environ.get("TEP_SRC"):
    pytest.skip("TEP_SRC is not set", allow_module_level=True)

import numpy as np  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor  # noqa: E402

from process_twins.tennessee_eastman import TennesseeEastman  # noqa: E402

DESC = ScenarioDescriptor({"plant": "tennessee_eastman_base_case"}, 1, 300, 240, {})


@pytest.fixture(scope="module")
def host():
    return TennesseeEastman()


@pytest.fixture(scope="module")
def baseline(host):
    return host.run_traced(DESC)


def test_run_is_a_pure_function_of_its_inputs(host, baseline):
    again, _ = host.run_traced(DESC)
    assert again.run_hash == baseline[0].run_hash and again.series == baseline[0].series


def test_a_disturbance_changes_exactly_the_samples_after_its_start(host, baseline):
    result = host.run(DESC, (Intervention("IDV1", 60, 100),))
    changed = [k for k in range(240) if any(result.series[v][k] != baseline[0].series[v][k] for v in result.series)]
    assert changed and changed[0] == 61


def test_replaying_the_own_trace_reproduces_the_closed_loop(host, baseline):
    replayed, trace = host.run_traced(DESC, (), baseline[1])
    assert replayed.series == baseline[0].series and set(trace) == {f"mv_{i:02d}" for i in range(1, 13)}


def test_a_replayed_policy_blocks_the_controller_reaction(host, baseline):
    reactive = host.run(DESC, (Intervention("IDV4", 60, 150),))
    replayed, _ = host.run_traced(DESC, (Intervention("IDV4", 60, 150),), baseline[1])
    assert np.array_equal(replayed.series["mv_10"], baseline[0].series["mv_10"])  # the imposed valve does not move
    assert not np.array_equal(reactive.series["mv_10"], baseline[0].series["mv_10"])  # the closed loop does react


def test_an_unknown_factor_is_refused(host):
    with pytest.raises(Exception):
        host.run(DESC, (Intervention("RAIN", 10, 10),))
