# Phase 5.43: local historical weather datasets

Status: **DONE for steps A-E (software qualification only)**. Nothing here claims calibration or validation.

## Why

The interactive simulator runs on `SYNTHETIC_SEASONAL` weather and one synthetic cycle per crop. To simulate real past periods (other years, other planting dates, several
cycles per year for short crops such as lettuce) it needs real weather available offline. This step downloads it once, explicitly, and keeps it local.

## What it is, and what it is not

* Source: the Open-Meteo **historical archive** API, a modelled reanalysis (not station data). Variables: temperature, relative humidity, shortwave radiation, wind speed
  and direction, rain, surface pressure, hourly, UTC.
* Classification: `FORCING`. These data are never `REAL_VERIFIED` and are not used to calibrate or validate anything (see `docs/scientific-limitations.md`).
* Attribution: weather data by Open-Meteo.com. Check its current licence terms before redistributing the data.
* The reanalysis grid is coarse (about 10-25 km). The elevation of the grid cell used is stored in each file's metadata and can differ from the parcel's.

## Locations (`src/weather_locations.json`)

| Id | Area | Crops | Point |
|---|---|---|---|
| `jumilla_vineyards` | Jumilla (Murcia), wine-growing plain | grape | 38.44, -1.25 |
| `cieza_orchards` | Cieza (Murcia), Segura valley orchards | peach | 38.27, -1.40 |
| `el_ejido_greenhouses` | El Ejido (Almeria), Campo de Dalias greenhouses | tomato, pepper | 36.77, -2.77 |
| `mazarron_coast_fields` | Mazarron coast (Murcia), irrigated fields | lettuce | 37.58, -1.32 |
| `zaragoza_fruit_valley` | Zaragoza, Jalon valley fruit area (Calatayud) | plum | 41.35, -1.63 |
| `burgo_de_osma_orchards` | El Burgo de Osma (Soria), river-valley orchards | apple | 41.57, -3.05 |

The points were chosen inside traditional growing areas, not town centres, from general geographic knowledge and are **not verified against real parcels**
(`coordinate_status = APPROXIMATE_ZONE_PENDING_USER_CONFIRMATION`, copied into every file's metadata). Refine them in the JSON and re-download if the exact area matters.

## Layout and incremental updates

One file per location and calendar year: `data/weather/archive/<location>/<year>.csv` plus `<year>.metadata.json` (endpoint, coordinates, elevation, retrieval time,
`complete`, classification, source note). A year is *complete* when its file holds every hour of that year; the current year is never downloaded. Adding a new year
is a new file: `update` fetches only what is missing, and an interrupted download resumes (nothing half-written is kept).

```powershell
$env:PYTHONPATH = "src"
python -m agri_twin.infrastructure.weather_archive plan   --start-year 2015 --end-year 2025   # what would be downloaded; no network
python -m agri_twin.infrastructure.weather_archive status                                    # what is on disk; no network
python -m agri_twin.infrastructure.weather_archive download --start-year 2015 --end-year 2025 --confirm-network
python -m agri_twin.infrastructure.weather_archive update --confirm-network                  # next year(s) once they are complete
```

`download` and `update` refuse to run without `--confirm-network`. They make one request per location and year, pause between requests, wait and retry on a rate
limit and stop cleanly at the first failure. The CSV files are not versioned (tens of MB, reproducible with the command above); the `.metadata.json` files are.

## Use in simulations (steps B and C)

A request may carry `weather: {source: "LOCAL_ARCHIVE", campaign_start: "<planting day, midnight UTC>"}` (`SYNTHETIC_SEASONAL` stays the default and is unchanged, hashes included).

* **Planting date.** Annual crops (tomato, pepper, lettuce) start on any day inside the downloaded years, so a short crop such as lettuce (42-day cycle) can run several cycles in one
  year, one request each. Perennial crops (grape, peach, plum, apple) start on their own season day (`MM-DD` of their dormancy cycle) of any covered year, because their initial
  state is a dormant tree: another day is rejected with that explanation.
* **Length.** The crop's synthetic cycle length, or until the downloaded data end if they end first (stated in the configuration as `cycle_truncated_by_data`). `end_time` can only shorten it.
* **Weather.** The hourly files of the crop's location, read exactly; an hour that was not downloaded is an error, never an estimate. Scenario events (heat wave, rain...) are still applied on top.
  `profile_overrides` shape the synthetic generator only and are rejected here.
* **Checkpoints.** The planting date and the provenance of the files (retrieval time, coordinates) are part of the resume identity: a checkpoint never resumes under other weather. Prefix plus
  resumed baseline equals the continuous run (tested on local weather).
* **Where it lives.** `application/weather_datasets.py` (offline and clock-free: locations, coverage, fingerprint, provider) and `infrastructure/weather_archive.py` (acquisition: network, clock, pauses).
  The project's static audit forbids clock and sleeps in `application/`, which is why they are split.
* **Interface (`/bench`).** "Weather source" in the scenario group: synthetic cycle or real weather, a planting date (or a season year for perennial crops), the location and coverage, and the notes that it
  is reanalysis forcing for an approximate area. The capabilities endpoint lists, per crop, what is available.

## Event plausibility from the real climate (step E)

`GET /api/weather/climatology?crop=<crop>` returns, for the crop's location, the 5, 50 and 95 % percentiles of the **daily mean temperature** by calendar day, pooled over +-7 days of
each date and over every downloaded year (offline, cached until the files change; `weather_datasets.climatology`). With real weather selected, a cold or heat wave is flagged on its card, its
bar and its tooltip when the daily mean it would produce (the run's baseline daily mean, or the median of that date before any run, minus or plus the event's intensity) falls outside the
5-95 % range seen on that date: a -8 degC cold wave in August on the Mazarron coast would give about 19 degC against a 5 % lowest of 24 degC. It is a hint, never a block, and the 5-95 % cut-offs are a
convention. Magnitude matters: a large heat wave in summer is flagged too if it exceeds what was seen. With the synthetic cycle (no climatology) the earlier hint relative to the run's own weather remains.

## Notes

* TLS verification stays on. When the `certifi` bundle is installed the transport uses it: the Windows certificate store held an expired root in the chain and Python
  rejected the valid server while other clients accepted it.
* The simulation never uses the network: it reads these local files through `CsvWeatherProvider`.

## Tests

`tests/test_weather_datasets.py` (acquisition, offline, fake transport) and `tests/test_local_weather_simulation.py` (simulations on a small temporary archive: exact use of the hours, planting dates,
validation, truncation, resume identity, what-if equivalence, no network or clock in the simulation-side module): plan without a socket, one file per location and year with provenance, incremental update, resume after a
cut, rate-limit retry, incomplete file detection, coverage status, explicit network confirmation, TLS verification on.
