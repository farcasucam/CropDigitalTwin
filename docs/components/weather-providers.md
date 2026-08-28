# Weather Providers

## Arquitectura

La meteorología sintética y la meteorología real comparten esta abstracción:

```text
WeatherProvider
    +-- SyntheticWeatherProvider -> WeatherEngine
    +-- CsvWeatherProvider       -> CSV local
```

Las perturbaciones se aplican mediante `ScenarioWeatherProvider`. El dataset
de referencia nunca se modifica.

Open-Meteo solo participa en adquisición explícita:

```text
Open-Meteo -> OpenMeteoClient.download() -> CSV + metadata -> CsvWeatherProvider
```

`WeatherProvider.get()` no realiza HTTP. La simulación con CSV funciona
completamente offline.

## Parcela y cultivo

`src/farm_config.json` es la fuente de identidad, ubicación, suelo, riego,
variedad y etapa inicial de cada parcela. `src/crop_config.json` es el catálogo
de definiciones agronómicas y sus etapas. `FarmConfigRepository` y
`CropConfigRepository` cargan y validan ambos archivos sin hacer HTTP.

La adquisición por parcela se realiza explícitamente con
`download_weather_for_plot()`. El servicio resuelve `plot_id`, valida su
`crop_key` y `current_stage`, y construye el `OpenMeteoRequest` con las
coordenadas de `Plot`; `app.json` solo proporciona la configuración técnica.
La metadata incluye parcela, cultivo, variedad y etapa inicial. La identidad
de cache sigue incluyendo las coordenadas, por lo que dos parcelas no
comparten silenciosamente un dataset.

```text
FarmConfigRepository -> Plot -> CropConfigRepository -> CropDefinition
    -> OpenMeteoClient -> CSV -> CsvWeatherProvider -> WeatherState
```

La fuente de simulación se selecciona con `weather.provider` en
`config/app.json`: `synthetic` mantiene el comportamiento anterior y `csv`
requiere `weather.dataset.path`. `open_meteo` solo prepara la adquisición; no
es un provider HTTP de runtime ni descarga automáticamente.

La configuración puede cargarse y convertirse en cliente/request sin efectos
de red:

```python
configuration = load_weather_source_configuration("config/app.json")
client = build_open_meteo_client(configuration.open_meteo)
request = build_open_meteo_request(configuration.open_meteo, start_date, end_date)
client.download(request, output_csv, use_cache=True)
```

La sección `open_meteo` admite endpoint, autenticación `public`/`customer`,
`api_key_env`, timeout, ubicación, modelo, timezone UTC, unidades, variables,
cache y `chunk_days`. El valor de `OPEN_METEO_API_KEY` solo se resuelve al
realizar la descarga customer.

## CSV

El formato estable contiene exactamente:

```text
timestamp,temperature_c,relative_humidity_pct,solar_radiation_w_m2,wind_speed_m_s,wind_direction_deg,rain_rate_mm_h,pressure_hpa
```

Los timestamps deben ser ISO-8601 timezone-aware. Se normalizan a UTC. Las
consultas requieren coincidencia exacta; un timestamp inexistente produce
`WeatherTimestampNotAvailable`. No se interpola ni se usa el vecino más
cercano.

La radiación del CSV se conserva literalmente. No se aplica la regla nocturna
del `WeatherEngine` sintético.

## Variables Open-Meteo

| Open-Meteo | Interna | Unidad |
|---|---|---|
| `temperature_2m` | `temperature_c` | °C |
| `relative_humidity_2m` | `relative_humidity_pct` | % |
| `shortwave_radiation` | `solar_radiation_w_m2` | W/m² |
| `wind_speed_10m` | `wind_speed_m_s` | m/s, solicitando `wind_speed_unit=ms` |
| `wind_direction_10m` | `wind_direction_deg` | grados |
| `surface_pressure` | `pressure_hpa` | hPa |
| `rain` | `rain_rate_mm_h` | acumulado de la hora anterior, normalizado como mm/h |

`rain` no es una medición instantánea. `snowfall`, `precipitation`, `showers`
y probabilidades no se añaden todavía a `WeatherState`.

## Adquisición

```python
request = OpenMeteoRequest(
    latitude=40.0,
    longitude=-3.0,
    start_date=date(2025, 1, 1),
    end_date=date(2025, 12, 31),
    variables=DEFAULT_VARIABLES,
    api=OpenMeteoApi.HISTORICAL,
    model="auto",
)
OpenMeteoClient().download(request, "data/weather/location.csv")
```

Se soportan `historical` y `forecast`. `forecast` valida el horizonte máximo
de 16 días. `archived_forecast`, `previous_runs` y `single_runs` están
representados en la API, pero requieren endpoints y contratos específicos
antes de implementarse.

La API key opcional se obtiene de `OPEN_METEO_API_KEY` y solo se envía cuando
se configura un endpoint customer. Nunca se guarda en CSV, metadata o logs.
El modo `public` usa `https://api.open-meteo.com/v1/forecast`; el modo
`customer` usa `https://customer-api.open-meteo.com/v1/forecast` y exige la
variable configurada en `key_env`.

## Cache y escenarios

`OpenMeteoClient.download(..., use_cache=True)` reutiliza únicamente un CSV y
metadata compatibles. `force_refresh=True` fuerza una nueva adquisición de
forma explícita. `WeatherCache.is_compatible(request)` compara ubicación, API, tipo, modelo,
variables, rango, timezone, resolución y unidades. Un dataset compatible se
reutiliza sin HTTP. La metadata conserva endpoint, modelo solicitado y
devuelto, momento de adquisición y referencia del forecast cuando la API la
proporciona.

Los rangos pueden dividirse de forma determinista con
`OpenMeteoRequest(chunk_days=N)`. Las respuestas se consolidan ordenadas, sin
duplicados y con continuidad horaria; una discontinuidad invalida la descarga.

```python
reference = CsvWeatherProvider("weather.csv")
scenario = ScenarioWeatherProvider(reference)
scenario.add_perturbation(rain_event)
```

Si el CSV contiene `rain_rate_mm_h=0` y el evento contiene `rate_mm_h=8`, el
escenario devuelve `8` y el provider de referencia continúa devolviendo `0`.

## Clock y Scheduler

`SimulationClock` solo proporciona el tiempo simulado. `SimulationScheduler`
puede invocar `provider.get(simulation_time)`, pero ninguno de los dos conoce
Open-Meteo ni realiza HTTP.