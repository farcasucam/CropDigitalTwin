"""Local HTTP adapter for the Phase 5.37 interactive simulation contract."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from agri_twin.application.energy_cost import energy_cost
from agri_twin.application.greenhouse_backend import GreenhouseBackendError, layout_floor_area_m2
from agri_twin.application.season_kpis import season_kpis
from agri_twin.application.site_resources import SiteResources, SiteResourcesError, load_site_resources, save_site_resources
from agri_twin.application.greenhouse_catalogue import build_greenhouse_catalogue
from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.runtime_replay import RuntimeReplayService
from agri_twin.application.climate_control import capabilities as climate_control_capabilities
from agri_twin.application.model_options import CO2_RESPONSES, DEFAULT_CO2, DEFAULT_ET0, ET0_METHODS, co2_constants
from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle
from agri_twin.application.weather_datasets import LOCAL_SOURCE, WeatherDatasetsError, dataset_info
from agri_twin.application.weather_datasets import climatology as weather_climatology
from agri_twin.application.interactive_simulation import (
    ErrorCode,
    SCIENTIFIC_STATUS,
    SimulationApiError,
    SimulationError,
    InteractiveSimulationService,
    canonicalize_request,
    contract_description,
    plan_execution,
)
from agri_twin.application.scientific_benchmark import KNOWN_CROPS, PERENNIAL_CROPS
from agri_twin.domain.farm import FarmConfigRepository
from agri_twin.infrastructure.energyplus_timeline import REQUIRED_VERSION_PREFIX, find_energyplus

LOGGER = logging.getLogger(__name__)
FRONTEND_ROOT = Path(__file__).resolve().parents[3] / "frontend"
MAX_REQUEST_BYTES = 1_000_000
POLL_INTERVAL_MS = 750


class InteractiveFrontendAdapter:
    """Present a narrow, JSON-friendly HTTP surface over the canonical 5.37 service."""

    def __init__(self, *, timer: Callable[[], float] | None = None) -> None:
        self._timer = timer
        self.service = InteractiveSimulationService(timer=timer)
        self.runtime = InteractiveRuntimeService(InteractiveSimulationService(timer=timer))
        self.replay_service = RuntimeReplayService(self.runtime)
        self._lock = threading.RLock()
        self._workers: dict[str, threading.Thread] = {}
        self._worker_errors: dict[str, str] = {}
        self._catalogue: dict[str, Any] | None = None
        self._farm_config = FarmConfigRepository(FRONTEND_ROOT.parent / "src" / "farm_config.json")

    def _tick(self) -> float | None:
        return self._timer() if self._timer is not None else None

    def _elapsed(self, started: float | None) -> float | None:
        return self._timer() - started if started is not None and self._timer is not None else None

    @staticmethod
    def weather_datasets() -> dict[str, Any]:
        """The local historical weather each crop can run on (offline: reads the downloaded files' metadata only)."""
        crops: dict[str, Any] = {}
        for crop in KNOWN_CROPS:
            _, cycle_start, cycle_end = campaign_cycle(crop)
            entry: dict[str, Any] = {"available": False, "cycle_days": (cycle_end - cycle_start).days, "perennial": crop in PERENNIAL_CROPS,
                                     "cycle_start_month_day": cycle_start.strftime("%m-%d")}
            try:
                info = dataset_info(crop)
            except WeatherDatasetsError:
                info = None
            if info is not None:
                entry.update(info.to_dict(), available=True)
            crops[crop] = entry
        return {"source": LOCAL_SOURCE, "classification": "FORCING", "crops": crops,
                "note": "Modelled reanalysis (Open-Meteo archive) used as simulation forcing: not station measurements and never REAL_VERIFIED. Points are approximate growing areas pending confirmation.",
                "download": "python -m agri_twin.application.weather_datasets plan | download --confirm-network | update --confirm-network"}

    def capabilities(self) -> dict[str, Any]:
        contract = contract_description()
        crop_defaults: dict[str, Any] = {}
        plot_details: dict[str, dict[str, Any]] = {}
        environments: dict[str, list[str]] = {}
        varieties: dict[str, list[str]] = {}
        configured_plots = {plot.plot_id: plot for plot in self._farm_config.plots}
        for crop in contract["crops"]:
            canonical = canonicalize_request({"crop": crop})
            varieties[crop] = [canonical.variety]
            crop_defaults[crop] = {
                "variety": canonical.variety,
                "plot": canonical.plot,
                "default_environment": canonical.environment,
                "start_time": canonical.start_time.isoformat(),
                "end_time": canonical.end_time.isoformat(),
                "dormancy_applicable": crop in PERENNIAL_CROPS,
            }
            configured_plot = configured_plots.get(canonical.plot)
            if configured_plot is None:
                plot_details[crop] = {
                    "plot_id": canonical.plot,
                    "crop_key": crop,
                    "variety": canonical.variety,
                    "metadata_status": "NO_FARM_METADATA_CONFIGURED",
                    "metadata_source": None,
                    "coordinates": None,
                }
            else:
                plot_details[crop] = {
                    "plot_id": configured_plot.plot_id,
                    "name": configured_plot.name,
                    "farm_name": configured_plot.farm_name,
                    "plot_code": configured_plot.plot_code,
                    "crop_key": configured_plot.crop_key,
                    "variety": configured_plot.variety,
                    "area_ha": configured_plot.area_ha,
                    "current_stage": configured_plot.current_stage,
                    "irrigation_type": configured_plot.irrigation_type,
                    "soil_type": configured_plot.soil_type,
                    "station_id": configured_plot.station_id,
                    "coordinates": {
                        "latitude": configured_plot.latitude,
                        "longitude": configured_plot.longitude,
                        "elevation_m": configured_plot.elevation,
                    },
                    "metadata_status": "TYPICAL_PLOT_NOT_REAL" if configured_plot.provenance else "CONFIGURED",
                    "metadata_source": "src/farm_config.json",
                }
            supported = []
            for environment in contract["environments"]:
                try:
                    canonicalize_request({"crop": crop, "environment": environment})
                except SimulationApiError:
                    continue
                supported.append(environment)
            environments[crop] = supported
        contract["crop_defaults"] = crop_defaults
        contract["plot_details"] = plot_details
        contract["crop_environments"] = environments
        contract["crop_varieties"] = varieties
        contract["perennial_crops"] = sorted(PERENNIAL_CROPS)
        contract["scientific_status"] = dict(SCIENTIFIC_STATUS)
        contract["runtime"] = self.runtime.contract()
        contract["greenhouse_backends"] = self.greenhouse_backends()
        contract["climate_control"] = climate_control_capabilities()
        contract["model_options"] = {"et0_methods": list(ET0_METHODS), "default_et0_method": DEFAULT_ET0,
                                     "co2_responses": list(CO2_RESPONSES), "default_co2_response": DEFAULT_CO2,
                                     "co2_gain_per_doubling": {"default": co2_constants()["relative_gain_per_doubling"], "status": co2_constants()["status"], "source": co2_constants()["source"]["citation"]}}
        contract["weather_datasets"] = self.weather_datasets()
        contract["poll_interval_ms"] = POLL_INTERVAL_MS
        contract["execution_adapter"] = "SYNCHRONOUS_IN_PROCESS_THREAD (local only; not durable or distributed)"
        return contract

    @staticmethod
    def plan(request: Any) -> dict[str, Any]:
        canonical = canonicalize_request(request)
        return {
            "request": canonical.to_dict(),
            "request_hash": canonical.request_hash,
            "plan": plan_execution(canonical).to_dict(),
        }

    def create(self, request: Any) -> dict[str, Any]:
        return self.service.create_simulation(request).to_dict()

    def start(self, simulation_id: str) -> dict[str, Any]:
        with self._lock:
            response = self.service.get_simulation(simulation_id)
            if response.execution_status.value == "CREATED":
                worker = self._workers.get(simulation_id)
                if worker is None or not worker.is_alive():
                    worker = threading.Thread(
                        target=self._run,
                        args=(simulation_id,),
                        name=f"agri-sim-{simulation_id}",
                        daemon=True,
                    )
                    self._workers[simulation_id] = worker
                    worker.start()
        return self.service.get_simulation(simulation_id).to_dict()

    def _run(self, simulation_id: str) -> None:
        try:
            self.service.start_simulation(simulation_id)
        except SimulationApiError as exc:
            response = self.service.get_simulation(simulation_id)
            if response.execution_status.value != "CANCELLED":
                LOGGER.error("Simulation worker %s could not start: %s", simulation_id, exc)
        except Exception:
            LOGGER.exception("Unexpected simulation adapter failure for %s", simulation_id)
            with self._lock:
                self._worker_errors[simulation_id] = (
                    "The in-process execution adapter failed unexpectedly; technical details are recorded in the local server log."
                )
        finally:
            with self._lock:
                self._workers.pop(simulation_id, None)

    def get(self, simulation_id: str) -> dict[str, Any]:
        with self._lock:
            worker_error = self._worker_errors.get(simulation_id)
        if worker_error is not None:
            raise SimulationApiError(
                (
                    SimulationError(
                        ErrorCode.INTERNAL_EXECUTION_ERROR,
                        worker_error,
                    ),
                )
            )
        return self.service.get_simulation(simulation_id).to_dict()

    def progress(self, simulation_id: str) -> dict[str, Any]:
        return self.service.get_simulation_progress(simulation_id).to_dict()

    def cancel(self, simulation_id: str) -> dict[str, Any]:
        return self.service.cancel_simulation(simulation_id).to_dict()

    def pause(self, simulation_id: str) -> dict[str, Any]:
        return self.service.pause_simulation(simulation_id).to_dict()

    def runtime_contract(self) -> dict[str, Any]:
        return self.runtime.contract()

    @staticmethod
    def greenhouse_backends() -> list[dict[str, Any]]:
        install = find_energyplus()
        usable = install is not None and install.version.startswith(REQUIRED_VERSION_PREFIX)
        reason = None
        if install is None:
            reason = "EnergyPlus was not found; set ENERGYPLUS_EXECUTABLE or install EnergyPlus 26.1"
        elif not usable:
            reason = f"EnergyPlus {install.version} found; the generated model needs {REQUIRED_VERSION_PREFIX}.x"
        return [
            {"id": "SIMPLIFIED", "label": "Simplified model", "available": True, "version": None, "reason": None,
             "note": "fast two-node lumped model of the chosen layout (same geometry and envelope as EnergyPlus); no crop feedback, no CO2 balance beyond the commanded supply"},
            {"id": "ENERGYPLUS", "label": "EnergyPlus", "available": usable, "version": install.version if install else None, "reason": reason,
             "note": "single-zone model of the chosen layout; no crop feedback, no CO2"},
        ]

    @staticmethod
    def climatology(crop: str) -> dict[str, Any] | None:
        try:
            return weather_climatology(crop)
        except WeatherDatasetsError:
            return None

    def greenhouse_catalogue(self) -> dict[str, Any]:
        if self._catalogue is None:
            self._catalogue = build_greenhouse_catalogue()
        return self._catalogue

    def runtime_preview(self, document: Any) -> dict[str, Any]:
        return self.runtime.preview_events(document)

    def runtime_what_if(self, document: Any) -> dict[str, Any]:
        return self.runtime.what_if(document)

    def runtime_explain(self, document: Any) -> dict[str, Any]:
        try:  # the explanation layer lives in the tsxai package; the rest of the server does not need it
            from twin_explanations.whatif import explain_what_if
        except ImportError as exc:
            raise ValueError(f"the explanation layer is not available: {exc}") from None
        return explain_what_if(self.runtime, document)

    def _plot_areas(self) -> dict[str, dict[str, Any]]:
        return {plot.crop_key: {"plot_id": plot.plot_id, "area_ha": plot.area_ha, "area_m2": None if plot.area_ha is None else plot.area_ha * 10000.0, "source": "src/farm_config.json", "typical": bool(plot.provenance)}
                for plot in self._farm_config.plots}

    def site_resources(self) -> dict[str, Any]:
        resources, document = load_site_resources()
        return {"configuration": resources.to_dict(), "status": document.get("status"), "note": document.get("note"), "meanings": document.get("meanings"),
                "content_hash": resources.content_hash, "plots": self._plot_areas()}

    def save_site_resources(self, document: Any) -> dict[str, Any]:
        try:
            save_site_resources(document if isinstance(document, dict) else {})
        except SiteResourcesError as exc:
            raise ValueError(f"{exc.path}: {exc.message}" if exc.path else exc.message) from None
        return self.site_resources()

    def season_kpis(self, document: Any) -> dict[str, Any]:
        allowed = {"crop", "environment", "times", "series", "greenhouse", "equipment", "area_m2", "resources"}
        if not isinstance(document, dict) or set(document) - allowed or not {"crop", "environment", "times", "series"} <= set(document):
            raise ValueError("the body must hold crop, environment, times and series (optionally greenhouse, equipment, area_m2)")
        crop, environment = str(document["crop"]).lower(), str(document["environment"]).lower()
        plots = self._plot_areas()
        plot_area = (plots.get(crop) or {}).get("area_m2")
        plot_note = " (a typical plot, not a real one)" if (plots.get(crop) or {}).get("typical") else ""
        if document.get("area_m2") is not None:
            area, source, plot_area = float(document["area_m2"]), "given by the caller", plot_area
        elif environment == "greenhouse":
            layout = (document.get("greenhouse") or {}).get("layout") if isinstance(document.get("greenhouse"), dict) else None
            try:
                area, source = layout_floor_area_m2(layout), "floor area of the simulated greenhouse layout"
            except GreenhouseBackendError as exc:
                raise ValueError(f"{exc.path}: {exc.message}") from None
        else:
            area, source, plot_area = plot_area, f"area of the plot in the farm configuration{plot_note}" if plot_area else "unknown", None
        try:
            resources = SiteResources.from_mapping(document["resources"]) if document.get("resources") is not None else load_site_resources()[0]  # unsaved values of the bench, or the saved file
            return season_kpis(resources, crop=crop, times=document["times"], series=document["series"], area_m2=area, area_source=source, plot_area_m2=plot_area, equipment=document.get("equipment"))
        except SiteResourcesError as exc:
            raise ValueError(f"{exc.path}: {exc.message}") from None

    def energy_cost(self, document: Any) -> dict[str, Any]:
        if not isinstance(document, dict) or set(document) != {"tariff", "time", "energy_kwh"}:
            raise ValueError("the body must hold exactly tariff, time and energy_kwh")
        return energy_cost(document["time"], document["energy_kwh"], document["tariff"])

    def runtime_record(self, document: Any) -> dict[str, Any]:
        return self.replay_service.record(document)

    def runtime_replay(self, session: Any) -> dict[str, Any]:
        return self.replay_service.replay(session)

    def resume(self, request: Any) -> dict[str, Any]:
        response = self.service.resume_simulation(request)
        self.start(response.simulation_id)
        return self.get(response.simulation_id)

    def result(self, simulation_id: str) -> dict[str, Any]:
        return self.service.get_simulation_result(simulation_id).to_dict()


class FrontendRequestHandler(BaseHTTPRequestHandler):
    """Serve the bundled UI and its same-origin JSON API; no arbitrary file paths."""

    adapter = InteractiveFrontendAdapter()
    server_version = "AgriTwinFrontend/5.38"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/capabilities":
            self._json(200, self.adapter.capabilities())
            return
        if path == "/api/site-resources":
            self._json(200, self.adapter.site_resources())
            return
        if path == "/api/runtime/contract":
            self._json(200, self.adapter.runtime_contract())
            return
        if path == "/api/greenhouse/catalogue":
            self._json(200, self.adapter.greenhouse_catalogue())
            return
        if path == "/api/weather/climatology":
            crop = (parse_qs(urlparse(self.path).query).get("crop") or [""])[0].lower()
            payload = self.adapter.climatology(crop)
            if payload is None:
                self._json(404, {"errors": [{"code": "NO_LOCAL_WEATHER", "message": f"no downloaded weather for crop {crop!r}", "path": "crop"}]})
            else:
                self._json(200, payload)
            return
        if path.startswith("/api/simulations/"):
            try:
                simulation_id, suffix = self._simulation_route(path)
                if suffix == "":
                    payload = self.adapter.get(simulation_id)
                elif suffix == "progress":
                    payload = self.adapter.progress(simulation_id)
                elif suffix == "result":
                    payload = self.adapter.result(simulation_id)
                else:
                    self._json(404, {"errors": [{"code": "NOT_FOUND", "message": "Unknown API route", "path": None}]})
                    return
            except SimulationApiError as exc:
                self._api_error(exc)
                return
            self._json(200, payload)
            return
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/plan":
                payload = self.adapter.plan(body)
            elif path == "/api/simulations":
                payload = self.adapter.create(body)
            elif path.startswith("/api/simulations/") and path.endswith("/start"):
                payload = self.adapter.start(self._simulation_route(path)[0])
            elif path.startswith("/api/simulations/") and path.endswith("/cancel"):
                payload = self.adapter.cancel(self._simulation_route(path)[0])
            elif path.startswith("/api/simulations/") and path.endswith("/pause"):
                payload = self.adapter.pause(self._simulation_route(path)[0])
            elif path == "/api/runtime/preview":
                payload = self.adapter.runtime_preview(body)
            elif path == "/api/runtime/what-if":
                payload = self.adapter.runtime_what_if(body)
            elif path == "/api/runtime/explain":
                payload = self.adapter.runtime_explain(body)
            elif path == "/api/site-resources":
                payload = self.adapter.save_site_resources(body)
            elif path == "/api/kpis/season":
                payload = self.adapter.season_kpis(body)
            elif path == "/api/energy/cost":
                payload = self.adapter.energy_cost(body)
            elif path == "/api/runtime/record":
                payload = self.adapter.runtime_record(body)
            elif path == "/api/runtime/replay":
                payload = self.adapter.runtime_replay(body)
            elif path == "/api/simulations/resume":
                payload = self.adapter.resume(body)
            else:
                self._json(404, {"errors": [{"code": "NOT_FOUND", "message": "Unknown API route", "path": None}]})
                return
        except SimulationApiError as exc:
            self._api_error(exc)
            return
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._json(400, {"errors": [{"code": "INVALID_REQUEST", "message": str(exc), "path": None}]})
            return
        self._json(200, payload)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _read_json(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length header is required")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("Content-Length must be an integer") from None
        if not 0 <= length <= MAX_REQUEST_BYTES:
            raise ValueError(f"Request body must not exceed {MAX_REQUEST_BYTES} bytes")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _simulation_route(self, path: str) -> tuple[str, str]:
        parts = path.split("/")
        if len(parts) < 4 or not parts[3] or parts[3] in {".", ".."}:
            raise SimulationApiError(
                (SimulationError(ErrorCode.INVALID_REQUEST, "A simulation id is required", "simulation_id"),)
            )
        return parts[3], "/".join(parts[4:])

    def _static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        files = {
            "/bench": ("bench.html", "text/html; charset=utf-8"),
            "/bench.js": ("bench.js", "text/javascript; charset=utf-8"),
            "/bench.css": ("bench.css", "text/css; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/runtime.js": ("runtime.js", "text/javascript; charset=utf-8"),
            "/visual_state.js": ("visual_state.js", "text/javascript; charset=utf-8"),
            "/visual.js": ("visual.js", "text/javascript; charset=utf-8"),
            "/scene_state.js": ("scene_state.js", "text/javascript; charset=utf-8"),
            "/iso_scene.js": ("iso_scene.js", "text/javascript; charset=utf-8"),
            "/vendor/isokit.iife.js": ("vendor/isokit.iife.js", "text/javascript; charset=utf-8"),
            "/vendor/isokit.css": ("vendor/isokit.css", "text/css; charset=utf-8"),
            "/vendor/uPlot.iife.min.js": ("vendor/uPlot.iife.min.js", "text/javascript; charset=utf-8"),
            "/vendor/uPlot.min.css": ("vendor/uPlot.min.css", "text/css; charset=utf-8"),
        }
        target = files.get(path)
        if target is None:
            self._json(404, {"errors": [{"code": "NOT_FOUND", "message": "Not found", "path": None}]})
            return
        filename, content_type = target
        try:
            content = (FRONTEND_ROOT / filename).read_bytes()
        except OSError:
            self._json(500, {"errors": [{"code": "FRONTEND_NOT_READY", "message": "Frontend asset is unavailable", "path": None}]})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(content)

    def _api_error(self, error: SimulationApiError) -> None:
        if error.errors and error.errors[0].code is ErrorCode.INTERNAL_EXECUTION_ERROR:
            status = 500
        elif error.errors and error.errors[0].path == "simulation_id" and "unknown simulation id" in str(error).lower():
            status = 404
        else:
            status = 400
        self._json(status, error.to_dict())

    def _json(self, status: int, payload: Any) -> None:
        started = self.adapter._tick()
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        serialization_seconds = self.adapter._elapsed(started)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if serialization_seconds is not None:
            self.send_header("X-Serialization-Seconds", f"{serialization_seconds:.6f}")
        self.end_headers()
        self.wfile.write(encoded)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    timer: Callable[[], float] | None = None,
) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("The development frontend server may only bind to loopback")

    class ServerHandler(FrontendRequestHandler):
        pass

    ServerHandler.adapter = InteractiveFrontendAdapter(timer=timer)
    server = ThreadingHTTPServer((host, port), ServerHandler)
    LOGGER.info("Agri-Twin frontend ready at http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Stopping Agri-Twin frontend server")
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the local Agri-Twin Phase 5.38 frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    serve(arguments.host, arguments.port)


if __name__ == "__main__":
    main()
