import glob
import math
import re
import subprocess
from pathlib import Path

import pytest

from agri_twin.domain.greenhouse_typology import (
    EvidenceStatus,
    GreenhouseTypology,
    GreenhouseTypologyError,
    all_typologies,
    default_geometry,
    documented,
    floor_area_m2,
    provisional,
    span_profile,
    volume_m3,
)
from agri_twin.infrastructure.greenhouse_idf import RunSpec, build_greenhouse_idf


def _energyplus() -> tuple[Path, Path] | None:
    for exe in sorted(glob.glob(r"C:\EnergyPlus*\energyplus.exe")):
        epws = sorted(glob.glob(str(Path(exe).parent / "WeatherData" / "*.epw")))
        if epws:
            return Path(exe), Path(epws[0])
    return None


def test_every_typology_builds_deterministically():
    for typology in all_typologies():
        geometry = default_geometry(typology)
        first = build_greenhouse_idf(geometry)
        second = build_greenhouse_idf(geometry)
        assert first.text == second.text
        assert first.idf_hash == second.idf_hash
        assert first.text.startswith("! Generated")
        assert "Version, 26.1;" in first.text
        assert first.window_count == first.surface_count - 1  # every surface but the floor has a cover window


def test_defaults_label_documented_and_provisional_values():
    capilla = default_geometry(GreenhouseTypology.MULTITUNEL_CAPILLA)
    assert capilla.span_m.evidence is EvidenceStatus.DOCUMENTED_COMMERCIAL
    assert capilla.length_m.evidence is EvidenceStatus.PROVISIONAL_DEFAULT
    built = build_greenhouse_idf(capilla)
    assert built.provenance["geometry.length_m"].startswith("PROVISIONAL_DEFAULT")
    assert built.provenance["geometry.span_m"].startswith("DOCUMENTED_COMMERCIAL")
    assert built.provenance["envelope.cover_u_w_m2k"].startswith("PROVISIONAL_DEFAULT")
    assert "novagric.com" in built.provenance["geometry.span_m"]


def test_thermal_properties_do_not_depend_on_typology():
    texts = []
    for typology in all_typologies():
        text = build_greenhouse_idf(default_geometry(typology)).text
        texts.append([line for line in text.splitlines() if line.startswith(("WindowMaterial", "ZoneVentilation", "ZoneInfiltration"))][0:3])
    assert all(entry == texts[0] for entry in texts)


def test_tunnel_profile_springs_from_ground_and_reaches_published_height():
    tunnel = default_geometry(GreenhouseTypology.TUNEL)
    profile = span_profile(tunnel)
    assert profile[0][1] == pytest.approx(0.0, abs=1e-9)
    assert profile[-1][1] == pytest.approx(0.0, abs=1e-9)
    assert max(z for _, z in profile) == pytest.approx(4.0)
    # width 8 m, rise 4 m is a semicircle: exact area of the faceted polygon is below pi r^2 / 2
    assert volume_m3(tunnel) < math.pi * 4.0**2 / 2.0 * tunnel.length_m.value


def test_pointed_arch_rises_monotonically_and_is_symmetric():
    gothic = default_geometry(GreenhouseTypology.MULTITUNEL_GOTICO)
    profile = span_profile(gothic)
    span = gothic.span_m.value
    assert max(z for _, z in profile) == pytest.approx(gothic.gutter_height_m.value + gothic.ridge_rise_m.value)
    assert profile[0][0] == pytest.approx(0.0, abs=1e-9) and profile[0][1] == pytest.approx(gothic.gutter_height_m.value)
    assert all(profile[i][1] <= profile[i + 1][1] + 1e-9 for i in range(len(profile) // 2))  # rises monotonically to the apex
    for (y, z), (y2, z2) in zip(profile, reversed(profile)):
        assert y + y2 == pytest.approx(span)
        assert z == pytest.approx(z2)


def test_asymmetric_gable_apex_is_off_centre():
    tropical = default_geometry(GreenhouseTypology.MULTITUNEL_TROPICAL_ASIMETRICO)
    profile = span_profile(tropical)
    apex = max(profile, key=lambda point: point[1])
    assert apex[0] == pytest.approx(0.35 * tropical.span_m.value)


def test_invalid_geometry_is_rejected():
    capilla = default_geometry(GreenhouseTypology.MULTITUNEL_CAPILLA)
    with pytest.raises(GreenhouseTypologyError):
        capilla.with_values(ridge_rise_m=provisional(6.0))  # a segmental arch cannot rise above span / 2
    with pytest.raises(GreenhouseTypologyError):
        capilla.with_values(n_spans=provisional(2.5))
    with pytest.raises(GreenhouseTypologyError):
        capilla.with_values(span_m=documented(-1.0, "x"))


def test_energyplus_zone_volume_matches_analytic_geometry(tmp_path):
    runtime = _energyplus()
    if runtime is None:
        pytest.skip("EnergyPlus runtime and weather file not found (external dependency)")
    exe, epw = runtime
    for typology in all_typologies():
        geometry = default_geometry(typology)
        built = build_greenhouse_idf(geometry, run=RunSpec(7, 1, 7, 2))
        folder = tmp_path / typology.value
        folder.mkdir()
        idf = folder / "gh.idf"
        idf.write_text(built.text, encoding="utf-8")
        result = subprocess.run([str(exe), "-w", str(epw), "-d", str(folder / "out"), str(idf)], capture_output=True, text=True, timeout=300)
        error_text = (folder / "out" / "eplusout.err").read_text(errors="replace")
        assert result.returncode == 0, error_text[-800:]
        assert "** Severe" not in error_text and "**  Fatal" not in error_text
        eio = (folder / "out" / "eplusout.eio").read_text(errors="replace")
        row = re.search(r"Zone Information, GREENHOUSE ZONE,([^\n]*)", eio).group(1).split(",")
        assert float(row[17]) == pytest.approx(volume_m3(geometry), rel=1e-3)  # volume
        assert float(row[20]) == pytest.approx(floor_area_m2(geometry), rel=1e-3)  # floor area


def test_pointed_arch_with_too_small_radius_is_rejected():
    gothic = default_geometry(GreenhouseTypology.MULTITUNEL_GOTICO)
    with pytest.raises(GreenhouseTypologyError):
        gothic.with_values(arch_radius_span_ratio=provisional(0.3))
