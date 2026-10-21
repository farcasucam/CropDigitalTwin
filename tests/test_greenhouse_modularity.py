import pytest

from agri_twin.domain.greenhouse_modularity import (
    CATALOGUE_RULES,
    MAX_SPANS,
    CultivationSystem,
    OpenFieldSpec,
    configure_greenhouse,
)
from agri_twin.domain.greenhouse_typology import (
    EvidenceStatus,
    GreenhouseTypology,
    GreenhouseTypologyError,
    RoofProfile,
    all_typologies,
    provisional,
    volume_m3,
)
from agri_twin.infrastructure.greenhouse_idf import build_greenhouse_idf


def test_every_listed_catalogue_combination_is_valid_and_documented():
    for typology in all_typologies():
        rules = CATALOGUE_RULES[typology]
        for span in rules.span_m.values:
            for rise in rules.ridge_rise_m.values or (None,):
                configured = configure_greenhouse(typology, span_m=span, ridge_rise_m=rise, n_spans=2)
                assert configured.is_catalogue_configuration
                assert configured.spec.span_m.evidence is EvidenceStatus.DOCUMENTED_COMMERCIAL
                build_greenhouse_idf(configured.spec)  # geometry must be buildable


def test_off_catalogue_values_are_accepted_but_flagged():
    configured = configure_greenhouse(GreenhouseTypology.MULTITUNEL_CAPILLA, span_m=9.0, gutter_height_m=4.2)
    assert configured.off_catalogue == ("span_m", "gutter_height_m")
    assert configured.spec.span_m.evidence is EvidenceStatus.USER_SUPPLIED
    assert "off-catalogue" in configured.spec.span_m.source
    with pytest.raises(GreenhouseTypologyError):
        configure_greenhouse(GreenhouseTypology.MULTITUNEL_CAPILLA, span_m=9.0, allow_off_catalogue=False)


def test_length_follows_the_pillar_grid_and_spans_scale_the_volume():
    one = configure_greenhouse(GreenhouseTypology.MULTITUNEL_GOTICO, n_spans=1, n_bays=6, pillar_spacing_m=3.0)
    four = configure_greenhouse(GreenhouseTypology.MULTITUNEL_GOTICO, n_spans=4, n_bays=6, pillar_spacing_m=3.0)
    assert one.spec.length_m.value == pytest.approx(18.0)
    assert one.spec.length_m.evidence is EvidenceStatus.USER_SUPPLIED
    assert volume_m3(four.spec) == pytest.approx(4 * volume_m3(one.spec))


def test_invalid_dimensions_are_rejected():
    capilla = GreenhouseTypology.MULTITUNEL_CAPILLA
    with pytest.raises(GreenhouseTypologyError):
        configure_greenhouse(capilla, n_spans=0)
    with pytest.raises(GreenhouseTypologyError):
        configure_greenhouse(capilla, n_spans=MAX_SPANS + 1)
    with pytest.raises(GreenhouseTypologyError):
        configure_greenhouse(capilla, n_bays=0)
    with pytest.raises(GreenhouseTypologyError):
        configure_greenhouse(capilla, span_m=8.0, ridge_rise_m=4.5)  # a segmental arch cannot rise above half its span
    with pytest.raises(GreenhouseTypologyError):
        configure_greenhouse(GreenhouseTypology.TUNEL, gutter_height_m=3.0)


def test_tall_tunnel_becomes_an_ogival_arch():
    low = configure_greenhouse(GreenhouseTypology.TUNEL, span_m=8.0, ridge_rise_m=4.0)
    tall = configure_greenhouse(GreenhouseTypology.TUNEL, span_m=9.6, ridge_rise_m=5.0)
    assert low.spec.profile is RoofProfile.SEGMENTAL_ARCH
    assert tall.spec.profile is RoofProfile.POINTED_ARCH
    assert tall.is_catalogue_configuration and tall.notes
    build_greenhouse_idf(tall.spec)


def test_unpublished_dimensions_stay_provisional_unless_the_user_supplies_them():
    tropical = configure_greenhouse(GreenhouseTypology.MULTITUNEL_TROPICAL_ASIMETRICO)
    assert tropical.spec.ridge_rise_m.evidence is EvidenceStatus.PROVISIONAL_DEFAULT
    chosen = configure_greenhouse(GreenhouseTypology.MULTITUNEL_TROPICAL_ASIMETRICO, ridge_rise_m=2.4)
    assert chosen.spec.ridge_rise_m.evidence is EvidenceStatus.USER_SUPPLIED  # nothing published to match against


def test_open_field_has_no_thermal_backend_and_counts_plants():
    field = OpenFieldSpec()
    assert field.system is CultivationSystem.OPEN_FIELD
    assert field.uses_energyplus is False
    assert field.rows == 20 and field.plants_per_row == 60 and field.plant_count == 1200
    assert field.plot_width_m.evidence is EvidenceStatus.PROVISIONAL_DEFAULT
    with pytest.raises(GreenhouseTypologyError):
        OpenFieldSpec(row_spacing_m=provisional(50.0))
    with pytest.raises(GreenhouseTypologyError):
        OpenFieldSpec(plot_length_m=provisional(0.0))
