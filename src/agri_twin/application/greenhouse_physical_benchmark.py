"""Analytical physical benchmarks of the greenhouse-crop model (Phase 5.31).

Controlled, minimal cases whose expected outcome follows from the relations the
model already implements (lumped first-order energy, vapour and CO2 balances,
Beer-Lambert interception, the single CO2 response, saturation-limited
transpiration). The suite only *calls* the existing components; it contains no
energy, humidity, VPD, CO2 or growth equations of its own. Analytic expectations
are closed-form special cases (closed box, pure decay, translation invariance,
exact transmission products), never fitted values.

"QUALIFIED" means the implementation passed these synthetic benchmarks. It is not
validation against a real greenhouse.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agri_twin.application.clock import SimulationClock
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator, CropSimulationSnapshot
from agri_twin.application.scenarios import Scenario, ScenarioEvent, ScenarioKind, ScenarioRunner
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.climate_stress import ClimateStressEngine
from agri_twin.domain.crop_greenhouse_feedback import CropGreenhouseFeedbackConfiguration, CropGreenhouseFeedbackLoop, CropPhysicalExchangeModel
from agri_twin.domain.crop_growth import CropGrowthEngine, CropGrowthError, CropGrowthInput
from agri_twin.domain.greenhouse import (
    AIR_DENSITY_KG_M3,
    AIR_SPECIFIC_HEAT_J_KG_K,
    LATENT_HEAT_VAPORIZATION_J_KG,
    OUTDOOR_CO2_PPM,
    ActuatorControl,
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    MicroclimateState,
    SimplifiedGreenhouseModel,
    saturation_vapour_density_kg_m3,
    vapour_density_kg_m3,
    vapour_pressure_deficit_kpa,
)
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.radiation_growth import RadiationGrowthEngine
from agri_twin.domain.weather import WeatherConfiguration

UTC = timezone.utc
VERSION = "5.31.1"
T0 = datetime(2026, 7, 1, tzinfo=UTC)
DT = 3600.0
REL_TOL = 1e-9
ABS_TOL = 1e-9
ENGINEERING_TEST_THRESHOLD = "ENGINEERING_TEST_THRESHOLD"


class BenchmarkStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class BenchmarkLayer(StrEnum):
    SOFTWARE_CORRECTNESS = "SOFTWARE_CORRECTNESS"
    PHYSICAL_CONSISTENCY = "PHYSICAL_CONSISTENCY"


class IssueClassification(StrEnum):
    SOFTWARE_BUG = "SOFTWARE_BUG"
    PHYSICAL_INCONSISTENCY = "PHYSICAL_INCONSISTENCY"
    UNIT_ERROR = "UNIT_ERROR"
    TRACEABILITY_GAP = "TRACEABILITY_GAP"
    SCENARIO_DESIGN_ISSUE = "SCENARIO_DESIGN_ISSUE"
    OPEN_PHYSICAL_ISSUE = "OPEN_PHYSICAL_ISSUE"


@dataclass(frozen=True, slots=True)
class PhysicalBenchmarkCase:
    case_id: str
    category: str
    layer: BenchmarkLayer
    mandatory: bool
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]
    expected_relation: str
    actual_relation: str
    status: BenchmarkStatus
    classification: IssueClassification | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "case_id": self.case_id,
            "category": self.category,
            "layer": self.layer.value,
            "mandatory": self.mandatory,
            "inputs": _plain(self.inputs),
            "outputs": _plain(self.outputs),
            "expected_relation": self.expected_relation,
            "actual_relation": self.actual_relation,
            "status": self.status.value,
            "classification": self.classification.value if self.classification else None,
        }
        payload["case_hash"] = _hash(payload)
        return payload


@dataclass(frozen=True, slots=True)
class PhysicalBenchmarkReport:
    version: str
    cases: tuple[PhysicalBenchmarkCase, ...]
    invariants: Mapping[str, Any]
    traceability: Mapping[str, Any]
    static_audit: Mapping[str, Any]
    energyplus: Mapping[str, Any]
    parameter_registry_hash: str
    configuration_hashes: Mapping[str, str]
    test_count: int | None = None
    execution_metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @property
    def counts(self) -> dict[str, int]:
        return {status.value: sum(case.status is status for case in self.cases) for status in BenchmarkStatus}

    @property
    def qualified(self) -> bool:
        mandatory_ok = all(case.status is not BenchmarkStatus.FAIL for case in self.cases if case.mandatory)
        return mandatory_ok and self.invariants["status"] == "PASS" and self.traceability["status"] == "PASS" and self.static_audit["status"] == "PASS"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "phase": "5.31",
            "version": self.version,
            "simulation_time_origin": T0.isoformat(),
            "benchmark_count": len(self.cases),
            "status_counts": self.counts,
            "qualified": self.qualified,
            "cases": [case.to_dict() for case in self.cases],
            "invariants": _plain(self.invariants),
            "traceability": _plain(self.traceability),
            "static_audit": _plain(self.static_audit),
            "energyplus": _plain(self.energyplus),
            "parameter_registry_hash": self.parameter_registry_hash,
            "configuration_hashes": dict(self.configuration_hashes),
            "test_count": self.test_count,
            "scientific_status": {
                "GREENHOUSE_PHYSICAL_BENCHMARKS": "QUALIFIED" if self.qualified else "NOT_QUALIFIED",
                "REAL_AGRICULTURAL_DATA_VERIFIED": False,
                "CALIBRATION_PERFORMED": False,
                "EXPERIMENTAL_VALIDATION": "DEFERRED_TO_FINAL_VALIDATION_STAGE",
                "BIOLOGICAL_VALIDITY_CLAIMED": False,
                "FIELD_ACCURACY_CLAIMED": False,
                "DATA_ASSIMILATION_IMPLEMENTED": False,
                "meaning_of_qualified": "the implementation passed the synthetic physical benchmarks of Phase 5.31; not validation against a real greenhouse",
            },
            "scientific_limitations": list(LIMITATIONS),
        }
        payload["report_hash"] = _hash(payload)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


LIMITATIONS = (
    "Lumped single-zone well-mixed air; no CFD, no longwave radiative exchange, condensation releases no latent heat to the air.",
    "Default geometry (1000 m3 air with a 1 m2 exchange area) is an engineering placeholder; magnitudes are not calibrated and only directions/closures are benchmarked.",
    "Crop sensible heat is an engineering proxy; transpiration demand is the WaterBalanceEngine Hargreaves-type estimate capped by the indoor vapour deficit.",
    "CO2 response is the existing min(1, CO2/420) engineering response; no enrichment benefit is represented.",
    "Benchmarks are synthetic and analytic; they establish internal physical consistency only, not biological validity or field accuracy.",
)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _close(a: float, b: float, rel: float = REL_TOL, abs_: float = ABS_TOL) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def _strictly_increasing(values: Sequence[float]) -> bool:
    return all(b > a for a, b in zip(values, values[1:]))


def _non_decreasing(values: Sequence[float]) -> bool:
    return all(b >= a - ABS_TOL for a, b in zip(values, values[1:]))


# ---------------------------------------------------------------------------
# Fixtures (inputs only; no physics)
# ---------------------------------------------------------------------------


def outdoor(temperature: float = 20.0, humidity: float = 50.0, radiation: float = 0.0, rain: float = 0.0) -> WeatherState:
    return WeatherState(temperature, humidity, radiation, 2.0, 180.0, rain, 1013.0)


def indoor(temperature: float = 20.0, humidity: float = 50.0, co2: float = OUTDOOR_CO2_PPM, radiation: float = 0.0) -> MicroclimateState:
    return MicroclimateState(
        air_temperature_c=temperature, relative_humidity_pct=humidity, vpd_kpa=vapour_pressure_deficit_kpa(temperature, humidity),
        pressure_hpa=1013.0, solar_radiation_w_m2=radiation, par_umol_m2_s=radiation * 2.04, co2_ppm=co2,
    )


def crop_state(**changes: Any) -> CropGrowthState:
    values: dict[str, Any] = dict(
        simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth",
        biomass_total=100.0, biomass_leaf=60.0, biomass_stem=20.0, biomass_root=20.0, leaf_area_index=1.2,
        root_depth_m=0.6, soil_water_vwc=0.3, phenology_model="BENCHMARK_FIXTURE",
    )
    values.update(changes)
    return CropGrowthState(**values)


def soil_state() -> SoilState:
    return SoilState(0.30, 18.0, 0.35, 0.10, 0.0, 120.0)


def closed_box(**changes: Any) -> GreenhouseConfiguration:
    """No air exchange and no cover conductance: an adiabatic, sealed air volume."""
    return GreenhouseConfiguration(ventilation_ach=0.0, heat_loss_w_k=0.0, **changes)


def vapour(state: MicroclimateState) -> float:
    return vapour_density_kg_m3(state.temperature_c, state.relative_humidity_pct)


class _ConstantWeather:
    def __init__(self, weather: WeatherState) -> None:
        self.weather = weather

    def get(self, _timestamp: datetime) -> WeatherState:
        return self.weather


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class GreenhousePhysicalBenchmarkSuite:
    """Build the Phase 5.31 benchmark cases by calling the existing components."""

    VERSION = VERSION

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None, test_count: int | None = None) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.test_count = test_count if test_count is not None else count_tests(self.root / "tests" / "test_greenhouse_physical_benchmark.py")
        self._states: list[MicroclimateState] = []
        self._crops: list[CropGrowthState] = []

    # -- component calls -----------------------------------------------------

    def step(self, prior: MicroclimateState | None, weather: WeatherState, configuration: GreenhouseConfiguration, actuators: GreenhouseActuatorState | None = None, feedback: CropMicroclimateFeedback | None = None, dt: float = DT) -> MicroclimateState:
        state = SimplifiedGreenhouseModel().step(weather, configuration, actuators or GreenhouseActuatorState(), feedback or CropMicroclimateFeedback(), dt, prior=prior)
        self._states.append(state)
        return state

    def loop_step(self, loop: CropGreenhouseFeedbackLoop, crop: CropGrowthState, weather: WeatherState, configuration: GreenhouseConfiguration, actuators: GreenhouseActuatorState | None = None, prior: MicroclimateState | None = None, soil: SoilState | None = None, when: datetime | None = None):
        result = loop.step(crop, weather, configuration, actuators or GreenhouseActuatorState(), DT, soil if soil is not None else soil_state(), simulation_time=when, prior=prior)
        self._states.append(result.microclimate)
        self._crops.append(result.crop)
        return result

    def orchestrator(self, weather: WeatherState, mode: str = "passive_greenhouse", crop: CropGrowthState | None = None) -> CropDigitalTwinOrchestrator:
        return CropDigitalTwinOrchestrator(SimulationClock(T0), WeatherEngine(WeatherConfiguration(), provider=_ConstantWeather(weather)), crop or crop_state(), soil_state(), mode)

    def orchestrate(self, twin: CropDigitalTwinOrchestrator, actuators: Mapping[str, ActuatorControl] | None = None) -> CropSimulationSnapshot:
        snapshot = twin.step(DT, dict(actuators) if actuators else None)
        self._states.append(snapshot.microclimate.indoor_state)
        self._crops.append(snapshot.crop)
        return snapshot

    # -- case helper ---------------------------------------------------------

    @staticmethod
    def case(case_id: str, category: str, layer: BenchmarkLayer, inputs: Mapping[str, Any], outputs: Mapping[str, Any], expected: str, actual: str, passed: bool, *, mandatory: bool = True, classification: IssueClassification | None = None) -> PhysicalBenchmarkCase:
        status = BenchmarkStatus.PASS if passed else (BenchmarkStatus.FAIL if mandatory else BenchmarkStatus.WARN)
        return PhysicalBenchmarkCase(case_id, category, layer, mandatory, inputs, outputs, expected, actual, status, None if passed else classification)

    # -- energy --------------------------------------------------------------

    def energy_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        cfg = GreenhouseConfiguration(ventilation_ach=0.0)
        same = self.step(indoor(22.0, 60.0), outdoor(22.0, 60.0), cfg)
        drift_t, drift_v = same.temperature_c - 22.0, vapour(same) - vapour_density_kg_m3(22.0, 60.0)
        cases.append(self.case(
            "energy.identical_ambient_no_drift", "energy", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"indoor": [22.0, 60.0], "outdoor": [22.0, 60.0], "radiation_w_m2": 0.0, "ventilation_ach": 0.0, "actuators": "none", "crop_feedback": "none"},
            {"temperature_drift_c": drift_t, "vapour_drift_kg_m3": drift_v},
            "identical indoor/outdoor state without sources: no thermal or humidity drift", f"dT={drift_t:.3e} C, drho_v={drift_v:.3e} kg m-3",
            abs(drift_t) <= ABS_TOL and abs(drift_v) <= ABS_TOL, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        box = closed_box()
        radiation = 600.0
        sunny = self.step(indoor(22.0, 60.0), outdoor(22.0, 60.0, radiation), box)
        gain_j = radiation * box.solar_transmission * box.thermal_exchange_area_m2 * DT
        stored_j = box.thermal_mass_kj_k * 1000.0 * (sunny.temperature_c - 22.0)
        cases.append(self.case(
            "energy.radiation_energy_closure", "energy", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"closed_box": True, "outdoor_radiation_w_m2": radiation, "solar_transmission": box.solar_transmission, "area_m2": box.thermal_exchange_area_m2, "dt_s": DT},
            {"absorbed_solar_j": gain_j, "stored_heat_j": stored_j},
            "sealed adiabatic air: stored heat C*dT equals transmitted solar energy (no energy created or lost)", f"stored={stored_j:.6f} J vs solar={gain_j:.6f} J",
            _close(stored_j, gain_j), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        exchange = []
        for inside, out in ((30.0, 10.0), (10.0, 30.0)):
            state = self.step(indoor(inside), outdoor(out), GreenhouseConfiguration())
            exchange.append(state.temperature_c - inside)
        cases.append(self.case(
            "energy.exchange_sign", "energy", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"cases": [[30.0, 10.0], [10.0, 30.0]], "radiation_w_m2": 0.0},
            {"indoor_warmer_dT": exchange[0], "indoor_colder_dT": exchange[1]},
            "indoor warmer than outdoor loses heat, colder gains heat", f"warmer dT={exchange[0]:.4f}, colder dT={exchange[1]:.4f}",
            exchange[0] < 0 < exchange[1] and _close(exchange[0], -exchange[1]), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        deltas = [self.step(indoor(20.0 + diff), outdoor(20.0), GreenhouseConfiguration()).temperature_c - (20.0 + diff) for diff in (2.5, 5.0, 10.0)]
        cases.append(self.case(
            "energy.exchange_scales_with_difference", "energy", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"indoor_minus_outdoor_c": [2.5, 5.0, 10.0]}, {"temperature_change_c": deltas},
            "without sources the exchange is linear in (T_in - T_out): doubling the difference doubles the change", f"changes={[round(d, 6) for d in deltas]}",
            _close(deltas[1], 2 * deltas[0]) and _close(deltas[2], 2 * deltas[1]) and _strictly_increasing([-d for d in deltas]),
            classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        shifted = [self.step(indoor(base + 4.0), outdoor(base), GreenhouseConfiguration()).temperature_c - (base + 4.0) for base in (-5.0, 10.0, 20.0, 35.0)]
        cases.append(self.case(
            "energy.no_hidden_reference_temperature", "energy", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"outdoor_c": [-5.0, 10.0, 20.0, 35.0], "indoor_minus_outdoor_c": 4.0}, {"temperature_change_c": shifted},
            "translating both temperatures (across 20 C) leaves the exchange unchanged: no fixed reference temperature", f"changes={[round(d, 9) for d in shifted]}",
            all(_close(value, shifted[0]) for value in shifted), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        cfg = GreenhouseConfiguration()
        conductance = cfg.heat_loss_w_k + AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_K * cfg.volume_m3 * cfg.ventilation_ach / 3600.0
        half_life = math.log(2.0) * cfg.thermal_mass_kj_k * 1000.0 / conductance
        halved = self.step(indoor(30.0), outdoor(20.0), cfg, dt=half_life)
        cases.append(self.case(
            "energy.thermal_time_constant", "energy", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"indoor_c": 30.0, "outdoor_c": 20.0, "dt_s": half_life, "conductance_w_k": conductance},
            {"indoor_after_half_life_c": halved.temperature_c},
            "pure decay with tau = C/G: after ln2*tau the indoor-outdoor difference halves", f"T={halved.temperature_c:.9f} C (expected 25)",
            _close(halved.temperature_c, 25.0), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        warmer = [self.step(indoor(22.0), outdoor(out), GreenhouseConfiguration()).temperature_c for out in (10.0, 20.0, 30.0, 40.0)]
        cases.append(self.case(
            "monotonicity.outdoor_temperature", "energy", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"outdoor_c": [10.0, 20.0, 30.0, 40.0], "prior_indoor_c": 22.0}, {"indoor_c": warmer},
            "higher outdoor temperature gives a higher indoor temperature, ceteris paribus", f"indoor={[round(t, 4) for t in warmer]}",
            _strictly_increasing(warmer), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        return cases

    # -- ventilation ------------------------------------------------------------

    def ventilation_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        sweep = (0.0, 0.5, 3.0, 10.0)
        prior = indoor(35.0, 90.0, co2=900.0)
        out = outdoor(20.0, 40.0)
        states = [self.step(prior, out, GreenhouseConfiguration(ventilation_ach=ach, heat_loss_w_k=0.0)) for ach in sweep]
        fractions = [state.ventilation_fraction for state in states]
        expected_fractions = [1.0 - math.exp(-ach * DT / 3600.0) for ach in sweep]
        cases.append(self.case(
            "ventilation.exchanged_fraction", "ventilation", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"ach": list(sweep), "dt_s": DT}, {"exchanged_fraction": fractions},
            "exchanged fraction = 1 - exp(-ACH dt/3600), 0 at 0 ACH, increasing with ACH, never instantaneous equilibrium", f"fractions={[round(f, 6) for f in fractions]}",
            all(_close(a, b) for a, b in zip(fractions, expected_fractions)) and fractions[0] == 0.0 and _strictly_increasing(fractions) and fractions[-1] < 1.0,
            classification=IssueClassification.UNIT_ERROR,
        ))
        for name, getter, target in (
            ("temperature", lambda s: s.temperature_c, out.temperature_c),
            ("vapour", vapour, vapour_density_kg_m3(out.temperature_c, out.relative_humidity_pct)),
            ("co2", lambda s: s.co2_ppm, OUTDOOR_CO2_PPM),
        ):
            gaps = [abs(getter(state) - target) for state in states]
            cases.append(self.case(
                f"ventilation.{name}_toward_outdoor", "ventilation", BenchmarkLayer.PHYSICAL_CONSISTENCY,
                {"ach": list(sweep), "heat_loss_w_k": 0.0, "prior": prior.to_dict(), "outdoor": [20.0, 40.0]}, {f"{name}_gap_to_outdoor": gaps},
                f"more air exchange brings indoor {name} closer to outdoor; no change at 0 ACH", f"gaps={[round(g, 9) for g in gaps]}",
                _strictly_increasing([-gap for gap in gaps]), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
            ))
        split = self.step(prior, out, GreenhouseConfiguration(ventilation_ach=2.0), GreenhouseActuatorState(ventilation_ach=1.0))
        joined = self.step(prior, out, GreenhouseConfiguration(ventilation_ach=3.0))
        cases.append(self.case(
            "ventilation.configuration_plus_actuator", "ventilation", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"configured_ach": 2.0, "actuator_ach": 1.0, "reference_ach": 3.0}, {"split": split.to_dict(), "joined": joined.to_dict()},
            "air exchange = configured ventilation_ach + actuator ventilation", "identical states" if split.to_dict() == joined.to_dict() else "states differ",
            split.to_dict() == joined.to_dict(), classification=IssueClassification.SOFTWARE_BUG,
        ))
        still = outdoor(24.0, 55.0)
        base = self.orchestrate(self._equilibrium_twin(still))
        vented = self.orchestrate(self._equilibrium_twin(still), {"ventilation": ActuatorControl(10.0, maximum=10.0, capacity=10.0)})
        same_micro = base.microclimate.indoor_state.to_dict() | {"ventilation_fraction": 0.0} == vented.microclimate.indoor_state.to_dict() | {"ventilation_fraction": 0.0}
        cases.append(self.case(
            "ventilation.no_direct_biomass_path", "ventilation", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"outdoor": [24.0, 55.0, 0.0], "prior_indoor": "equal to outdoor", "ventilation_actuator_ach": 10.0},
            {"microclimate_identical": same_micro, "crop_identical": base.crop == vented.crop},
            "when ventilation leaves the microclimate unchanged, the crop is unchanged: no actuator-to-biomass path", f"microclimate identical={same_micro}, crop identical={base.crop == vented.crop}",
            same_micro and base.crop == vented.crop, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        return cases

    def _equilibrium_twin(self, weather: WeatherState) -> CropDigitalTwinOrchestrator:
        twin = self.orchestrator(weather)
        twin.microclimate = indoor(weather.temperature_c, weather.relative_humidity_pct, radiation=0.0)
        return twin

    # -- humidity / VPD ------------------------------------------------------------

    def humidity_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        grid = [(t, rh) for t in (-10.0, 5.0, 25.0, 45.0) for rh in (5.0, 50.0, 80.0, 100.0)]
        bad = []
        for temperature, humidity in grid:
            state = self.step(indoor(temperature, humidity), outdoor(temperature, humidity), GreenhouseConfiguration(ventilation_ach=1.0))
            if not (0.0 <= state.relative_humidity_pct <= 100.0 and state.vpd_kpa >= 0.0) or (humidity == 100.0 and state.vpd_kpa > ABS_TOL):
                bad.append([temperature, humidity])
        cases.append(self.case(
            "humidity.rh_vpd_bounds", "humidity_vpd", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"grid_temperature_c": [-10.0, 5.0, 25.0, 45.0], "grid_rh_pct": [5.0, 50.0, 80.0, 100.0]}, {"violations": bad},
            "RH in [0, 100] %, VPD >= 0 kPa, VPD = 0 at saturation, for dry, humid and saturated air", f"{len(bad)} violations over {len(grid)} states",
            not bad, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        box = closed_box()
        transpiration = 0.2
        humid = self.step(indoor(25.0, 40.0), outdoor(25.0, 40.0), box, feedback=CropMicroclimateFeedback(transpiration_mm_h=transpiration))
        added = (vapour(humid) - vapour_density_kg_m3(25.0, 40.0)) * box.volume_m3
        expected = transpiration * box.thermal_exchange_area_m2 * DT / 3600.0
        cases.append(self.case(
            "humidity.closed_box_vapour_conservation", "humidity_vpd", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"transpiration_mm_h": transpiration, "area_m2": box.thermal_exchange_area_m2, "volume_m3": box.volume_m3, "dt_s": DT},
            {"vapour_added_kg": added, "water_transpired_kg": expected},
            "sealed air below saturation: vapour mass gain equals transpired water (1 mm = 1 kg m-2)", f"gain={added:.9f} kg vs transpired={expected:.9f} kg",
            _close(added, expected, rel=1e-6), classification=IssueClassification.UNIT_ERROR,
        ))
        cooled = self.step(indoor(30.0, 95.0), outdoor(5.0, 95.0), GreenhouseConfiguration(ventilation_ach=0.0), dt=12 * 3600.0)
        cases.append(self.case(
            "humidity.condensation_bound", "humidity_vpd", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"prior": [30.0, 95.0], "outdoor": [5.0, 95.0], "dt_s": 12 * 3600.0}, {"rh_pct": cooled.relative_humidity_pct, "vpd_kpa": cooled.vpd_kpa},
            "cooling humid air caps vapour at saturation: RH = 100 %, VPD = 0", f"RH={cooled.relative_humidity_pct:.6f} VPD={cooled.vpd_kpa:.3e}",
            _close(cooled.relative_humidity_pct, 100.0) and cooled.vpd_kpa <= ABS_TOL and vapour(cooled) <= saturation_vapour_density_kg_m3(cooled.temperature_c) + ABS_TOL,
            classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
        crop = crop_state()
        violations, max_rh = 0, 0.0
        for hour in range(96):
            when = T0 + timedelta(hours=hour + 1)
            weather = outdoor(18.0 + 8.0 * math.sin(2 * math.pi * (hour - 8) / 24), 90.0, max(0.0, 800.0 * math.sin(2 * math.pi * (hour - 6) / 24)))
            result = self.loop_step(loop, crop, weather, GreenhouseConfiguration(ventilation_ach=0.0), when=when)
            max_rh = max(max_rh, result.microclimate.relative_humidity_pct)
            violations += int(result.microclimate.vpd_kpa <= 1e-12 and result.exchange.latent_heat_flux.value > 0.0)
            crop = result.crop.advance(when, DT)
        cases.append(self.case(
            "humidity.closed_saturated_greenhouse_no_latent_regression", "humidity_vpd", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"ventilation_ach": 0.0, "hours": 96, "outdoor_rh_pct": 90.0}, {"latent_flux_at_saturation_steps": violations, "max_rh_pct": max_rh},
            "Phase 5.29 regression: no latent heat flux while indoor air is saturated (VPD = 0) in a closed greenhouse", f"{violations} violating steps, max RH {max_rh:.3f} %",
            violations == 0 and max_rh <= 100.0, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        state = crop_state()
        model = CropPhysicalExchangeModel()
        common = dict(temperature=28.0, humidity=60.0, radiation=500.0)
        low = model.calculate(state, self._growth(state, indoor(**common)), MicroclimateState(air_temperature_c=28.0, relative_humidity_pct=60.0, vpd_kpa=0.5, pressure_hpa=1013.0, solar_radiation_w_m2=500.0, par_umol_m2_s=1020.0), outdoor(), DT, soil_state())
        high = model.calculate(state, self._growth(state, indoor(**common)), MicroclimateState(air_temperature_c=28.0, relative_humidity_pct=60.0, vpd_kpa=2.5, pressure_hpa=1013.0, solar_radiation_w_m2=500.0, par_umol_m2_s=1020.0), outdoor(), DT, soil_state())
        micro = indoor(30.0, 30.0, radiation=500.0)
        climate = ClimateStressEngine().profile_for("tomato")
        twin = self.orchestrator(outdoor(30.0, 30.0, 500.0), "outdoor")
        snapshot = self.orchestrate(twin)
        expected_stress = min(1.0, max(0.0, min(1.0, max(0.0, (snapshot.environment.vpd_kpa - climate.optimal_vpd_kpa) / (climate.stress_vpd_kpa - climate.optimal_vpd_kpa))) * 1.0))
        single = _close(low.transpiration_rate.value, high.transpiration_rate.value) and _close(snapshot.crop.vpd_stress, expected_stress)
        cases.append(self.case(
            "humidity.no_double_vpd_correction", "humidity_vpd", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"vpd_field_kpa": [0.5, 2.5], "orchestrator_outdoor": [30.0, 30.0, 500.0]},
            {"transpiration_mm_h": [low.transpiration_rate.value, high.transpiration_rate.value], "crop_vpd_stress": snapshot.crop.vpd_stress, "single_ramp_vpd_stress": expected_stress, "reference_microclimate_vpd": micro.vpd_kpa},
            "transpiration demand is not VPD-corrected a second time (only the saturation cap), and crop VPD stress is one ramp of the environment VPD",
            f"transpiration equal={_close(low.transpiration_rate.value, high.transpiration_rate.value)}, vpd_stress {snapshot.crop.vpd_stress:.6f} vs {expected_stress:.6f}",
            single, classification=IssueClassification.SOFTWARE_BUG,
        ))
        vpd = vapour_pressure_deficit_kpa(25.0, 50.0)
        cases.append(self.case(
            "units.vpd_kpa", "units", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"temperature_c": 25.0, "rh_pct": 50.0}, {"vpd_kpa": vpd},
            "VPD is reported in kPa (Tetens e_s(25 C) = 3.1686 kPa, half of it at 50 % RH)", f"VPD={vpd:.4f} kPa",
            _close(vpd, 0.5 * 3.16794, rel=1e-4) and 1.0 < vpd < 2.0, classification=IssueClassification.UNIT_ERROR,
        ))
        return cases

    @staticmethod
    def _growth(state: CropGrowthState, micro: MicroclimateState):
        return CropGrowthEngine().advance(state, CropGrowthInput(outdoor(micro.temperature_c, micro.relative_humidity_pct, micro.solar_radiation_w_m2), DT))

    # -- latent -------------------------------------------------------------------

    def latent_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        model = CropPhysicalExchangeModel()
        dry = indoor(28.0, 40.0, radiation=600.0)
        bare = crop_state(leaf_area_index=0.0, biomass_total=40.0, biomass_leaf=0.0)
        no_crop = model.calculate(bare, self._growth(bare, dry), dry, outdoor(), DT, soil_state())
        cases.append(self.case(
            "latent.no_crop_no_flux", "latent", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"lai": 0.0, "indoor": [28.0, 40.0, 600.0]}, {"transpiration_mm_h": no_crop.transpiration_rate.value, "latent_w_m2": no_crop.latent_heat_flux.value},
            "no canopy: no transpiration and no latent flux", f"E={no_crop.transpiration_rate.value}, LE={no_crop.latent_heat_flux.value}",
            no_crop.transpiration_rate.value == 0.0 and no_crop.latent_heat_flux.value == 0.0, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        night = indoor(20.0, 50.0, radiation=0.0)
        state = crop_state()
        dark = model.calculate(state, self._growth(state, night), night, outdoor(), DT, soil_state())
        cases.append(self.case(
            "latent.crop_without_transpiration", "latent", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"lai": 1.2, "indoor_radiation_w_m2": 0.0}, {"transpiration_mm_h": dark.transpiration_rate.value, "latent_w_m2": dark.latent_heat_flux.value},
            "canopy without radiative demand (night): no transpiration, no latent flux", f"E={dark.transpiration_rate.value}, LE={dark.latent_heat_flux.value}",
            dark.transpiration_rate.value == 0.0 and dark.latent_heat_flux.value == 0.0, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        wet = model.calculate(state, self._growth(state, dry), dry, outdoor(), DT, soil_state())
        consistent = _close(wet.latent_heat_flux.value, wet.transpiration_rate.value * LATENT_HEAT_VAPORIZATION_J_KG / 3600.0)
        box = closed_box()
        latent_only = CropMicroclimateFeedback(latent_heat_w_m2=wet.latent_heat_flux.value)
        cooled = self.step(indoor(28.0, 40.0), outdoor(28.0, 40.0), box, feedback=latent_only)
        expected = -wet.latent_heat_flux.value * box.thermal_exchange_area_m2 * DT / (box.thermal_mass_kj_k * 1000.0)
        cases.append(self.case(
            "latent.dry_air_cooling_applied_once", "latent", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"indoor": [28.0, 40.0, 600.0], "closed_box": True}, {"transpiration_mm_h": wet.transpiration_rate.value, "latent_w_m2": wet.latent_heat_flux.value, "temperature_change_c": cooled.temperature_c - 28.0, "expected_change_c": expected},
            "LE = E*lambda/3600 and the greenhouse cools by exactly LE*A*dt/C (single application, correct sign)", f"LE={wet.latent_heat_flux.value:.4f} W m-2, dT={cooled.temperature_c - 28.0:.6f} vs {expected:.6f}",
            wet.latent_heat_flux.value > 0.0 and consistent and _close(cooled.temperature_c - 28.0, expected), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        saturated = indoor(28.0, 100.0, radiation=600.0)
        blocked = model.calculate(state, self._growth(state, saturated), saturated, outdoor(), DT, soil_state())
        cases.append(self.case(
            "latent.saturated_air_no_cooling", "latent", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"indoor": [28.0, 100.0, 600.0]}, {"transpiration_mm_h": blocked.transpiration_rate.value, "latent_w_m2": blocked.latent_heat_flux.value},
            "saturated air (VPD = 0) has no evaporative capacity: no latent cooling", f"E={blocked.transpiration_rate.value}, LE={blocked.latent_heat_flux.value}",
            blocked.transpiration_rate.value == 0.0 and blocked.latent_heat_flux.value == 0.0, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        humidities = (99.999, 99.99, 99.9, 99.0, 90.0, 50.0)
        fluxes = []
        for humidity in humidities:
            micro = indoor(28.0, humidity, radiation=600.0)
            fluxes.append(model.calculate(state, self._growth(state, micro), micro, outdoor(), DT, soil_state()).latent_heat_flux.value)
        demand = WaterBalanceEngineProxy.demand(state, 28.0, 50.0, 600.0)
        cases.append(self.case(
            "monotonicity.transpiration_capacity", "latent", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"rh_pct": list(humidities), "temperature_c": 28.0}, {"latent_w_m2": fluxes, "unlimited_demand_mm_h": demand},
            "more evaporative capacity (lower RH) gives non-decreasing latent flux, bounded by the water-balance demand", f"LE={[round(f, 4) for f in fluxes]}",
            _non_decreasing(fluxes) and fluxes[0] < fluxes[-1] and fluxes[-1] <= demand * LATENT_HEAT_VAPORIZATION_J_KG / 3600.0 + ABS_TOL,
            classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        return cases

    # -- radiation ------------------------------------------------------------------

    def radiation_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        radiation = 800.0
        transmissions = (0.5, 0.78, 1.0)
        through = [self.step(indoor(), outdoor(radiation=radiation), GreenhouseConfiguration(solar_transmission=value)).solar_radiation_w_m2 for value in transmissions]
        cases.append(self.case(
            "radiation.cover_transmission", "radiation", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"outdoor_w_m2": radiation, "solar_transmission": list(transmissions)}, {"indoor_w_m2": through},
            "indoor radiation = outdoor x transmission (lower transmission, less radiation)", f"indoor={through}",
            all(_close(value, radiation * t) for value, t in zip(through, transmissions)) and _strictly_increasing(through), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        shades = (0.0, 0.3, 0.7)
        cfg = GreenhouseConfiguration()
        shaded = [self.step(indoor(), outdoor(radiation=radiation), cfg, GreenhouseActuatorState(shading_fraction=value)).solar_radiation_w_m2 for value in shades]
        cases.append(self.case(
            "radiation.shading", "radiation", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"outdoor_w_m2": radiation, "shading_fraction": list(shades)}, {"indoor_w_m2": shaded},
            "indoor radiation = outdoor x transmission x (1 - shading) (more shading, less radiation)", f"indoor={[round(v, 6) for v in shaded]}",
            all(_close(value, radiation * cfg.solar_transmission * (1 - s)) for value, s in zip(shaded, shades)) and _strictly_increasing(shaded[::-1]),
            classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        dark_state = self.step(indoor(), outdoor(radiation=0.0), cfg)
        dark = self.orchestrate(self.orchestrator(outdoor(radiation=0.0)))
        cases.append(self.case(
            "radiation.zero", "radiation", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"outdoor_w_m2": 0.0}, {"indoor_w_m2": dark_state.solar_radiation_w_m2, "potential_growth_g_m2": dark.potential_growth_g_m2},
            "no outdoor radiation: no indoor radiation and no potential growth", f"indoor={dark_state.solar_radiation_w_m2}, potential={dark.potential_growth_g_m2}",
            dark_state.solar_radiation_w_m2 == 0.0 and dark.potential_growth_g_m2 == 0.0, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        start = crop_state()
        twin = self.orchestrator(outdoor(25.0, 60.0, radiation), crop=start)
        snapshot = self.orchestrate(twin, {"shade": ActuatorControl(0.4)})
        profile = RadiationGrowthEngine().profile_for("tomato")
        indoor_radiation = snapshot.microclimate.indoor_state.solar_radiation_w_m2
        single = RadiationGrowthEngine.par_mj_m2(indoor_radiation, DT) * (1 - math.exp(-profile.extinction_coefficient * start.leaf_area_index)) * profile.rue_g_dm_mj_par
        outdoor_path = RadiationGrowthEngine.par_mj_m2(radiation, DT) * (1 - math.exp(-profile.extinction_coefficient * start.leaf_area_index)) * profile.rue_g_dm_mj_par
        cases.append(self.case(
            "radiation.single_path_to_crop", "radiation", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"outdoor_w_m2": radiation, "shading": 0.4, "lai": start.leaf_area_index}, {"indoor_w_m2": indoor_radiation, "potential_growth_g_m2": snapshot.potential_growth_g_m2, "single_indoor_path_g_m2": single, "outdoor_path_g_m2": outdoor_path},
            "potential growth = PAR(indoor radiation) x (1 - exp(-k LAI)) x RUE, applied once; never the outdoor radiation", f"potential={snapshot.potential_growth_g_m2:.9f} vs indoor path {single:.9f} (outdoor path {outdoor_path:.9f})",
            _close(snapshot.potential_growth_g_m2, single) and not _close(snapshot.potential_growth_g_m2, outdoor_path), classification=IssueClassification.SOFTWARE_BUG,
        ))
        return cases

    # -- CO2 ------------------------------------------------------------------------

    def co2_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        box = GreenhouseConfiguration(ventilation_ach=0.0)
        supplied = self.step(indoor(co2=500.0), outdoor(), box, GreenhouseActuatorState(co2_supply_ppm=40.0))
        uptaken = self.step(indoor(co2=500.0), outdoor(), box, feedback=CropMicroclimateFeedback(co2_uptake_ppm=25.0))
        cases.append(self.case(
            "co2.closed_box_bookkeeping", "co2", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"prior_ppm": 500.0, "supply_ppm_step": 40.0, "uptake_ppm_step": 25.0, "ventilation_ach": 0.0}, {"supplied_ppm": supplied.co2_ppm, "uptaken_ppm": uptaken.co2_ppm},
            "sealed air: supply adds and uptake removes exactly their per-step increments", f"supplied={supplied.co2_ppm}, uptaken={uptaken.co2_ppm}",
            _close(supplied.co2_ppm, 540.0) and _close(uptaken.co2_ppm, 475.0), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        ach, supply = 2.0, 30.0
        steady = self.step(indoor(co2=420.0), outdoor(), GreenhouseConfiguration(ventilation_ach=ach), GreenhouseActuatorState(co2_supply_ppm=supply), dt=30 * 86400.0)
        equilibrium = OUTDOOR_CO2_PPM + (supply / (30 * 86400.0)) / (ach / 3600.0)
        cases.append(self.case(
            "co2.ventilated_equilibrium", "co2", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"ach": ach, "supply_ppm_per_step": supply, "dt_s": 30 * 86400.0}, {"co2_ppm": steady.co2_ppm, "analytic_equilibrium_ppm": equilibrium},
            "with constant supply and exchange, CO2 tends to C_out + S/k", f"CO2={steady.co2_ppm:.9f} vs {equilibrium:.9f}",
            _close(steady.co2_ppm, equilibrium), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        levels = (0.0, 20.0, 60.0)
        concentrations = [self.step(indoor(co2=420.0), outdoor(), GreenhouseConfiguration(), GreenhouseActuatorState(co2_supply_ppm=value)).co2_ppm for value in levels]
        cases.append(self.case(
            "monotonicity.co2_supply", "co2", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"supply_ppm_step": list(levels)}, {"co2_ppm": concentrations},
            "more supply gives higher indoor CO2, ceteris paribus", f"CO2={[round(c, 6) for c in concentrations]}",
            _strictly_increasing(concentrations), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        sunny = outdoor(25.0, 60.0, 800.0)
        with_crop = self.loop_step(CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()), crop_state(), sunny, GreenhouseConfiguration(), prior=indoor(25.0, 60.0))
        bare = crop_state(leaf_area_index=0.0, biomass_total=40.0, biomass_leaf=0.0)
        without = self.loop_step(CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()), bare, sunny, GreenhouseConfiguration(), prior=indoor(25.0, 60.0))
        cases.append(self.case(
            "co2.crop_uptake_reduces_co2", "co2", BenchmarkLayer.PHYSICAL_CONSISTENCY,
            {"outdoor": [25.0, 60.0, 800.0], "lai": [1.2, 0.0]}, {"with_crop_ppm": with_crop.microclimate.co2_ppm, "without_crop_ppm": without.microclimate.co2_ppm, "uptake_ppm_step": with_crop.exchange.co2_uptake.value},
            "a growing canopy lowers indoor CO2 relative to the same greenhouse without crop", f"with={with_crop.microclimate.co2_ppm:.6f}, without={without.microclimate.co2_ppm:.6f}",
            with_crop.microclimate.co2_ppm < without.microclimate.co2_ppm and without.exchange.co2_uptake.value == 0.0, classification=IssueClassification.PHYSICAL_INCONSISTENCY,
        ))
        base = CropGrowthInput(outdoor(25.0, 60.0, 700.0), DT)
        state = crop_state()
        growth = {ppm: CropGrowthEngine().advance(state, CropGrowthInput(base.weather, DT, co2_ppm=ppm)).actual_growth_g_m2 for ppm in (210.0, 420.0, 840.0)}
        try:
            CropGrowthInput(base.weather, DT, co2_factor=0.5, co2_ppm=210.0)
            double_rejected = False
        except CropGrowthError:
            double_rejected = True
        snapshot = self.orchestrate(self.orchestrator(outdoor(25.0, 60.0, 700.0)), {"co2": ActuatorControl(200.0, maximum=2000.0, capacity=2000.0)})
        depleted = indoor(25.0, 60.0, co2=300.0, radiation=600.0)
        loop_growth = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())._grow(state, outdoor(), depleted, DT, T0)
        single = (
            double_rejected
            and snapshot.co2_factor == CropGrowthEngine.co2_response(snapshot.microclimate.indoor_state.co2_ppm)
            and loop_growth.co2_factor == CropGrowthEngine.co2_response(300.0)
            and _close(growth[210.0], 0.5 * growth[420.0]) and _close(growth[840.0], growth[420.0])
        )
        cases.append(self.case(
            "co2.single_path_to_growth", "co2", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"co2_ppm": [210.0, 420.0, 840.0], "double_input": "co2_factor=0.5 and co2_ppm=210"},
            {"actual_growth_g_m2": growth, "double_application_rejected": double_rejected, "orchestrator_co2_factor": snapshot.co2_factor, "loop_co2_factor": loop_growth.co2_factor},
            "MicroclimateState.CO2 -> CropGrowthInput.co2_ppm -> CropGrowthEngine.co2_response, applied once in both integration paths; double input rejected",
            f"growth ratios 210/420={growth[210.0] / growth[420.0]:.6f}, 840/420={growth[840.0] / growth[420.0]:.6f}; double rejected={double_rejected}",
            single, classification=IssueClassification.SOFTWARE_BUG,
        ))
        return cases

    # -- crop consumes the microclimate -----------------------------------------------

    def crop_microclimate_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        open_field = self.orchestrate(self.orchestrator(outdoor(26.0, 35.0, 600.0, rain=2.0), "outdoor"))
        cases.append(self.case(
            "crop_microclimate.outdoor_temperature", "crop_microclimate", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"mode": "outdoor", "outdoor": [26.0, 35.0, 600.0, 2.0]}, {"crop_temperature_c": open_field.weather.temperature_c, "crop_environment_equals_weather": open_field.weather == open_field.outdoor_weather},
            "outdoor: crop temperature == outdoor weather temperature (whole WeatherState, rain included)", f"crop T={open_field.weather.temperature_c}",
            open_field.weather == open_field.outdoor_weather, classification=IssueClassification.SOFTWARE_BUG,
        ))
        heated = self.orchestrate(self.orchestrator(outdoor(5.0, 70.0, 0.0)), {"heating": ActuatorControl(20.0, maximum=20.0, capacity=20.0)})
        micro = heated.microclimate.indoor_state
        cases.append(self.case(
            "crop_microclimate.greenhouse_temperature", "crop_microclimate", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"mode": "passive_greenhouse", "outdoor_c": 5.0, "heating_kw": 20.0}, {"outdoor_c": heated.outdoor_weather.temperature_c, "indoor_c": micro.temperature_c, "crop_c": heated.weather.temperature_c},
            "greenhouse: crop temperature == indoor microclimate temperature, not outdoor", f"outdoor={heated.outdoor_weather.temperature_c}, indoor={micro.temperature_c:.4f}, crop={heated.weather.temperature_c:.4f}",
            heated.weather.temperature_c == micro.temperature_c and abs(micro.temperature_c - heated.outdoor_weather.temperature_c) > 1.0, classification=IssueClassification.SOFTWARE_BUG,
        ))
        rich = self.orchestrate(self.orchestrator(outdoor(28.0, 40.0, 800.0, rain=5.0)), {"shade": ActuatorControl(0.5), "co2": ActuatorControl(300.0, maximum=2000.0, capacity=2000.0)})
        state = rich.microclimate.indoor_state
        consumed = (
            rich.weather.relative_humidity_pct == state.relative_humidity_pct
            and rich.weather.solar_radiation_w_m2 == state.solar_radiation_w_m2
            and rich.environment.vpd_kpa == state.vpd_kpa
            and rich.co2_factor == CropGrowthEngine.co2_response(state.co2_ppm)
            and rich.weather.rain_rate_mm_h == 0.0
        )
        cases.append(self.case(
            "crop_microclimate.greenhouse_rh_vpd_radiation_co2", "crop_microclimate", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"mode": "passive_greenhouse", "outdoor": [28.0, 40.0, 800.0, 5.0], "shading": 0.5, "co2_supply_ppm": 300.0},
            {"crop_environment": {"rh": rich.weather.relative_humidity_pct, "radiation": rich.weather.solar_radiation_w_m2, "rain": rich.weather.rain_rate_mm_h}, "indoor": state.to_dict(), "environment_vpd": rich.environment.vpd_kpa},
            "greenhouse: crop RH, VPD, radiation and CO2 are the indoor values and no rain reaches the crop", f"consumed indoor={consumed}",
            consumed, classification=IssueClassification.SOFTWARE_BUG,
        ))
        return cases

    # -- feedback ------------------------------------------------------------------------

    def feedback_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        start = indoor(25.0, 55.0, co2=450.0)
        sunny = outdoor(24.0, 60.0, 750.0)
        cfg = GreenhouseConfiguration()
        bare = crop_state(leaf_area_index=0.0, biomass_total=40.0, biomass_leaf=0.0)
        loop_result = self.loop_step(CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()), bare, sunny, cfg, prior=start)
        reference = self.step(start, sunny, cfg)
        zero_exchange = all(getattr(loop_result.feedback, name) == 0.0 for name in ("transpiration_mm_h", "latent_heat_w_m2", "sensible_heat_w_m2", "co2_uptake_ppm"))
        loop_values, reference_values = loop_result.microclimate.to_dict(), reference.to_dict()
        # Relaxation blends alpha*x + (1-alpha)*x, which equals x only to floating-point rounding.
        reproduced = all(_close(loop_values[key], reference_values[key], rel=1e-12, abs_=1e-12) for key in loop_values)
        cases.append(self.case(
            "feedback.none", "feedback", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"lai": 0.0, "prior": start.to_dict()}, {"loop": loop_values, "greenhouse_only": reference_values, "all_exchanges_zero": zero_exchange},
            "without crop exchanges (all zero) the loop reproduces the greenhouse step (to 1e-12 relative, the rounding of the relaxation blend)",
            f"exchanges zero={zero_exchange}, reproduced={reproduced}",
            zero_exchange and reproduced, classification=IssueClassification.SOFTWARE_BUG,
        ))
        zero = self.step(start, sunny, cfg)
        for name, feedback, changes_t, changes_v, changes_c in (
            ("thermal", CropMicroclimateFeedback(sensible_heat_w_m2=30.0), 1, False, False),
            ("latent", CropMicroclimateFeedback(latent_heat_w_m2=150.0), -1, False, False),
            ("co2", CropMicroclimateFeedback(co2_uptake_ppm=15.0), 0, False, True),
        ):
            state = self.step(start, sunny, cfg, feedback=feedback)
            dt_sign = (state.temperature_c > zero.temperature_c) - (state.temperature_c < zero.temperature_c)
            dv = not _close(vapour(state), vapour(zero), rel=1e-12, abs_=1e-15)
            dc = not _close(state.co2_ppm, zero.co2_ppm)
            cases.append(self.case(
                f"feedback.{name}_isolated", "feedback", BenchmarkLayer.PHYSICAL_CONSISTENCY,
                {"feedback": {f.name: getattr(feedback, f.name) for f in fields(feedback)}}, {"temperature_change_c": state.temperature_c - zero.temperature_c, "vapour_changed": dv, "co2_change_ppm": state.co2_ppm - zero.co2_ppm},
                f"{name} feedback changes only its own balance (temperature sign {changes_t:+d}; vapour {'changes' if changes_v else 'unchanged'}; CO2 {'decreases' if changes_c else 'unchanged'})",
                f"dT sign={dt_sign:+d}, vapour changed={dv}, CO2 changed={dc}",
                dt_sign == changes_t and dv == changes_v and dc == changes_c and (not changes_c or state.co2_ppm < zero.co2_ppm), classification=IssueClassification.PHYSICAL_INCONSISTENCY,
            ))
        one = CropGreenhouseFeedbackConfiguration(max_iterations=1)
        single = self.loop_step(CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel(), configuration=one), crop_state(), sunny, cfg, prior=start)
        candidate = SimplifiedGreenhouseModel().step(sunny, cfg, GreenhouseActuatorState(), CropMicroclimateFeedback(), DT, prior=start)
        loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel(), configuration=one)
        growth = loop._grow(crop_state(), sunny, candidate, DT, T0)
        exchange = loop.exchange.calculate(crop_state(), growth, candidate, sunny, DT, soil_state())
        calculated = SimplifiedGreenhouseModel().step(sunny, cfg, GreenhouseActuatorState(), exchange.to_feedback(), DT, prior=start)
        expected = one.relaxation_alpha * calculated.temperature_c + (1 - one.relaxation_alpha) * candidate.temperature_c
        cases.append(self.case(
            "feedback.relaxation_applied_once", "feedback", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"max_iterations": 1, "alpha": one.relaxation_alpha}, {"loop_temperature_c": single.microclimate.temperature_c, "reconstructed_c": expected},
            "one iteration = one relaxation of the candidate toward the recomputed state, both from the same start state", f"loop={single.microclimate.temperature_c:.12f} vs {expected:.12f}",
            _close(single.microclimate.temperature_c, expected), classification=IssueClassification.SOFTWARE_BUG,
        ))
        backend = SimplifiedGreenhouseModel()
        committed_loop = CropGreenhouseFeedbackLoop(backend)
        input_crop = crop_state()
        result = self.loop_step(committed_loop, input_crop, sunny, cfg, prior=start)
        backend_state = backend.state()
        committed = committed_loop.last_converged is result.microclimate and input_crop == crop_state() and backend_state.to_dict() == result.microclimate.to_dict()
        cases.append(self.case(
            "feedback.only_converged_state_persists", "feedback", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"prior": start.to_dict()}, {"loop_last_converged_is_result": committed_loop.last_converged is result.microclimate, "backend_state_equals_converged": backend_state.to_dict() == result.microclimate.to_dict(), "input_crop_unchanged": input_crop == crop_state()},
            "intermediate iterations mutate no persistent state: loop and greenhouse backend hold the converged state, the input crop is untouched",
            f"loop={committed_loop.last_converged is result.microclimate}, backend={backend_state.to_dict() == result.microclimate.to_dict()}",
            committed, classification=IssueClassification.SOFTWARE_BUG,
        ))
        runs = {}
        for ach in (0.0, 0.3, 3.0):
            first, second = self._diurnal_loop(ach), self._diurnal_loop(ach)
            runs[str(ach)] = first | {"replay_identical": first["hash"] == second["hash"]}
        combined_ok = all(run["converged"] == run["steps"] and run["finite"] and run["replay_identical"] and run["reversals_over_1c"] == 0 for run in runs.values())
        cases.append(self.case(
            "feedback.combined_convergence_determinism", "feedback", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"hours": 48, "ach": [0.0, 0.3, 3.0]}, {"runs": runs},
            "combined thermal+latent+CO2 feedback converges every step, replays identically, has no NaN/Inf and no artificial temperature oscillation", f"{json.dumps({k: [v['converged'], v['max_iterations'], v['reversals_over_1c']] for k, v in runs.items()})}",
            combined_ok, classification=IssueClassification.SOFTWARE_BUG,
        ))
        return cases

    def _diurnal_loop(self, ach: float, hours: int = 48) -> dict[str, Any]:
        loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
        crop = crop_state()
        digest = hashlib.sha256()
        converged, iterations, finite, deltas = 0, [], True, []
        for hour in range(hours):
            when = T0 + timedelta(hours=hour + 1)
            weather = outdoor(20.0 + 8.0 * math.sin(2 * math.pi * (hour - 9) / 24), 60.0, max(0.0, 850.0 * math.sin(2 * math.pi * (hour - 6) / 24)))
            result = self.loop_step(loop, crop, weather, GreenhouseConfiguration(ventilation_ach=ach), when=when)
            values = [*result.microclimate.to_dict().values(), result.feedback.latent_heat_w_m2, result.crop_growth.actual_growth_g_m2]
            finite = finite and all(math.isfinite(v) for v in values)
            converged += int(result.convergence.converged)
            iterations.append(result.convergence.iterations)
            deltas.append(result.microclimate.temperature_c - weather.temperature_c)
            digest.update(repr(values).encode("ascii"))
            crop = result.crop.advance(when, DT)
        reversals = sum(1 for a, b, c in zip(deltas, deltas[1:], deltas[2:]) if abs(c - b) > 1.0 and abs(b - a) > 1.0 and (c - b) * (b - a) < 0)
        return {"steps": hours, "converged": converged, "max_iterations": max(iterations), "finite": finite, "reversals_over_1c": reversals, "hash": digest.hexdigest()}

    # -- determinism and units -------------------------------------------------------------

    def determinism_and_unit_cases(self) -> list[PhysicalBenchmarkCase]:
        cases = []
        start = datetime(2026, 5, 1, tzinfo=UTC)
        crop, soil = crop_state(simulation_time=start), soil_state()
        scenario = Scenario(
            "p531_replay", "replay", "deterministic replay", "tomato", "RAF", start, start + timedelta(hours=48), 3600, ScenarioKind.BENCHMARK,
            crop, soil, outdoor(24.0, 60.0, 600.0), "passive_greenhouse",
            (ScenarioEvent("vent", "ventilation", start, start + timedelta(hours=24), 2.0, {"value": 2.0, "maximum": 5.0}), ScenarioEvent("co2", "co2", start + timedelta(hours=12), start + timedelta(hours=36), 150.0, {"value": 150.0, "maximum": 2000.0})),
        )

        def replay() -> str:
            result = ScenarioRunner().run(scenario)
            return _hash([[s.simulation_time.isoformat(), s.crop.to_dict(), s.microclimate.indoor_state.to_dict()] for s in result.snapshots])

        first, second = replay(), replay()
        cases.append(self.case(
            "determinism.scenario_replay", "determinism", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"scenario": scenario.config_hash(), "clock": "SimulationClock via ScenarioRunner", "hours": 48}, {"first_hash": first, "second_hash": second},
            "the same scenario replayed through SimulationClock gives an identical full trajectory", "identical" if first == second else "different",
            first == second, classification=IssueClassification.SOFTWARE_BUG,
        ))
        box = closed_box()
        heated = self.step(indoor(15.0), outdoor(15.0), box, GreenhouseActuatorState(heating_kw=1.0))
        expected = 1000.0 * DT / (box.thermal_mass_kj_k * 1000.0)
        cases.append(self.case(
            "units.heating_kw_to_joules", "units", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"heating_kw": 1.0, "dt_s": DT, "thermal_mass_kj_k": box.thermal_mass_kj_k}, {"temperature_change_c": heated.temperature_c - 15.0, "expected_c": expected},
            "1 kW for 1 h into C = thermal_mass_kj_k x 1000 J/K raises T by 3.6e6 / C", f"dT={heated.temperature_c - 15.0:.9f} vs {expected:.9f}",
            _close(heated.temperature_c - 15.0, expected), classification=IssueClassification.UNIT_ERROR,
        ))
        misted = self.step(indoor(25.0, 40.0), outdoor(25.0, 40.0), box, GreenhouseActuatorState(misting_mm_h=0.36))
        added = (vapour(misted) - vapour_density_kg_m3(25.0, 40.0)) * box.volume_m3
        cooling = misted.temperature_c - 25.0
        expected_cooling = -0.36 * box.thermal_exchange_area_m2 * LATENT_HEAT_VAPORIZATION_J_KG / (box.thermal_mass_kj_k * 1000.0)
        cases.append(self.case(
            "units.misting_mm_h_to_kg", "units", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"misting_mm_h": 0.36, "area_m2": box.thermal_exchange_area_m2, "dt_s": DT}, {"vapour_added_kg": added, "temperature_change_c": cooling, "expected_cooling_c": expected_cooling},
            "0.36 mm/h over 1 m2 for 1 h evaporates 0.36 kg (below saturation) and removes its latent heat", f"added={added:.9f} kg, dT={cooling:.9f} vs {expected_cooling:.9f}",
            _close(added, 0.36, rel=1e-6) and _close(cooling, expected_cooling), classification=IssueClassification.UNIT_ERROR,
        ))
        registry_before = _hash([record.to_dict() for record in self.registry.records])
        configuration = GreenhouseConfiguration()
        crop_before = crop_state()
        loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
        self.loop_step(loop, crop_before, outdoor(25.0, 55.0, 700.0), configuration)
        self.orchestrate(self.orchestrator(outdoor(25.0, 55.0, 700.0)))
        unchanged = registry_before == _hash([record.to_dict() for record in self.registry.records]) and configuration == GreenhouseConfiguration() and crop_before == crop_state()
        cases.append(self.case(
            "mutation.no_parameter_configuration_or_state_mutation", "mutation", BenchmarkLayer.SOFTWARE_CORRECTNESS,
            {"components": ["CropGreenhouseFeedbackLoop", "CropDigitalTwinOrchestrator"]}, {"unchanged": unchanged},
            "benchmark execution mutates neither the ParameterRegistry, nor GreenhouseConfiguration, nor input crop states", f"unchanged={unchanged}",
            unchanged, classification=IssueClassification.SOFTWARE_BUG,
        ))
        return cases

    # -- invariants, traceability, static audit ---------------------------------------------

    def invariants(self) -> dict[str, Any]:
        failures = []
        for index, state in enumerate(self._states):
            values = state.to_dict()
            if not all(math.isfinite(value) for value in values.values()):
                failures.append([index, "finite"])
            if state.vpd_kpa < 0:
                failures.append([index, "vpd>=0"])
            if not 0.0 <= state.relative_humidity_pct <= 100.0:
                failures.append([index, "rh_range"])
            if state.solar_radiation_w_m2 < 0:
                failures.append([index, "radiation>=0"])
            if state.co2_ppm < 0:
                failures.append([index, "co2>=0"])
        for index, crop in enumerate(self._crops):
            if crop.biomass_total < 0 or crop.leaf_area_index < 0 or not 0.0 <= crop.maturity_index <= 1.0:
                failures.append([index, "crop_state_bounds"])
        return {
            "status": "PASS" if not failures else "FAIL",
            "microclimate_states_checked": len(self._states),
            "crop_states_checked": len(self._crops),
            "failures": failures,
            "rules": ["finite values", "VPD >= 0", "0 <= RH <= 100", "radiation >= 0", "CO2 >= 0", "biomass >= 0", "LAI >= 0", "maturity in [0, 1]"],
            "cross_references": {
                "no state mutation": "mutation.no_parameter_configuration_or_state_mutation, feedback.only_converged_state_persists",
                "deterministic replay": "determinism.scenario_replay, feedback.combined_convergence_determinism",
                "greenhouse crop receives indoor microclimate": "crop_microclimate.*",
                "no duplicate CO2 application": "co2.single_path_to_growth",
                "no duplicate VPD correction": "humidity.no_double_vpd_correction",
                "no latent flux without evaporative capacity": "latent.saturated_air_no_cooling, humidity.closed_saturated_greenhouse_no_latent_regression",
            },
        }

    TRACED_PARAMETERS: tuple[tuple[str, str, float], ...] = (
        ("volume_m3", "greenhouse.volume", GreenhouseConfiguration().volume_m3),
        ("solar_transmission", "greenhouse.cover_transmission", GreenhouseConfiguration().solar_transmission),
        ("ventilation_ach", "greenhouse.ventilation_ach", GreenhouseConfiguration().ventilation_ach),
        ("heat_loss_w_k", "greenhouse.heat_loss_conductance", GreenhouseConfiguration().heat_loss_w_k),
        ("thermal_mass_kj_k", "greenhouse.thermal_mass", GreenhouseConfiguration().thermal_mass_kj_k),
        ("thermal_exchange_area_m2", "greenhouse.thermal_exchange_area", GreenhouseConfiguration().thermal_exchange_area_m2),
        ("co2_ppm_baseline", "greenhouse.co2_baseline", GreenhouseConfiguration().co2_ppm_baseline),
        ("AIR_DENSITY_KG_M3", "feedback.air_density", AIR_DENSITY_KG_M3),
        ("AIR_SPECIFIC_HEAT_J_KG_K", "physics.air_specific_heat", AIR_SPECIFIC_HEAT_J_KG_K),
        ("LATENT_HEAT_VAPORIZATION_J_KG", "feedback.latent_heat_vaporization", LATENT_HEAT_VAPORIZATION_J_KG),
        ("WATER_VAPOUR_GAS_CONSTANT_J_KG_K", "physics.water_vapour_gas_constant", 461.5),
        ("OUTDOOR_CO2_PPM", "greenhouse.outdoor_co2", OUTDOOR_CO2_PPM),
        ("CO2_REFERENCE_PPM", "crop.co2_response_reference", CropGrowthEngine.CO2_REFERENCE_PPM),
        ("air_volume_m3", "feedback.air_volume", CropGreenhouseFeedbackConfiguration().air_volume_m3),
        ("relaxation_alpha", "feedback.relaxation_alpha", CropGreenhouseFeedbackConfiguration().relaxation_alpha),
        ("sensible_heat_transfer_w_m2_k", "feedback.sensible_heat_transfer", CropGreenhouseFeedbackConfiguration().sensible_heat_transfer_w_m2_k),
    )

    def traceability(self) -> dict[str, Any]:
        rows, gaps = [], []
        by_id = {record.parameter_id: record for record in self.registry.records}
        for name, parameter_id, value in self.TRACED_PARAMETERS:
            record = by_id.get(parameter_id)
            row = {"parameter": name, "parameter_id": parameter_id, "code_value": value, "registered": record is not None}
            if record is not None:
                row |= {"registry_value": record.value, "unit": record.unit, "source_type": record.source_type, "calibration_status": record.calibration_status, "calibration_allowed": record.calibration_allowed}
                if not _close(float(record.value), float(value)) or record.source_type == "calibrated":
                    gaps.append(parameter_id)
            else:
                gaps.append(parameter_id)
            rows.append(row)
        return {"status": "PASS" if not gaps else "FAIL", "classification": None if not gaps else IssueClassification.TRACEABILITY_GAP.value, "gaps": gaps, "parameters": rows}

    def static_audit(self) -> dict[str, Any]:
        from agri_twin.application.integrated_synthetic_validation import static_audit

        audit = static_audit(self.root)
        source = self.root / "src" / "agri_twin"
        tetens = []
        for path in sorted(source.rglob("*.py")):
            relative = path.relative_to(source.parent).as_posix()
            if relative == "agri_twin/application/greenhouse_physical_benchmark.py":
                continue  # this scanner's own detection literal
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and node.value == 17.27:
                    tetens.append(f"{relative}:{node.lineno}")
        single_psychrometrics = tetens == [t for t in tetens if t.startswith("agri_twin/domain/greenhouse.py")] and len(tetens) == 1
        passed = audit["status"] == "PASS" and single_psychrometrics
        return {
            "status": "PASS" if passed else "FAIL",
            "phase5_29_static_audit": {key: audit[key] for key in ("status", "violations", "duplicate_core_classes", "missing_core_classes", "phase_module_calibration_imports", "phase_module_optimizer_calls")},
            "saturation_vapour_pressure_definitions": tetens,
            "single_psychrometric_definition": single_psychrometrics,
            "classification": None if passed else (IssueClassification.TRACEABILITY_GAP.value if not single_psychrometrics else IssueClassification.SOFTWARE_BUG.value),
        }

    @staticmethod
    def energyplus() -> dict[str, Any]:
        from agri_twin.infrastructure.energyplus_greenhouse import detect_energyplus

        availability = detect_energyplus()
        return {
            "availability": availability.status.value,
            "detail": availability.detail,
            "role": "optional secondary backend; never ground truth",
            "benchmark_use": "none (not available)" if availability.status.value != "AVAILABLE" else "technical smoke only; not executed by this suite",
        }

    # -- report ------------------------------------------------------------------------

    def build_report(self) -> PhysicalBenchmarkReport:
        self._states.clear()
        self._crops.clear()
        cases = [
            *self.energy_cases(), *self.ventilation_cases(), *self.humidity_cases(), *self.latent_cases(),
            *self.radiation_cases(), *self.co2_cases(), *self.crop_microclimate_cases(), *self.feedback_cases(),
            *self.determinism_and_unit_cases(),
        ]
        configurations = {
            "default": GreenhouseConfiguration(), "closed_box": closed_box(), "closed": GreenhouseConfiguration(ventilation_ach=0.0),
            "feedback": CropGreenhouseFeedbackConfiguration(),
        }
        return PhysicalBenchmarkReport(
            VERSION, tuple(cases), self.invariants(), self.traceability(), self.static_audit(), self.energyplus(),
            _hash([record.to_dict() for record in self.registry.records]),
            {name: _hash({f.name: getattr(value, f.name) for f in fields(value)}) for name, value in configurations.items()},
            self.test_count,
        )

    def write_report(self, report: PhysicalBenchmarkReport, directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "benchmarks"
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "greenhouse_physical_benchmark_report.json"
        readme_path = output / "greenhouse_physical_benchmark_README.md"
        payload = report.to_dict()
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        lines = [
            "# Greenhouse physical benchmark (Phase 5.31)",
            "",
            "Deterministic analytical benchmarks of the greenhouse-crop model. QUALIFIED means the implementation passed these synthetic benchmarks;",
            "it is not validation against a real greenhouse, not calibration, and claims no biological validity or field accuracy.",
            "",
            f"- version: `{report.version}`",
            f"- benchmark cases: `{len(report.cases)}`; status counts: `{json.dumps(report.counts, sort_keys=True)}`",
            f"- qualified: `{report.qualified}`",
            f"- invariants: `{report.invariants['status']}`; traceability: `{report.traceability['status']}`; static audit: `{report.static_audit['status']}`",
            f"- EnergyPlus: `{report.energyplus['availability']}` (optional, never ground truth)",
            f"- parameter registry hash: `{report.parameter_registry_hash}`",
            f"- report hash: `{payload['report_hash']}`",
            "",
            "## Cases",
            "",
            *[f"- `{case.case_id}` [{case.layer.value}] {case.status.value}: {case.expected_relation}" for case in report.cases],
            "",
        ]
        readme_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path, readme_path


def count_tests(path: Path) -> int | None:
    """Deterministic count of pytest cases in a file (parametrize lists expanded)."""
    if not path.is_file():
        return None
    total = 0
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            count = 1
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and _call_name(decorator.func).endswith("parametrize") and len(decorator.args) >= 2 and isinstance(decorator.args[1], (ast.List, ast.Tuple)):
                    count *= len(decorator.args[1].elts)
            total += count
    return total


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


class WaterBalanceEngineProxy:
    """Unlimited transpiration demand from the existing WaterBalanceEngine (no cap)."""

    @staticmethod
    def demand(crop: CropGrowthState, temperature: float, humidity: float, radiation: float) -> float:
        from agri_twin.domain.water_balance import WaterBalanceEngine

        return WaterBalanceEngine().advance(soil_state(), WeatherState(temperature, humidity, radiation, 2.0, 180.0, 0.0, 1013.0), DT, crop).transpiration_mm


__all__ = [
    "BenchmarkLayer",
    "BenchmarkStatus",
    "GreenhousePhysicalBenchmarkSuite",
    "IssueClassification",
    "PhysicalBenchmarkCase",
    "PhysicalBenchmarkReport",
]
