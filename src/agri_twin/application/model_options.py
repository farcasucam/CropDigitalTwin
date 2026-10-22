"""Optional physical-model choices of an interactive simulation (request block ``model_options``).

Every option defaults to the historical behaviour, and a request that does not use them has no block, so earlier requests, hashes and checkpoints do not move.

* ``et0_method``: ``HARGREAVES_HISTORICAL`` (default: temperature and radiation only, fixed temperature range, no wind or humidity) or ``PENMAN_MONTEITH_FAO56``
  (FAO-56 hourly: radiation, temperature, humidity, wind and pressure; needs the site, which comes from the weather location or the plot, never from a default).
* ``co2_response``: ``HISTORICAL_CAPPED`` (default: ``min(1, CO2/420)``, enrichment gives no benefit) or ``LOG_RELATIVE_GAIN`` (growth factor 1 at 420 ppm and 1 + gain at twice that, logarithmic; the gain per doubling
  comes from ``src/co2_response.json``, a generic C3 literature value with its citation and status, or from the request's ``co2_gain_per_doubling``).
* ``indoor_wind_m_s``: air speed inside a greenhouse for the Penman-Monteith aerodynamic term (default 0: still air; the outdoor wind does not reach the crop). The user's value, not a model value.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from agri_twin.domain.co2_response import LogarithmicCo2Response
from agri_twin.domain.evapotranspiration import Et0Site, EvapotranspirationError, PenmanMonteithEt0
from agri_twin.domain.farm import FarmConfigRepository

OPTION_FIELDS = ("et0_method", "indoor_wind_m_s", "co2_response", "co2_gain_per_doubling")
CO2_RESPONSES = ("HISTORICAL_CAPPED", "LOG_RELATIVE_GAIN")
DEFAULT_CO2 = CO2_RESPONSES[0]
CO2_FILE = Path(__file__).resolve().parents[2] / "co2_response.json"
ET0_METHODS = ("HARGREAVES_HISTORICAL", "PENMAN_MONTEITH_FAO56")
DEFAULT_ET0 = ET0_METHODS[0]
FARM_CONFIG = Path(__file__).resolve().parents[3] / "src" / "farm_config.json"
OPEN_METEO_WIND_HEIGHT_M = 10.0  # the local archive stores Open-Meteo wind_speed_10m
SYNTHETIC_WIND_HEIGHT_M = 2.0    # the synthetic generator defines no measurement height: it is taken as the FAO-56 reference height (no conversion)


class ModelOptionsError(ValueError):
    def __init__(self, message: str, path: str, kind: str = "INVALID_REQUEST") -> None:
        super().__init__(message)
        self.message, self.path, self.kind = message, path, kind


@dataclass(frozen=True, slots=True)
class ModelOptions:
    et0_method: str = DEFAULT_ET0
    indoor_wind_m_s: float = 0.0
    co2_response: str = DEFAULT_CO2
    co2_gain_per_doubling: float | None = None  # None: the value of src/co2_response.json

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {}
        if self.et0_method != DEFAULT_ET0:
            document["et0_method"] = self.et0_method
        if self.indoor_wind_m_s:
            document["indoor_wind_m_s"] = self.indoor_wind_m_s
        if self.co2_response != DEFAULT_CO2:
            document["co2_response"] = self.co2_response
        if self.co2_gain_per_doubling is not None:
            document["co2_gain_per_doubling"] = self.co2_gain_per_doubling
        return document


def parse_model_options(document: Any, environment: str) -> ModelOptions | None:
    """``None`` when the block is absent or states only defaults (the canonical request then has no block)."""
    if document is None:
        return None
    if not isinstance(document, Mapping):
        raise ModelOptionsError("model_options must be a mapping", "model_options")
    unknown = sorted(set(document) - set(OPTION_FIELDS))
    if unknown:
        raise ModelOptionsError(f"unknown model option {unknown[0]!r}; allowed: {', '.join(OPTION_FIELDS)}", f"model_options.{unknown[0]}")
    method = str(document.get("et0_method", DEFAULT_ET0)).upper()
    if method not in ET0_METHODS:
        raise ModelOptionsError(f"et0_method {method!r} is not available; choose one of {', '.join(ET0_METHODS)}", "model_options.et0_method")
    wind = document.get("indoor_wind_m_s", 0.0)
    if isinstance(wind, bool) or not isinstance(wind, (int, float)) or not math.isfinite(wind) or not 0.0 <= wind <= 20.0:
        raise ModelOptionsError("indoor_wind_m_s must be a number between 0 and 20", "model_options.indoor_wind_m_s")
    if wind and (method != "PENMAN_MONTEITH_FAO56" or environment != "greenhouse"):
        raise ModelOptionsError("indoor_wind_m_s applies to the Penman-Monteith ET0 inside a greenhouse", "model_options.indoor_wind_m_s", "UNSUPPORTED_ENVIRONMENT")
    co2 = str(document.get("co2_response", DEFAULT_CO2)).upper()
    if co2 not in CO2_RESPONSES:
        raise ModelOptionsError(f"co2_response {co2!r} is not available; choose one of {', '.join(CO2_RESPONSES)}", "model_options.co2_response")
    gain = document.get("co2_gain_per_doubling")
    if gain is not None:
        if co2 != "LOG_RELATIVE_GAIN":
            raise ModelOptionsError("co2_gain_per_doubling applies to the LOG_RELATIVE_GAIN response", "model_options.co2_gain_per_doubling", "UNSUPPORTED_ENVIRONMENT")
        if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain) or not 0.0 <= gain <= 1.0:
            raise ModelOptionsError("co2_gain_per_doubling must be a number between 0 and 1 (relative gain of growth for a doubling of CO2)", "model_options.co2_gain_per_doubling")
        gain = float(gain)
    options = ModelOptions(method, float(wind), co2, gain)
    return options if options.to_dict() else None


def et0_site(request: Any) -> tuple[Et0Site, str]:
    """(site, where it comes from) of a request: the weather location of a local archive run, else the plot of the farm configuration. Never a default."""
    if request.dataset:
        from agri_twin.application.weather_datasets import dataset_info

        info = dataset_info(request.crop)
        if info is not None:
            return Et0Site(info.location.latitude, info.location.longitude), f"weather location {info.location.id} ({info.location.status})"
    try:
        plot = next(item for item in FarmConfigRepository(FARM_CONFIG).plots if item.plot_id == request.plot)
        return Et0Site(float(plot.latitude), float(plot.longitude), None if plot.elevation is None else float(plot.elevation)), f"plot {request.plot} of the farm configuration"
    except (StopIteration, AttributeError, TypeError, ValueError, OSError):
        raise ModelOptionsError(f"Penman-Monteith needs the site's coordinates and plot {request.plot!r} has none in the farm configuration: use the local weather archive or add them",
                                "model_options.et0_method", "INVALID_CONFIGURATION") from None


def water_engine_factory(request: Any) -> Callable[[Any, Any], Any] | None:
    """Builds the water balance of a run (None: the historical engine)."""
    options = request.model_options
    if options is None or options.et0_method == DEFAULT_ET0:
        return None
    from agri_twin.domain.water_balance import WaterBalanceEngine

    site, _ = et0_site(request)
    height = OPEN_METEO_WIND_HEIGHT_M if request.dataset else SYNTHETIC_WIND_HEIGHT_M
    return lambda _scenario, weather: WaterBalanceEngine(et0=PenmanMonteithEt0(site, height, lambda label: weather.generate(label).solar_radiation_w_m2, options.indoor_wind_m_s))


def co2_constants() -> Mapping[str, Any]:
    return json.loads(CO2_FILE.read_text(encoding="utf-8"))


def co2_response_function(request: Any) -> Callable[[float], float] | None:
    """The growth response to CO2 of a run (None: the historical min(1, CO2/420))."""
    options = request.model_options
    if options is None or options.co2_response == DEFAULT_CO2:
        return None
    constants = co2_constants()
    gain = options.co2_gain_per_doubling if options.co2_gain_per_doubling is not None else float(constants["relative_gain_per_doubling"])
    return LogarithmicCo2Response(gain, float(constants["reference_co2_ppm"]))


def describe_co2(request: Any) -> dict[str, Any]:
    options = request.model_options
    if options is None or options.co2_response == DEFAULT_CO2:
        return {"co2_response": DEFAULT_CO2, "formula": "min(1, CO2 / 420): depletion limits growth, enrichment above 420 ppm gives no benefit"}
    constants = co2_constants()
    user = options.co2_gain_per_doubling is not None
    return {"co2_response": options.co2_response, "formula": constants["functional_form"],
            "relative_gain_per_doubling": options.co2_gain_per_doubling if user else constants["relative_gain_per_doubling"],
            "gain_origin": "USER_SUPPLIED (request)" if user else f"{constants['status']}: {constants['source']['citation']} (doi {constants['source']['doi']})",
            "confidence_interval_99_9_of_the_source": None if user else constants["confidence_interval_99_9"], "assumptions": constants["assumptions_not_in_the_source"]}


def describe(request: Any) -> dict[str, Any]:
    options = request.model_options
    method = options.et0_method if options is not None else DEFAULT_ET0
    if method == DEFAULT_ET0:
        return {"et0_method": method, "formula": "Hargreaves-like: 0.0023 (T + 17.8) sqrt(10) Rs; fixed temperature range, no wind, humidity or pressure term"}
    site, origin = et0_site(request)
    return {"et0_method": method, "reference": "FAO-56 (Allen et al., 1998) hourly Penman-Monteith, equations 53, 28, 37, 39-40, 45-47",
            "site": {"latitude": site.latitude_deg, "longitude": site.longitude_deg, "elevation_m": site.elevation_m, "origin": origin},
            "wind": {"height_m": OPEN_METEO_WIND_HEIGHT_M if request.dataset else SYNTHETIC_WIND_HEIGHT_M, "indoor_m_s": options.indoor_wind_m_s,
                     "note": "converted to 2 m with FAO-56 eq. 47; the synthetic generator defines no height (taken as 2 m); indoors the air speed is the user's value (default still air)"},
            "cloudiness": "Rs/Rso from the outdoor radiation, clipped to 0.3-1.0; at night the value two hours before the last sunlit hour",
            "limits": ["grass reference ET0 only: the crop coefficient is the model's LAI and stage factor (not FAO Kc)", "not calibrated or validated against lysimeter or station data",
                       "inside a greenhouse the equation is applied with the crop's indoor microclimate and the user's air speed, outside its validated open-field domain"]}


__all__ = ["co2_response_function", "describe_co2", "ModelOptions", "ModelOptionsError", "parse_model_options", "water_engine_factory", "describe", "et0_site", "EvapotranspirationError"]
