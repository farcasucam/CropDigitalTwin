"""The confirmatory protocol D25: well-formed, partitions as the salt gives them, every exposed unit registered, and, once frozen, unchanged."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
pytest.importorskip("tsxai")

import freeze_protocol_d25 as freeze  # noqa: E402

PROTOCOL = json.loads(freeze.PROTOCOL.read_text(encoding="utf-8"))


def test_the_protocol_has_the_declared_structure():
    assert PROTOCOL["contract"] == "xai_protocol_d25"
    assert {h["id"] for h in PROTOCOL["hypotheses"]} == {"H1", "H2", "H3", "H4", "H5", "H6"}
    assert {s["id"] for s in PROTOCOL["strata"]} == {"S1", "S2", "S3", "S4"}
    assert PROTOCOL["comparators"]["primary"]["id"] == "TF" and {c["id"] for c in PROTOCOL["comparators"]["others"]} == {"SN", "HW", "LR", "DS"}
    assert PROTOCOL["analysis"]["not_claimed"] and PROTOCOL["episode"]["excluded"]


def test_the_partitions_are_the_documented_ones_and_the_design_is_the_frozen_one():
    parts = freeze.partitions(PROTOCOL)
    assert [len(parts["agri"][c]) for c in ("tomato", "pepper", "lettuce")] == [11, 18, 13] and parts["tep"] == [3, 4, 6, 10, 13, 14, 18, 21, 23, 33]
    design = json.loads((ROOT / "src" / "xai_benchmark_design.json").read_text(encoding="utf-8"))
    assert design["split"]["salt"] == PROTOCOL["domains"]["agri"]["salt"] and design["split"]["test_share"] == PROTOCOL["domains"]["agri"]["test_share"] and design["seasons"] == PROTOCOL["domains"]["agri"]["seasons"]
    document = freeze.DOCUMENT.read_text(encoding="utf-8")
    for crop, seasons in parts["agri"].items():
        assert ", ".join(str(s) for s in seasons) in document


def test_every_exposed_unit_is_registered_and_is_a_test_unit():
    assert freeze.problems(PROTOCOL) == []


def test_a_frozen_protocol_has_not_changed():
    if not freeze.FREEZE.exists():
        pytest.skip("the protocol is not frozen yet (open parameters: %s)" % ", ".join(freeze.open_parameters(PROTOCOL)))
    frozen = json.loads(freeze.FREEZE.read_text(encoding="utf-8"))
    assert frozen["hashes"] == {name: freeze.file_hash(path) for name, path in freeze.TRACKED.items()}, "a tracked file changed after the freeze: record a deviation in section 10 instead"
    assert frozen["partitions"] == freeze.partitions(PROTOCOL)
