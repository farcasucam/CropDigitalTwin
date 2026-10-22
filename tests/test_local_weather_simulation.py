"""Phase 5.43 (steps B and C): simulations on the local weather archive and a free planting date. Offline: a small synthetic archive in a temporary directory."""

from __future__ import annotations

import ast
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application import weather_datasets as wd
from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import InteractiveSimulationService, SimulationApiError, canonicalize_request
from agri_twin.infrastructure.csv_weather import COLUMNS

YEARS = (2019, 2020)
OPTIONS = {"include_trajectory": True, "compute_trajectory_hash": True}


def write_year(archive: Path, location: str, year: int, retrieved: str = "2026-10-22T10:00:00Z") -> None:
    folder = archive / location
    folder.mkdir(parents=True, exist_ok=True)
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    rows = [",".join(COLUMNS)]
    for hour in range(24 * ((date(year, 12, 31) - date(year, 1, 1)).days + 1)):
        moment = start + timedelta(hours=hour)
        doy = moment.timetuple().tm_yday
        temperature = 16.0 + 9.0 * math.sin(2 * math.pi * (doy - 105) / 365) + 4.0 * math.sin(2 * math.pi * (moment.hour - 9) / 24)
        sun = max(0.0, math.sin(math.pi * (moment.hour - 6) / 12)) * (450.0 + 300.0 * math.sin(2 * math.pi * (doy - 80) / 365))
        rows.append(f"{moment.isoformat()},{temperature:.2f},55,{sun:.1f},2.5,200,0.0,1000")
    (folder / f"{year}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (folder / f"{year}.metadata.json").write_text(json.dumps({"complete": True, "year": year, "retrieved_at": retrieved, "latitude": 37.58, "longitude": -1.32, "elevation": 99.0,
                                                               "endpoint": "https://archive-api.open-meteo.com/v1/archive"}), encoding="utf-8")


