import csv
import glob
import math
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.domain.greenhouse import saturation_vapour_pressure_kpa
from agri_twin.domain.greenhouse_typology import GreenhouseTypology, default_geometry
from agri_twin.infrastructure.epw_weather import (
    EpwConversionError,
    EpwLocation,
    HourConvention,
    dew_point_c,
    erbs_components,
    write_epw,
)
from agri_twin.infrastructure.greenhouse_idf import RunSpec, build_greenhouse_idf

LOCATION = EpwLocation(40.0, -3.0, 810.0, "Test Site", "ESP")
HEADER = ["timestamp", "temperature_c", "relative_humidity_pct", "solar_radiation_w_m2", "wind_speed_m_s", "wind_direction_deg", "rain_rate_mm_h", "pressure_hpa"]


def _write_csv(path: Path, hours: int, start: datetime = datetime(2026, 7, 1, tzinfo=timezone.utc), skip: set[int] | None = None) -> list[dict]:
    rows = []
    for i in range(hours):
        if skip and i in skip:
            continue
        stamp = start + timedelta(hours=i)
        sun = max(0.0, math.sin((stamp.hour - 6) / 12 * math.pi))
        rows.append({
            "timestamp": stamp.isoformat(), "temperature_c": round(18 + 8 * sun + (i % 5) * 0.3, 1), "relative_humidity_pct": 55,
            "solar_radiation_w_m2": round(850 * sun, 1), "wind_speed_m_s": 2.0, "wind_direction_deg": 270, "rain_rate_mm_h": 0.0, "pressure_hpa": 925.0,
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _energyplus() -> tuple[Path, Path] | None:
    for exe in sorted(glob.glob(r"C:\EnergyPlus*\energyplus.exe")):
        return Path(exe), Path(exe).parent
    return None


def test_dew_point_inverts_the_project_saturation_pressure():
    for temperature, humidity in ((20.0, 60.0), (5.0, 90.0), (35.0, 20.0)):
        dew = dew_point_c(temperature, humidity)
        assert saturation_vapour_pressure_kpa(dew) == pytest.approx(saturation_vapour_pressure_kpa(temperature) * humidity / 100.0, rel=1e-9)
        assert dew <= temperature


def test_erbs_components_close_the_energy_balance():
    ghi, cos_zenith = 700.0, 0.8
    dni, dhi = erbs_components(ghi, cos_zenith, 1367.0)
    assert dni * cos_zenith + dhi == pytest.approx(ghi, rel=1e-9)
    assert erbs_components(0.0, 0.8, 1367.0) == (0.0, 0.0)
    assert erbs_components(30.0, -0.2, 1367.0) == (0.0, 30.0)  # sun below the horizon: all diffuse, no beam


def test_conversion_is_deterministic_and_structured(tmp_path):
    csv_path = tmp_path / "w.csv"
    _write_csv(csv_path, 72)
    first = write_epw(csv_path, tmp_path / "a.epw", LOCATION)
    second = write_epw(csv_path, tmp_path / "b.epw", LOCATION)
    assert first.sha256 == second.sha256
    lines = (tmp_path / "a.epw").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("LOCATION,Test Site") and lines[7].startswith("DATA PERIODS")
    data = lines[8:]
    assert len(data) == first.records == 48  # 72 rows -> days 1 July (hours 1-24) and 2 July; 3 July partial dropped
    assert first.trimmed_rows == 24
    assert all(len(row.split(",")) == 35 for row in data)
    assert data[0].split(",")[:5] == ["2026", "7", "1", "1", "60"]
    assert data[23].split(",")[:5] == ["2026", "7", "1", "24", "60"]
    assert "Erbs decomposition (no measured DNI/DHI)" in first.assumptions


def test_midnight_stamp_closes_the_previous_day_and_partial_days_are_trimmed(tmp_path):
    csv_path = tmp_path / "w.csv"
    _write_csv(csv_path, 49, start=datetime(2026, 7, 1, tzinfo=timezone.utc))
    report = write_epw(csv_path, tmp_path / "w.epw", LOCATION)
    data = (tmp_path / "w.epw").read_text(encoding="utf-8").splitlines()[8:]
    # the row stamped 2026-07-01T00:00 would be hour 24 of 30 June, a partial day, so it is trimmed
    assert report.trimmed_rows == 1 and report.records == 48
    assert data[0].split(",")[:4] == ["2026", "7", "1", "1"]
    assert data[23].split(",")[:4] == ["2026", "7", "1", "24"]  # row stamped 2026-07-02T00:00 closes 1 July
    assert report.hour_convention == HourConvention.END_OF_HOUR.value


def test_gaps_and_short_series_are_rejected(tmp_path):
    csv_path = tmp_path / "gap.csv"
    _write_csv(csv_path, 72, skip={10})
    with pytest.raises(Exception, match="hourly"):  # rejected by CsvWeatherProvider before conversion
        write_epw(csv_path, tmp_path / "x.epw", LOCATION)
    short = tmp_path / "short.csv"
    _write_csv(short, 12)
    with pytest.raises(EpwConversionError):
        write_epw(short, tmp_path / "y.epw", LOCATION)


def test_energyplus_reproduces_csv_outdoor_temperature(tmp_path):
    runtime = _energyplus()
    if runtime is None:
        pytest.skip("EnergyPlus runtime not found (external dependency)")
    exe, _ = runtime
    csv_path = tmp_path / "w.csv"
    rows = _write_csv(csv_path, 96)
    write_epw(csv_path, tmp_path / "w.epw", LOCATION)
    built = build_greenhouse_idf(default_geometry(GreenhouseTypology.TUNEL), run=RunSpec(7, 2, 7, 3))
    (tmp_path / "gh.idf").write_text(built.text, encoding="utf-8")
    result = subprocess.run([str(exe), "-w", str(tmp_path / "w.epw"), "-d", str(tmp_path / "out"), str(tmp_path / "gh.idf")], capture_output=True, text=True, timeout=300)
    err = (tmp_path / "out" / "eplusout.err").read_text(errors="replace")
    assert result.returncode == 0, err[-800:]
    assert "** Severe" not in err
    connection = sqlite3.connect(tmp_path / "out" / "eplusout.sql")
    try:
        found = connection.execute(
            "select t.Month, t.Day, t.Hour, t.Minute, v.Value from ReportData v join ReportDataDictionary d using(ReportDataDictionaryIndex) "
            "join Time t using(TimeIndex) where d.Name='Site Outdoor Air Drybulb Temperature' and t.Minute=0 and t.WarmupFlag is not 1"
        ).fetchall()
    finally:
        connection.close()
    by_end = {(month, day, hour): value for month, day, hour, minute, value in found}
    expected = {datetime.fromisoformat(r["timestamp"]): r["temperature_c"] for r in rows}
    checked = 0
    for stamp, temperature in expected.items():
        if stamp.day == 2 and stamp.hour in (3, 9, 15, 21):  # END_OF_HOUR: row stamped T is the value at the end of hour T
            assert by_end[(7, 2, stamp.hour)] == pytest.approx(temperature, abs=0.11)
            checked += 1
    assert checked == 4
