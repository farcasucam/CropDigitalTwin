import json
from pathlib import Path

import pytest

from agri_twin.domain import GrowthModelConfigurationError, GrowthModelConfigurationRepository


ROOT = Path(__file__).resolve().parents[1]


def load_configuration(path=ROOT / "src" / "growth_model_config.json"):
    return GrowthModelConfigurationRepository(path, ROOT / "src" / "crop_config.json", ROOT / "src" / "farm_config.json")


def test_growth_contract_covers_existing_crops_soils_and_environments_without_activation():
    configuration = load_configuration()

    assert set(configuration.crop_profiles) == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    assert set(configuration.soil_profiles) == {"sandy_loam", "clay_loam", "calcareous_loam"}
    assert set(configuration.environment_profiles) == {"outdoor", "passive_greenhouse", "actuated_greenhouse"}


def test_crop_parameter_descriptors_are_unambiguous_and_pending_calibration():
    payload = json.loads((ROOT / "src" / "growth_model_config.json").read_text(encoding="utf-8"))

    for descriptor in payload["crop_parameter_contract"].values():
        assert descriptor["unit"]
        assert len(descriptor["reasonable_range"]) == 2
        assert descriptor["default_value"] is None
        assert descriptor["evidence_status"] == "CALIBRATION_REQUIRED"
        assert descriptor["crop_specific"] is True
        assert descriptor["requires_calibration"] is True


def test_growth_contract_rejects_missing_soil_profile_for_a_configured_plot(tmp_path):
    payload = json.loads((ROOT / "src" / "growth_model_config.json").read_text(encoding="utf-8"))
    del payload["soil_profiles"]["sandy_loam"]
    path = tmp_path / "growth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GrowthModelConfigurationError, match="soil profiles missing"):
        load_configuration(path)