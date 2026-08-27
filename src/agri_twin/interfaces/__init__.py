"""External adapters for application services."""

from agri_twin.interfaces.clock_mqtt import SimulationClockMQTTAdapter
from agri_twin.interfaces.weather_mqtt import WeatherMQTTAdapter

__all__ = ["SimulationClockMQTTAdapter", "WeatherMQTTAdapter"]
