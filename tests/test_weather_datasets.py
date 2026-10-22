"""Phase 5.43 (step A): local historical weather datasets. Everything here runs offline with a fake transport."""

from __future__ import annotations

import json
import socket
from datetime import date, datetime, timedelta, timezone

import pytest

from agri_twin.application import weather_datasets as wd
from agri_twin.infrastructure.csv_weather import CsvWeatherProvider
from agri_twin.infrastructure.open_meteo import OpenMeteoClient, OpenMeteoRateLimitError

TODAY = date(2026, 10, 22)


class YearTransport:
    """Answers each archive request with a flat but valid hourly series for the requested dates."""

    def __init__(self, fail_after=None, rate_limit_times=0):
        self.calls, self.fail_after, self.rate_limit_times = [], fail_after, rate_limit_times

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        if self.rate_limit_times:
            self.rate_limit_times -= 1
            raise OpenMeteoRateLimitError("Open-Meteo rate limit exceeded")
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise wd.OpenMeteoRequestError("network failed")
        start = datetime.fromisoformat(params["start_date"]).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(params["end_date"]).replace(tzinfo=timezone.utc) + timedelta(hours=23)
        times, current = [], start
        while current <= end:
            times.append(current.strftime("%Y-%m-%dT%H:%M"))
            current += timedelta(hours=1)
        n = len(times)
        return json.dumps({"latitude": float(params["latitude"]), "longitude": float(params["longitude"]), "elevation": 640.0, "model": "best_match",
                           "hourly": {"time": times, "temperature_2m": [18.5] * n, "relative_humidity_2m": [55] * n, "shortwave_radiation": [120] * n,
                                      "wind_speed_10m": [2.0] * n, "wind_direction_10m": [200] * n, "rain": [0.0] * n, "surface_pressure": [940] * n}}).encode()


@pytest.fixture
def archive(tmp_path):
    return tmp_path / "archive"


def make_client(transport):
    return OpenMeteoClient(transport=transport)


def run(items, transport, **kwargs):
    kwargs.setdefault("pause_seconds", 0)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return wd.execute(items, make_client(transport), **kwargs)


def test_the_locations_file_covers_every_crop_and_says_its_coordinates_are_unconfirmed():
    locations = wd.load_locations()
    for crop in ("tomato", "pepper", "lettuce", "grape", "peach", "plum", "apple"):
        assert crop in wd.location_for_crop(crop, locations).crops
    assert wd.location_for_crop("tomato").id == wd.location_for_crop("pepper").id == "el_ejido_greenhouses"
    assert {location.status for location in locations.values()} == {"APPROXIMATE_ZONE_PENDING_USER_CONFIRMATION"}
    with pytest.raises(wd.WeatherDatasetsError):
        wd.location_for_crop("banana")


