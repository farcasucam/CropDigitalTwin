# Plan de Implementación por Fases

| Fase | Resultado | No avanzar hasta |
|---|---|---|
| 0 | Contratos + estructura + Docker MQTT | tests/imports OK |
| 1 | Clock + scheduler | tests de tiempo OK |
| 2 | Weather | series reproducibles |
| 3 | Física | causalidad física OK |
| 4 | Crop | stress/growth OK |
| 4.7.1 | Growth-model configuration contract | calibrated values and activation remain pending |
| 4.7.2 | Persistent crop growth state | deterministic dynamics remain pending |
| 4.7.3 | Phenology, chilling and maturity engine | calibrated crop/variety profiles remain pending |
| 4.7.4 | Radiation, LAI and biomass engine | water, nutrient and climate limitation models remain pending |
| 4.7.5 | Simplified crop water balance | soil calibration and controller policy remain pending |
| 4.7.6 | Simplified nutrient availability | field nutrient data and calibration remain pending |
| 4.7.7 | Climate stress, extreme events and accumulated damage | crop/plot calibration remains pending |
| 4.7.8 | Greenhouse microclimate and actuators | site inventory and actuator calibration remain pending |
| 4.7.9 | Integrated plant digital twin | end-to-end calibration and scenario validation remain pending |
| 5.1 | Scientific parameter audit and traceability | calibration and validation remain pending |
| 5.2 | Calibration framework and predictive-model boundary | scientific datasets and calibration remain pending |
| 5.3 | Scientific validation, metrics and benchmarking | independent observations remain pending |
| 5.4 | Reproducible agronomic scenarios | scenarios are synthetic and not scientific validation |
| 5.5 | Crop and variety calibration protocol | no local agronomic observations; all protocols are INSUFFICIENT_DATA |
| 5.6 | Crop growth, biomass and LAI engine | mechanistic simplified model; not calibrated |
| 5.7.1 | Greenhouse physical model and simplified microclimate contract | common contract and simplified backend implemented; EnergyPlus remains deferred |
| 5.7.2 | Optional eppy greenhouse variants | reproducible IDF variants only; EnergyPlus runtime remains deferred |
| 5.7.3 | Optional EnergyPlus greenhouse backend | Python API adapter and explicit unavailable state; crop feedback remains deferred |
| 5.7.4 | Crop-greenhouse microclimate feedback | bounded physical exchange loop with audited CO2, thermal and water balances; calibration and systematic backend comparison remain deferred |
| 5.x audit | Transversal scientific and architectural audit of Phases 5.1-5.7.4 | architecture and traceability audited; model remains mechanistic simplified and not calibrated or experimentally validated |
| 5.8 | Real observation data readiness and ingestion | ingestion pipeline ready; real data availability, calibration and experimental validation remain unclaimed |
| 5.9 | Synthetic simulation reference data and agricultural technician templates | synthetic data is for software testing only; real agronomic data, calibration and experimental validation remain unclaimed |
| 5.10 | Temporal crop-cycle execution and multi-plot simulation | single SimulationClock/Scheduler; synthetic software tests only; calibration and experimental validation remain unclaimed |
| 5.11 | Temporal TwinState management, multi-plot snapshots and in-memory history | twin state and temporal queries ready; no database, calibration or experimental validation |
| 5.12 | Temporal TwinState to Observation alignment and comparison | temporal alignment and comparison ready; no calibration, data assimilation or experimental validation |
| 5.13 | Error diagnostics and multilevel evaluation | error diagnostics ready; calibration not performed, data assimilation not implemented, experimental validation not claimed |
| 5.14 | Parameter identifiability and calibration readiness | parameter identifiability/readiness framework ready; real agronomic data unavailable, calibration not performed, experimental validation not claimed |
| 5.15 | Experimental observation plan and data acquisition design | campaign designed but not executed; real agronomic data unavailable, calibration not performed, experimental validation not claimed |
| 5.16 | Modular instrumentation readiness and simulated acquisition backend | simulated acquisition only; real sensor deployment, calibration and experimental validation remain unexecuted |
| 5.17 | Real acquisition adapter contract and external source substitution | synthetic and future-real sources share the same `AcquisitionRecord`; no real sensor connection, hardware dependency, calibration or validation claimed |
| 5.18 | Synthetic observation campaign & scientific pipeline qualification | end-to-end synthetic campaign orchestrating 5.8-5.17 components; software pipeline qualified, calibration not performed, data assimilation not implemented, experimental validation not claimed |
| 5.19 | Real agronomic data integration & calibration readiness | first real-data-ready ingestion/manifest/quality-report/readiness-gate layer; `ObservationIngestion` deduplication now keys on `(plot_id, cycle_id, variable, timestamp)`; calibration readiness assessed but not performed, data assimilation not implemented, experimental validation not claimed |
| 5.20 | Scientific readiness gate & synthetic benchmarking | global software/data/scientific-validation readiness report plus ten deterministic synthetic software benchmarks; software ready, real agronomic data not verified, calibration blocked/not performed, data assimilation not implemented, experimental validation not claimed |
| 5.21 | Synthetic real-data substitute & scientific sensitivity framework | deterministic synthetic real-data substitute preserving the common observation contract, future real-data substitution path, and one-at-a-time parameter sensitivity analysis without calibration or experimental validation |
| 5.23 | Scientific uncertainty & scenario ensemble framework | deterministic uncertainty definitions, scenario ensembles and synthetic robustness reports that preserve the same scientific guardrails and never claim real validation |
| 5.24 | Integrated scientific benchmark & reproducible evaluation | orchestration of existing scenarios, sensitivity, uncertainty and ensemble contracts with deterministic hashes, matrix coverage and explicit synthetic-only scientific status |
| 5.25 | Real validation readiness & out-of-sample evaluation gate | source audit, forcing/observation separation and reusable validation pipeline; current project state remains insufficient real data and experimental validation unclaimed |
| 5.26 | Conditional scientific calibration & overfitting control | readiness-gated orchestration of the existing grid calibrator, parameter identifiability, bounds, explicit calibration/holdout split and transactional synthetic-only software tests |
| 5.27 | Independent post-calibration validation gate | consumes only a valid 5.26 calibrated parameter set and independent observations; current state remains validation not performed because no real data or scientific calibration exists |
| 5.29 | Integrated synthetic validation with plausible agronomic scenarios | fixed-model `SYNTHETIC_INTEGRATED_VALIDATION` over 30 cases (7 crops, outdoor/greenhouse, stress/recovery, full cycles), restart, persistence, multi-plot/multi-cycle, feedback loop, determinism and static audit; greenhouse-crop integration not qualified (closed-greenhouse latent-flux defect open); real data, calibration and experimental validation remain unclaimed |
| 5.30 | Greenhouse-Crop Physical Corrections | baseline 687 passed/12 skipped; corrected saturation-limited transpiration, configured ventilation, indoor-outdoor heat exchange with exact first-order integration, vapour-density humidity balance, indoor microclimate consumed by the crop (no indoor rain), single CO2 response, endodormancy growth gate, feedback iteration start state, outdoor VPD and misting sign; new physical tests and manual A-G; Phase 5.29 re-run with greenhouse-crop integration synthetically qualified; not calibration, real data and experimental validation remain unclaimed |
| 5.31 | Greenhouse-Crop Physical Benchmark | baseline 731 passed/12 skipped; 47 analytical benchmarks (energy closure and exchange sign, ventilation, humidity/VPD incl. 5.29 saturation regression, latent, radiation, CO2, crop microclimate, feedback, determinism, units) all PASS; fixed backend cache holding unconverged feedback candidates, registered active greenhouse defaults, single psychrometric definition; EnergyPlus optional/unavailable; benchmarks qualified synthetically only, no calibration, real data or experimental validation |
| 5.32 | Plausible synthetic climate scenarios and full-campaign validation | baseline 787 passed/12 skipped; WeatherEngine optional seasonal cycle and continuous seeded daily variability, ramped ScenarioEvent overlays (cold_wave, wind); 12 mandatory + 2 supplementary scenarios x 7 crops outdoor and 3 greenhouse (122 campaigns) with invariants, direction checks (MODEL_BEHAVIOR_CONSISTENT), restart, replay, multi-plot/multi-cycle; peach/apple chilling onset left as OPEN_SCIENTIFIC_DECISION; not calibration, real data or experimental validation |
| 5.33 | Environment- and hemisphere-independent dormancy / chilling framework | baseline 854 passed/12 skipped; DormancyChillingController inside PhenologyEngine (ChillingStartPolicy + ChillingModel + requirement; default reproduces previous behaviour), registered chilling parameters, 6 synthetic NH/SH locations x peach/apple/plum x 5 policies, exact hemisphere inversion, calendar and latitude independence, 5.32 diagnosed as INSUFFICIENT_TEMPORAL_CONTEXT; decision POLICY_UNCERTAINTY (no universal start date), model selection and dormancy induction open; no calibration or biological validation |
| 5.34 | Chilling model policy, STRICT fallback and canonical configuration | baseline 892 passed/12 skipped; single canonical DormancyConfiguration (requested + effective + fallback metadata) and one canonicalization path; DEFAULT is an alias of STRICT; UTAH/DYNAMIC declared, not implemented, explicit STRICT fallback to CHILLING_HOURS with request recorded; deterministic configuration/effective SHA-256, JSON round trip, 20 negative cases; DEFAULT and DYNAMIC requests reproduce all 5.33 DORMANCY_STATE rows and the full twin; registry adds phenology.chilling_fallback_policy; no model, requirement or date changed, no calibration or biological validation |
| 5.35 | Alternative chilling models: Utah and Dynamic | baseline 954 passed/12 skipped; published Utah weight table and Dynamic Model (Erez et al. 1990 constants, exact hour-by-hour equivalence with the chillR reference loop) behind the single ChillingModel/DormancyChillingController path; units chill_hours / utah_chill_units / chill_portions never converted; serializable Dynamic state with exact JSON checkpoint/restart; both IMPLEMENTED_UNPARAMETERIZED (no activated species requirement), unparameterized requests keep the 5.34 STRICT fallback with identical hashes, execution only with explicit SOFTWARE_TEST_ONLY requirements, injected bare models MODEL_NOT_READY; 20 fixed literature constants registered; no requirement invented or activated, no calibration or biological validation |
| 5 | Actuators + Controller | comandos y estados separados |
| 6 | Eventos + escenarios | replay reproducible |
| 7 | Storage | histórico consultable |
| 8 | Semantic Engine | packets trazables |
| 9 | Backend | API/WebSocket funcional |
| 10 | Frontend | dashboard/control funcional |
| 11 | Experiments | comparación A/B |
| 12 | Hardening | integración completa |

## Orden obligatorio de implementación

No desarrollar primero la UI y luego adaptar el dominio.

Primero:
1. dominio;
2. contratos;
3. motor;
4. MQTT;
5. API;
6. UI.

El frontend consume contratos existentes.
