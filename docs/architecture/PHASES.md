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
