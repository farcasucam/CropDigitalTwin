from importlib import import_module


_EXPORTS = {
	"CsvWeatherProvider": ("agri_twin.infrastructure.csv_weather", "CsvWeatherProvider"),
	"WeatherDatasetError": ("agri_twin.infrastructure.csv_weather", "WeatherDatasetError"),
	"OpenMeteoApi": ("agri_twin.infrastructure.open_meteo", "OpenMeteoApi"),
	"OpenMeteoClient": ("agri_twin.infrastructure.open_meteo", "OpenMeteoClient"),
	"OpenMeteoAuthConfig": ("agri_twin.infrastructure.open_meteo", "OpenMeteoAuthConfig"),
	"OpenMeteoRequest": ("agri_twin.infrastructure.open_meteo", "OpenMeteoRequest"),
	"OpenMeteoRequestError": ("agri_twin.infrastructure.open_meteo", "OpenMeteoRequestError"),
	"OpenMeteoAuthenticationError": ("agri_twin.infrastructure.open_meteo", "OpenMeteoAuthenticationError"),
	"OpenMeteoRateLimitError": ("agri_twin.infrastructure.open_meteo", "OpenMeteoRateLimitError"),
	"OpenMeteoResponseError": ("agri_twin.infrastructure.open_meteo", "OpenMeteoResponseError"),
	"WeatherModelNotAvailable": ("agri_twin.infrastructure.open_meteo", "WeatherModelNotAvailable"),
	"WeatherRangeNotAvailable": ("agri_twin.infrastructure.open_meteo", "WeatherRangeNotAvailable"),
	"HttpTransport": ("agri_twin.infrastructure.open_meteo", "HttpTransport"),
	"WeatherCache": ("agri_twin.infrastructure.weather_cache", "WeatherCache"),
	"EnergyPlusAvailability": ("agri_twin.infrastructure.energyplus_greenhouse", "EnergyPlusAvailability"),
	"EnergyPlusBackendError": ("agri_twin.infrastructure.energyplus_greenhouse", "EnergyPlusBackendError"),
	"EnergyPlusGreenhouseModel": ("agri_twin.infrastructure.energyplus_greenhouse", "EnergyPlusGreenhouseModel"),
	"EnergyPlusStatus": ("agri_twin.infrastructure.energyplus_greenhouse", "EnergyPlusStatus"),
	"detect_energyplus": ("agri_twin.infrastructure.energyplus_greenhouse", "detect_energyplus"),
}


def __getattr__(name: str):
	try:
		module_name, attribute = _EXPORTS[name]
	except KeyError as exc:
		raise AttributeError(name) from exc
	value = getattr(import_module(module_name), attribute)
	globals()[name] = value
	return value

__all__ = [
	"CsvWeatherProvider",
	"WeatherDatasetError",
	"OpenMeteoApi",
	"OpenMeteoClient",
	"OpenMeteoAuthConfig",
	"OpenMeteoRequest",
	"OpenMeteoRequestError",
	"OpenMeteoAuthenticationError",
	"OpenMeteoRateLimitError",
	"OpenMeteoResponseError",
	"WeatherModelNotAvailable",
	"WeatherRangeNotAvailable",
	"HttpTransport",
	"WeatherCache",
	"EnergyPlusAvailability",
	"EnergyPlusBackendError",
	"EnergyPlusGreenhouseModel",
	"EnergyPlusStatus",
	"detect_energyplus",
]
"""Infrastructure adapters kept separate from the domain."""