@pytest.fixture
def archive(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    for location in ("mazarron_coast_fields", "cieza_orchards"):  # lettuce and peach; tomato (El Ejido) has no data on purpose
        for year in YEARS:
            write_year(root, location, year)
    monkeypatch.setattr(wd, "ARCHIVE_DIR", root)
    return root


def request(crop="lettuce", start="2019-03-01T00:00:00+00:00", **extra):
    return {"crop": crop, "environment": "outdoor", "weather": {"source": "LOCAL_ARCHIVE", "campaign_start": start}, "options": OPTIONS, **extra}


def code(call):
    with pytest.raises(SimulationApiError) as caught:
        call()
    return caught.value.to_dict()["errors"][0]


def test_a_run_uses_the_downloaded_hours_and_the_chosen_planting_date(archive):
    response = InteractiveSimulationService().run_simulation(request())
    assert response.execution_status.value == "COMPLETED"
    trajectory = response.result.trajectory
    assert trajectory["time"][0].startswith("2019-03-01T01") and trajectory["time"][-1].startswith("2019-04-12")  # lettuce cycle: 42 days from the planting date
    provider = wd.ArchiveWeatherProvider("mazarron_coast_fields")
    assert trajectory["temperature_c"][0] == provider.get(datetime(2019, 3, 1, 1, tzinfo=timezone.utc)).temperature_c  # outdoors the crop sees the archive hour exactly
    assert trajectory["radiation_w_m2"][12] == provider.get(datetime(2019, 3, 1, 13, tzinfo=timezone.utc)).solar_radiation_w_m2


def test_two_cycles_of_a_short_crop_fit_in_one_year_and_differ(archive):
    service = InteractiveSimulationService()
    spring, autumn = (service.run_simulation(request(start=day)) for day in ("2019-03-01T00:00:00+00:00", "2019-09-15T00:00:00+00:00"))
    assert spring.result.trajectory["time"][0][:7] == "2019-03" and autumn.result.trajectory["time"][0][:7] == "2019-09"
    assert spring.result.trajectory_hash != autumn.result.trajectory_hash
    assert max(autumn.result.trajectory["temperature_c"]) > max(spring.result.trajectory["temperature_c"])


def test_the_same_request_gives_the_same_trajectory(archive):
    service = InteractiveSimulationService()
    assert service.run_simulation(request()).result.trajectory_hash == service.run_simulation(request()).result.trajectory_hash


def test_a_cycle_that_outlasts_the_data_stops_where_the_data_end(archive):
    response = InteractiveSimulationService().run_simulation(request(start="2020-12-10T00:00:00+00:00"))
    assert response.result.trajectory["time"][-1].startswith("2020-12-31T23")
    assert response.effective_configuration["weather"]["dataset"]["cycle_truncated_by_data"] is True
    assert code(lambda: canonicalize_request(request(start="2020-12-10T00:00:00+00:00", end_time="2021-01-20T00:00:00+00:00")))["code"] == "INVALID_TIME_RANGE"


@pytest.mark.parametrize("document, error_code, path", [
    ({"crop": "lettuce", "weather": {"source": "LOCAL_ARCHIVE"}}, "INVALID_REQUEST", "weather.campaign_start"),
    (request(start="2015-03-01T00:00:00+00:00"), "INVALID_TIME_RANGE", "weather.campaign_start"),
    (request(start="2021-03-01T00:00:00+00:00"), "INVALID_TIME_RANGE", "weather.campaign_start"),
    (request(start="2019-03-01T06:00:00+00:00"), "INVALID_TIME_RANGE", "weather.campaign_start"),
    (request(crop="peach", start="2019-06-01T00:00:00+00:00"), "INVALID_TIME_RANGE", "weather.campaign_start"),
    (request(crop="tomato", environment="greenhouse"), "MODEL_NOT_READY", "weather.source"),
    ({"crop": "lettuce", "weather": {"source": "SYNTHETIC_SEASONAL", "campaign_start": "2019-03-01T00:00:00+00:00"}}, "INVALID_REQUEST", "weather.campaign_start"),
    ({"crop": "lettuce", "weather": {"source": "LOCAL_ARCHIVE", "campaign_start": "2019-03-01T00:00:00+00:00", "profile_overrides": {"temperature_mean_c": 3}}}, "INVALID_CONFIGURATION", "weather.profile_overrides"),
])
def test_invalid_local_weather_requests_are_structured_errors(archive, document, error_code, path):
    error = code(lambda: canonicalize_request(document))
    assert (error["code"], error["path"]) == (error_code, path)


def test_a_perennial_season_starts_on_its_own_day_of_any_covered_year(archive):
    for year in YEARS:
        canonical = canonicalize_request(request(crop="peach", start=f"{year}-02-01T00:00:00+00:00"))
        assert canonical.campaign_start.year == year and canonical.campaign_end <= datetime(year, 12, 31, 23, tzinfo=timezone.utc)


def test_checkpoints_belong_to_the_planting_date_and_the_exact_files(archive):
    base = canonicalize_request(request())
    assert canonicalize_request(request(start="2019-03-05T00:00:00+00:00")).resume_hash != base.resume_hash  # another planting date
    assert canonicalize_request(request()).resume_hash == base.resume_hash
    write_year(archive, "mazarron_coast_fields", 2019, retrieved="2027-01-01T00:00:00Z")  # re-downloaded: other provenance
    assert canonicalize_request(request()).resume_hash != base.resume_hash
    assert "dataset" not in canonicalize_request({"crop": "lettuce"}).resume_identity()  # the synthetic default is unchanged


def test_a_what_if_runs_on_local_weather_and_prefix_plus_baseline_equals_the_continuous_run(archive):
    base = request()
    plain = InteractiveSimulationService().run_simulation(base).result.trajectory
    event = {"event_type": "HEAT_WAVE", "start_simulation_time": "2019-03-20T00:00:00+00:00", "duration_hours": 48, "intensity": 8}
    result = InteractiveRuntimeService().what_if({"request": {k: v for k, v in base.items() if k != "options"}, "checkpoint_time": "2019-03-10T00:00:00+00:00", "events": [event]})
    prefix = result["prefix"]["result"]["trajectory"]
    baseline = result["branches"]["baseline"]["response"]["result"]["trajectory"]
    keep = [index for index, time in enumerate(baseline["time"]) if time > prefix["time"][-1]]
    for name in ("time", "temperature_c", "biomass_total_g_m2", "soil_water_vwc_m3_m3"):
        assert prefix[name] + [baseline[name][index] for index in keep] == plain[name], name
    assert result["hashes"]["intervention_trajectory_hash"] != result["hashes"]["baseline_trajectory_hash"]


def test_the_configuration_says_what_the_weather_is(archive):
    response = InteractiveSimulationService().run_simulation(request())
    weather = response.effective_configuration["weather"]
    assert weather["classification"] == "FORCING" and "never REAL_VERIFIED" in weather["kind"]
    assert weather["dataset"]["location_id"] == "mazarron_coast_fields" and len(weather["dataset"]["fingerprint"]) == 64
    assert weather["dataset"]["coordinates"]["coordinate_status"] == "APPROXIMATE_ZONE_PENDING_USER_CONFIRMATION"


def test_the_capabilities_list_what_each_crop_can_run_on(archive):
    from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter

    crops = InteractiveFrontendAdapter.weather_datasets()["crops"]
    assert crops["lettuce"]["available"] is True and crops["lettuce"]["years"] == list(YEARS) and crops["lettuce"]["cycle_days"] == 42 and crops["lettuce"]["perennial"] is False
    assert crops["peach"]["perennial"] is True and crops["peach"]["cycle_start_month_day"] == "02-01"
    assert crops["tomato"]["available"] is False


def test_simulation_modules_never_import_the_network_or_the_clock_for_weather():
    root = Path(wd.__file__)
    imports = {alias.name for node in ast.walk(ast.parse(root.read_text(encoding="utf-8"))) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])}
    assert not {name for name in imports if name.split(".")[0] in {"urllib", "socket", "http", "requests", "time"} or "open_meteo" in name}
    assert "datetime.now" not in root.read_text(encoding="utf-8") and "sleep(" not in root.read_text(encoding="utf-8")


