# Phase 5.43: local historical weather datasets

Status: **IN PROGRESS (step A done: acquisition and offline queries)**. Steps B-E (use in the interactive simulator, choice of cycle period and planting date, interface,
real-climate plausibility of events) are not done. Nothing here claims calibration or validation.

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
python -m agri_twin.application.weather_datasets plan   --start-year 2015 --end-year 2025   # what would be downloaded; no network
python -m agri_twin.application.weather_datasets status                                    # what is on disk; no network
python -m agri_twin.application.weather_datasets download --start-year 2015 --end-year 2025 --confirm-network
python -m agri_twin.application.weather_datasets update --confirm-network                  # next year(s) once they are complete
```

`download` and `update` refuse to run without `--confirm-network`. They make one request per location and year, pause between requests, wait and retry on a rate
limit and stop cleanly at the first failure. The CSV files are not versioned (tens of MB, reproducible with the command above); the `.metadata.json` files are.

## Notes

* TLS verification stays on. When the `certifi` bundle is installed the transport uses it: the Windows certificate store held an expired root in the chain and Python
  rejected the valid server while other clients accepted it.
* The simulation never uses the network: it reads these local files through `CsvWeatherProvider`.

## Tests

`tests/test_weather_datasets.py` (offline, fake transport): plan without a socket, one file per location and year with provenance, incremental update, resume after a
cut, rate-limit retry, incomplete file detection, coverage status, explicit network confirmation, TLS verification on.