def test_plan_never_touches_the_network(archive, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("plan must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    items = wd.plan(None, 2015, 2025, today=TODAY, archive=archive)
    assert len(items) == 6 * 11 and all(item.action == "DOWNLOAD" and item.requests == 1 for item in items)


def test_a_year_that_is_not_complete_cannot_be_planned(archive):
    assert wd.last_complete_year(TODAY) == 2025
    assert wd.last_complete_year(date(2027, 1, 3)) == 2026
    with pytest.raises(wd.WeatherDatasetsError, match="not complete yet"):
        wd.plan(["jumilla_vineyards"], 2015, 2026, today=TODAY, archive=archive)
    with pytest.raises(wd.WeatherDatasetsError, match="unknown locations"):
        wd.plan(["nowhere"], 2015, 2016, today=TODAY, archive=archive)
    with pytest.raises(wd.WeatherDatasetsError):
        wd.plan(None, 2020, 2019, today=TODAY, archive=archive)


def test_download_writes_one_file_per_location_and_year_with_provenance(archive):
    transport = YearTransport()
    report = run(wd.plan(["cieza_orchards"], 2020, 2021, today=TODAY, archive=archive), transport)
    assert report["failed"] is None and len(report["downloaded"]) == 2 and len(transport.calls) == 2
    location = wd.load_locations()["cieza_orchards"]
    assert all(params["latitude"] == str(location.latitude) and params["longitude"] == str(location.longitude) for _, params in transport.calls)
    assert all("archive-api" in url for url, _ in transport.calls)  # the historical archive, not the forecast endpoint
    metadata = json.loads((archive / "cieza_orchards" / "2020.metadata.json").read_text(encoding="utf-8"))
    assert metadata["classification"] == "FORCING" and metadata["complete"] is True and metadata["year"] == 2020 and metadata["crops"] == ["peach"]
    assert metadata["coordinate_status"] == "APPROXIMATE_ZONE_PENDING_USER_CONFIRMATION" and metadata["elevation"] == 640.0 and "never REAL_VERIFIED" in metadata["source_note"]
    provider = CsvWeatherProvider(archive / "cieza_orchards" / "2020.csv")  # the simulation's own reader accepts it
    assert len(provider.timestamps) == 8784 and provider.get(datetime(2020, 2, 29, 12, tzinfo=timezone.utc)).temperature_c == 18.5


def test_a_second_run_downloads_nothing_and_a_new_year_adds_only_that_year(archive):
    run(wd.plan(["cieza_orchards"], 2020, 2021, today=TODAY, archive=archive), YearTransport())
    again = wd.plan(["cieza_orchards"], 2020, 2021, today=TODAY, archive=archive)
    assert [item.action for item in again] == ["PRESENT", "PRESENT"]
    transport = YearTransport()
    later = wd.plan(["cieza_orchards"], 2020, 2022, today=TODAY, archive=archive)
    assert [item.action for item in later] == ["PRESENT", "PRESENT", "DOWNLOAD"]
    report = run(later, transport)
    assert len(transport.calls) == 1 and transport.calls[0][1]["start_date"] == "2022-01-01" and report["skipped_present"] == 2


def test_a_cut_download_keeps_what_it_got_and_resumes(archive):
    items = wd.plan(["cieza_orchards"], 2020, 2022, today=TODAY, archive=archive)
    report = run(items, YearTransport(fail_after=1))
    assert len(report["downloaded"]) == 1 and report["failed"]["year"] == 2021 and report["remaining"] == 1
    assert not (archive / "cieza_orchards" / "2021.csv").exists()  # nothing half-written
    resumed = wd.plan(["cieza_orchards"], 2020, 2022, today=TODAY, archive=archive)
    assert [item.action for item in resumed] == ["PRESENT", "DOWNLOAD", "DOWNLOAD"]


def test_a_rate_limit_waits_and_retries_then_gives_up_cleanly(archive):
    waits = []
    ok = run(wd.plan(["cieza_orchards"], 2020, 2020, today=TODAY, archive=archive), YearTransport(rate_limit_times=1), retry_wait_seconds=7, sleep=waits.append)
    assert ok["failed"] is None and waits == [7]
    bad = run(wd.plan(["jumilla_vineyards"], 2020, 2020, today=TODAY, archive=archive), YearTransport(rate_limit_times=99), retry_wait_seconds=1, retries=2)
    assert "rate limit" in bad["failed"]["error"] and bad["downloaded"] == []


def test_an_incomplete_file_is_downloaded_again(archive):
    run(wd.plan(["cieza_orchards"], 2021, 2021, today=TODAY, archive=archive), YearTransport())
    path = archive / "cieza_orchards" / "2021.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-24]) + "\n", encoding="utf-8")  # a day missing
    assert wd.plan(["cieza_orchards"], 2021, 2021, today=TODAY, archive=archive)[0].action == "DOWNLOAD"


def test_status_reports_coverage_and_what_an_update_would_add(archive):
    run(wd.plan(["cieza_orchards"], 2020, 2022, today=TODAY, archive=archive), YearTransport())
    row = next(item for item in wd.status(archive, today=TODAY) if item["location"] == "cieza_orchards")
    assert row["years"] == [2020, 2021, 2022] and row["coverage"] == [{"from": "2020-01-01T00:00:00+00:00", "to": "2022-12-31T23:00:00+00:00"}]
    assert 2015 in row["missing_years"] and 2025 in row["missing_years"] and row["classification"] == "FORCING"


def test_the_command_line_needs_explicit_confirmation_before_using_the_network(capsys):
    with pytest.raises(SystemExit):
        wd.main(["download", "--locations", "cieza_orchards"])
    assert wd.main(["plan", "--locations", "cieza_orchards", "--start-year", "2024", "--end-year", "2025"]) == 0
    assert '"requests"' in capsys.readouterr().out


def test_the_transport_keeps_tls_verification_on_and_prefers_the_certifi_bundle():
    import ssl

    from agri_twin.infrastructure.open_meteo import UrllibTransport

    context = UrllibTransport()._context
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True