def test_climatology_gives_ordered_percentiles_by_calendar_day_from_the_downloaded_years(archive):
    clim = wd.climatology("lettuce")
    assert clim["years"] == list(YEARS) and clim["classification"] == "FORCING" and clim["window_days"] == 7 and len(clim["p05"]) == len(clim["p50"]) == len(clim["p95"]) == 366
    assert all(low <= mid <= high for low, mid, high in zip(clim["p05"], clim["p50"], clim["p95"]))
    summer, winter = date(2000, 8, 15).timetuple().tm_yday - 1, date(2000, 1, 15).timetuple().tm_yday - 1
    assert clim["p50"][summer] > clim["p50"][winter] + 10  # the archive's own seasonal cycle comes out
    assert wd.climatology("tomato") is None  # no data for El Ejido in this archive


def test_the_climatology_is_cached_until_the_files_change(archive):
    first = wd.climatology("lettuce")
    assert wd.climatology("lettuce") == first
    write_year(archive, "mazarron_coast_fields", 2019, retrieved="2027-02-02T00:00:00Z")
    assert wd.climatology("lettuce")["fingerprint"] != first["fingerprint"]


def test_the_climatology_endpoint_serves_it_and_refuses_crops_without_data(archive):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from agri_twin.interfaces.frontend_api import FrontendRequestHandler, InteractiveFrontendAdapter

    class Handler(FrontendRequestHandler):
        adapter = InteractiveFrontendAdapter()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/weather/climatology?crop=lettuce", timeout=30) as response:
            payload = json.loads(response.read())
        assert payload["location_id"] == "mazarron_coast_fields" and len(payload["p95"]) == 366
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(base + "/api/weather/climatology?crop=tomato", timeout=30)
        assert caught.value.code == 404
    finally:
        server.shutdown()
