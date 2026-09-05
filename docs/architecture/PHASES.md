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
