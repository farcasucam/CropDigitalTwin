"""Pure domain models. This package has no infrastructure dependencies."""

from agri_twin.domain.crop import (
    CropConfigRepository,
    CropConfigurationError,
    CropDefinition,
    CropStageDefinition,
)
from agri_twin.domain.crop_engine import CropEngine, CropEngineError
from agri_twin.domain.phenology_configuration import (
    PhenologyConfigurationError,
    validate_phenology_configuration,
)
from agri_twin.domain.digital_twin import CropDigitalTwinState
from agri_twin.domain.farm import (
    FarmConfigRepository,
    FarmConfigurationError,
    Plot as FarmPlot,
    PlotLocation,
)
from agri_twin.domain.growth_configuration import (
    GrowthModelConfigurationError,
    GrowthModelConfigurationRepository,
)
from agri_twin.domain.phenology import (
    PhenologyEngine,
    PhenologyError,
    PhenologyEvidenceLevel,
    PhenologyProfile,
)

from agri_twin.domain.models import (
    ActuatorState,
    CropState,
    CropGrowthState,
    DerivedEnvironmentState,
    Plot,
    SimulationState,
    SoilState,
    WeatherState,
)
from agri_twin.domain.weather import (
    HumidityConfiguration,
    PressureConfiguration,
    RadiationConfiguration,
    TemperatureConfiguration,
    WeatherConfiguration,
    WeatherEngineValueError,
    WeatherEventType,
    WeatherPerturbation,
    WeatherSimulationConfiguration,
    WindConfiguration,
)

__all__ = [
    "ActuatorState",
    "CropState",
    "CropGrowthState",
    "DerivedEnvironmentState",
    "Plot",
    "SimulationState",
    "SoilState",
    "WeatherState",
    "HumidityConfiguration",
    "PressureConfiguration",
    "RadiationConfiguration",
    "TemperatureConfiguration",
    "WeatherConfiguration",
    "WeatherEngineValueError",
    "WeatherEventType",
    "WeatherPerturbation",
    "WeatherSimulationConfiguration",
    "WindConfiguration",
    "CropConfigRepository",
    "CropConfigurationError",
    "CropDefinition",
    "CropStageDefinition",
    "CropEngine",
    "CropEngineError",
    "PhenologyConfigurationError",
    "validate_phenology_configuration",
    "CropDigitalTwinState",
    "FarmConfigRepository",
    "FarmConfigurationError",
    "FarmPlot",
    "PlotLocation",
    "GrowthModelConfigurationError",
    "GrowthModelConfigurationRepository",
    "PhenologyEngine",
    "PhenologyError",
    "PhenologyEvidenceLevel",
    "PhenologyProfile",
]