import pytest

from agri_twin.domain import PhenologyConfigurationError, validate_phenology_configuration


def valid_config():
    return {
        "method": "gdd",
        "base_temperature_c": None,
        "stages": [
            {"stage_key": "establishment", "gdd_to_next": None},
            {"stage_key": "vegetative_growth", "gdd_to_next": None},
        ],
    }


def test_optional_empty_phenology_is_accepted_without_activation():
    validate_phenology_configuration(None)


def test_future_phenology_shape_is_validated_without_requiring_values():
    validate_phenology_configuration(valid_config())


def test_phenology_stage_order_can_be_checked_without_executing_transitions():
    validate_phenology_configuration(valid_config(), ("establishment", "vegetative_growth"))
    with pytest.raises(PhenologyConfigurationError, match="stage order"):
        validate_phenology_configuration(valid_config(), ("vegetative_growth", "establishment"))


@pytest.mark.parametrize(
    "change",
    [
        {"method": "unknown"},
        {"stages": []},
        {"stages": [{"stage_key": "establishment"}]},
        {"stages": [{"stage_key": "establishment", "gdd_to_next": None}, {"stage_key": "establishment", "gdd_to_next": None}]},
        {"stages": [{"stage_key": "establishment", "gdd_to_next": -1}]},
        {"base_temperature_c": "10"},
    ],
)
def test_incomplete_or_invalid_phenology_is_rejected(change):
    payload = valid_config()
    payload.update(change)
    with pytest.raises(PhenologyConfigurationError):
        validate_phenology_configuration(payload)


def test_current_config_has_no_active_phenology_values():
    import json
    from pathlib import Path

    payload = json.loads(Path("src/crop_config.json").read_text(encoding="utf-8"))
    assert all("phenology" not in crop for crop in payload["crops"].values())


def test_optional_phenology_does_not_change_current_crop_configuration():
    repository = __import__("agri_twin.domain", fromlist=["CropConfigRepository"]).CropConfigRepository("src/crop_config.json")
    assert repository.get_crop("plum").resolve_stage("yield_maturation").stage_key == "yield_maturation"
