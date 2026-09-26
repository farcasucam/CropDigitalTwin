# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Agricultural crop digital twin ("Gemelo Digital Agrícola"), Python 3.11+, package `agri_twin` under `src/`. Most docs and the README are in Spanish; code and newer phase docs are in English. The authoritative spec lives in `docs/architecture/` (`ARCHITECTURE_REQUIREMENTS.md`, `DOMAIN_MODEL.md`, `EVENTS_AND_CAUSALITY.md`, `DECISIONS.md`, `PHASES.md`) and `docs/components/`. `CODE_GENERATION_PROMPT.md` holds the implementation rules the project was built under.

## Commands

```powershell
python -m pip install -e ".[dev]"          # optional extra: ".[eppy]" for EnergyPlus/eppy greenhouse variants
python -m pytest                            # testpaths=tests, pythonpath=src (from pyproject.toml)
python -m pytest tests/test_transferability_robustness.py
python -m pytest tests/test_crop_engine.py::test_name -q
python -u manual_phase5_28_transferability_robustness_test.py   # per-phase offline acceptance script
docker compose up -d mosquitto              # local MQTT broker (only needed for real MQTT runs)
```

A `.venv` exists at the repo root. There is no linter/formatter configured. There is no `.gitignore`: `__pycache__/*.pyc` files are tracked and show up in diffs/commits.

## Architecture

Layered, dependency pointing inward:

- `agri_twin/domain/` — immutable dataclasses and pure deterministic engines (crop, phenology, radiation growth, water/nutrient balance, climate stress, greenhouse microclimate, calibration primitives, parameter audit). Must not import MQTT, HTTP, storage, frontend, `application` or `infrastructure`.
- `agri_twin/application/` — orchestration and services: `SimulationClock`/`SimulationScheduler` (deterministic, explicit `initial_time`, no wall clock), `CropDigitalTwinOrchestrator`, scenarios, twin state/history, and the Phase 5.x scientific framework modules. `application/__init__.py` re-exports the public API of every module (large, ~450 lines).
- `agri_twin/infrastructure/` — adapters: Open-Meteo download, CSV weather provider, weather cache, eppy/EnergyPlus greenhouse backends, logging.
- `agri_twin/interfaces/` + `agri_twin/mqtt/` — MQTT port (`MQTTClient`, `InMemoryMQTTClient` for tests), topic catalog, clock/weather MQTT bindings. Contracts use a versioned JSON envelope (`1.0`); schemas in `schemas/`, validated by `agri_twin/contracts.py`.

Causal chain that must be preserved: `external event/data -> physical model -> state -> crop -> evaluation/control -> command -> actuator -> physical model`. Controllers and frontend never write resulting state (temperature, humidity, VWC) directly. No randomness substituting causality.

### Configuration files

- `config/app.json` — technical config. `config/crop_config.json` is an empty template.
- `src/crop_config.json` (effective crop catalog: stages, thresholds), `src/farm_config.json` (plots, location), `src/growth_model_config.json` (growth contracts, soil/greenhouse profiles, actuators), `src/crop_phenology.csv`. These are loaded by path relative to the repo root.
- Weather: Open-Meteo is used only for explicit downloads (`download_weather_for_plot`); simulations consume local CSV in `data/weather/` without network access.

### Phase 5.x scientific framework

Development proceeds in numbered phases tracked in `docs/architecture/PHASES.md`; phases are implemented in order. Each Phase 5.x delivery follows the same pattern — mirror it when adding a phase:

1. `src/agri_twin/application/<feature>.py` — a "Suite"/framework class built by composing earlier phase modules (e.g. `real_validation`, `scientific_calibration`, `post_calibration_validation`, `uncertainty_ensemble`, `sensitivity`, `domain/calibration`, `domain/parameter_audit`).
2. Exports added to `application/__init__.py`.
3. `tests/test_<feature>.py` (pytest).
4. `manual_phase5_<N>_<feature>_test.py` at repo root — offline, assertion-based delivery verification that writes a deterministic JSON report under `data/<area>/`.
5. `docs/phase5_<N>_<feature>.md` and a row in `PHASES.md`.

Scientific guardrails that every module enforces and tests check:
- Data sources are classified (`DataSourceClassification`: `REAL_VERIFIED`, `SYNTHETIC`, `SIMULATED_REAL_DATA_SUBSTITUTE`, `FORCING`, …). No `REAL_VERIFIED` data exists yet, so real calibration/validation/transferability must report `INSUFFICIENT_DATA` / `NOT_PERFORMED`; synthetic runs are labelled software-qualification only (`SOFTWARE_TEST_ONLY`, `QUALIFIED_SYNTHETIC`). Never claim calibration, data assimilation or experimental validation.
- Evaluation must not mutate `ParameterSet`s, the `ParameterRegistry` or `TwinState`; forcing data is kept separate from observations, and data leakage between calibration/holdout sets is detected.
- Reports are deterministic: repeated builds produce identical JSON and `configuration_hash`.
- Uncalibrated parameters stay marked as such (see `docs/scientific-limitations.md`, `docs/parameter_audit_report.md`); do not invent agronomic values (Tbase, GDD, etc.) without a traceable source.
