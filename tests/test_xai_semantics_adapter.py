"""Phase 6.4: the twin's domain pack for the semantic layer: thresholds only from crop_config.json (with their path as the source), provisional conventions, nothing invented."""

from __future__ import annotations

import json

from agri_twin.interfaces.xai_adapter import CROP_CONFIG_FILE, crop_stage, semantic_pack


def test_the_pack_reads_every_threshold_from_the_crop_catalogue_with_its_path_as_the_source():
    pack = semantic_pack("tomato", 3)
    stage = json.loads(CROP_CONFIG_FILE.read_text(encoding="utf-8"))["crops"]["tomato"]["stages"][crop_stage("tomato", 3)]
    assert pack.threshold("temperature_c", "max").value == stage["stress_thresholds"]["max_temp_c"] and pack.threshold("vpd_kpa", "max").value == stage["vpd_thresholds"]["stress_max_kpa"]
    assert pack.threshold("soil_water_vwc_m3_m3", "min").value == stage["vwc_thresholds"]["optimal_min"]
    assert all(spec.source.startswith("crop_config.json tomato/") for sides in pack.thresholds.values() for spec in sides.values())
    assert pack.convention_status == "provisional" and pack.content_hash == semantic_pack("tomato", 3).content_hash


def test_a_crop_or_month_without_a_catalogue_stage_gets_no_thresholds_instead_of_invented_ones():
    assert crop_stage("tomato", 3) == "establishment" and crop_stage("nonexistent", 3) is None
    assert semantic_pack("nonexistent", 3).thresholds == {}
    months = {m for stage in json.loads(CROP_CONFIG_FILE.read_text(encoding="utf-8"))["crops"]["tomato"]["stages"].values() for m in stage["months"]}
    assert len(months) < 12 and semantic_pack("tomato", next(i for i in range(1, 13) if i not in {["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].index(m) + 1 for m in months})).thresholds == {}


def test_the_twin_confirms_only_the_variables_whose_direction_was_reliable_in_development():
    pack = semantic_pack("tomato", 3)
    assert set(pack.confirmable_variables) == {"temperature_c", "greenhouse_heating_kw", "greenhouse_cooling_kw"}
    assert "relative_humidity_pct" not in pack.confirmable_variables and "vpd_kpa" not in pack.confirmable_variables


def test_the_pack_forbids_claiming_calibration_or_validation_of_the_twin():
    claims = " ".join(semantic_pack("tomato", 3).forbidden_claims)
    assert "calibrated" in claims and "validated against the real system" in claims
