from pathlib import Path

import pytest

from agri_twin.infrastructure.eppy_greenhouse import (
    EppyGreenhouseBuilder,
    EppyGreenhouseError,
    EppyStatus,
    GreenhouseVariant,
    PARAMETER_REGISTRY_IDS,
    VARIANT_DEFINITIONS,
    detect_eppy,
)

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "templates" / "greenhouse" / "greenhouse_template.idf"


def test_eppy_detection_is_explicit():
    assert detect_eppy().status in set(EppyStatus)


def test_missing_eppy_is_explicit(monkeypatch):
    import agri_twin.infrastructure.eppy_greenhouse as module

    def missing(_name):
        raise ModuleNotFoundError("eppy")

    monkeypatch.setattr(module.importlib, "import_module", missing)
    assert module.detect_eppy().status is EppyStatus.UNAVAILABLE


def test_template_is_present_and_original_is_not_changed(tmp_path):
    before = TEMPLATE.read_bytes()
    builder = EppyGreenhouseBuilder(output_dir=tmp_path)
    assert builder.template_path == TEMPLATE
    assert builder.template_path.is_file()
    assert builder.status().status in set(EppyStatus)
    assert TEMPLATE.read_bytes() == before


def test_variant_hash_is_order_independent_and_deterministic():
    first = GreenhouseVariant("x", "description", {"mode": "passive"}, {"b": 2, "a": 1})
    second = GreenhouseVariant("x", "description", {"mode": "passive"}, {"a": 1, "b": 2})
    assert first.configuration_hash == second.configuration_hash
    assert len(first.configuration_hash) == 64


def test_invalid_variant_configuration_is_rejected_before_eppy():
    builder = EppyGreenhouseBuilder()
    with pytest.raises(ValueError, match="invalid value"):
        builder.build(GreenhouseVariant("invalid", "bad", modifications={"ventilation_ach": -1}))
    with pytest.raises(ValueError, match="unsupported"):
        builder.build(GreenhouseVariant("invalid", "bad", modifications={"crop_lai": 2}))


def test_builder_reports_missing_eppy_or_idd_without_breaking_core():
    builder = EppyGreenhouseBuilder()
    if detect_eppy().status is EppyStatus.UNAVAILABLE:
        with pytest.raises(EppyGreenhouseError, match="UNAVAILABLE"):
            builder.load_template()
    else:
        assert builder.status().status in {EppyStatus.MISCONFIGURED, EppyStatus.AVAILABLE}


def available_builder(tmp_path):
    builder = EppyGreenhouseBuilder(output_dir=tmp_path)
    if builder.status().status is not EppyStatus.AVAILABLE:
        pytest.skip(f"eppy IDF integration unavailable: {builder.status().detail}")
    return builder


@pytest.mark.parametrize("variant_name", sorted(VARIANT_DEFINITIONS))
def test_all_variants_generate_distinct_idfs_when_eppy_is_available(tmp_path, variant_name):
    builder = available_builder(tmp_path)
    result = builder.build(variant_name)
    assert result.generated_idf_path is not None
    assert result.generated_idf_path.is_file()
    assert result.generated_idf_path != TEMPLATE


def test_baseline_and_modified_idf_differ_when_eppy_is_available(tmp_path):
    builder = available_builder(tmp_path)
    original = TEMPLATE.read_bytes()
    baseline = builder.build("baseline")
    ventilation = builder.build("high_ventilation")
    assert baseline.generated_idf_path.read_bytes() != ventilation.generated_idf_path.read_bytes()
    assert TEMPLATE.read_bytes() == original


def test_variant_declares_existing_registry_parameter():
    assert PARAMETER_REGISTRY_IDS["solar_transmission"] == "greenhouse.cover_transmission"


def test_same_variant_uses_same_output_path_and_bytes_when_eppy_is_available(tmp_path):
    builder = available_builder(tmp_path)
    first = builder.build("shading")
    first_bytes = first.generated_idf_path.read_bytes()
    second = builder.build("shading")
    assert first.generated_idf_path == second.generated_idf_path
    assert first_bytes == second.generated_idf_path.read_bytes()
