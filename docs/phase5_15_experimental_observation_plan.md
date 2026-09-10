# Phase 5.15: experimental observation and data acquisition plan

**THIS IS AN OBSERVATION PLAN, NOT A CALIBRATION RESULT.**

## Objective and scientific scope

Phase 5.15 designs the future field and greenhouse campaign required to collect observations for later identifiability analysis and calibration. It does not collect data, connect sensors, execute a campaign, fit parameters, assimilate observations or claim experimental validation.

The plan is derived from the existing `ParameterRegistry` and `ParameterIdentifiabilityAnalyzer`:

```text
ParameterRegistry
  -> ParameterIdentifiabilityAnalyzer
  -> parameter / observation matrix
  -> confounders
  -> ExperimentalObservationPlan
  -> future field measurements
  -> ObservationIngestion
  -> ObservationDataset
  -> TemporalAlignment / ErrorDiagnostics
  -> future identifiability and calibration
```

`PLANNED` means a measurement task has been designed. It does not mean measured, identified, calibrated or validated. `UNKNOWN` is retained when the repository has no defensible method, frequency, uncertainty target or quantitative requirement.

## Plan representation

`ExperimentalObservationPlan` is a read-only application contract. Each `ObservationPlanItem` preserves:

- real `parameter_ids` from the registry;
- observable variable when the 5.14 requirement text supports one;
- crop, variety, plot, environment and phenological stage scope;
- purpose, conditions, confounders and future calibration relation;
- method, unit, temporal resolution and uncertainty as known or `UNKNOWN`/`TO_BE_DEFINED`;
- quality flags compatible with `ObservationIngestion`;
- evidence, confidence, requirement source, priority and plan status.

The plan has deterministic filters by parameter, observable, crop, variety, plot, environment and stage. It can be exported as JSON-compatible data and validated by `schemas/observation_campaign_plan.schema.json`.

## Priorities and requirements

Priorities are `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` and `UNKNOWN`. They are planning priorities, not scientific certainty. They are derived conservatively from registry category, calibration permission and unresolved confounders. No arbitrary sample count, interval, campaign count or error threshold is introduced.

Requirement source distinguishes `scientific_requirement`, `engineering_recommendation`, `project_requirement` and `unknown`. Current generated items use `unknown` unless the existing registry provides evidence. The absence of an instrument protocol is represented by `TO_BE_DEFINED`, not an invented method.

## Measurement taxonomy

The plan can link registry requirements to the existing observation variables:

- phenology: stage transitions, budburst, flowering, fruit set, veraison, maturity and harvest when the registry requests phenology;
- canopy and growth: LAI, biomass and canopy observations when requested;
- radiation: solar radiation and canopy/radiation evidence where present;
- water: soil water/VWC, irrigation and transpiration where present;
- microclimate: temperature, relative humidity, VPD, radiation and CO2;
- production: yield, fruit mass and fruit count where the existing variable contract supports them;
- greenhouse: internal climate and actuator records when they control a confounder.

Actuator commands must remain distinct from measured environmental state. A command to ventilate, heat, cool, shade, inject CO2 or irrigate is not proof that the physical state changed.

## Crops, cycles and environments

The plan covers tomato, lettuce, pepper, grape, peach, plum and apple through the registry. Known varieties remain tomato/RAF, pepper/Lamuyo, grape/Monastrell and plum/Suplum 26. Lettuce, apple and peach use generic scope; no local variety is invented. Annual and perennial scopes remain distinct. Lettuce cycle IDs and plot IDs are retained for future observations, and perennial stages can span dormancy, budburst, flowering, fruit set, growth, maturity and harvest when the existing model/registry supports those concepts.

Outdoor and greenhouse are separate planning scopes. Greenhouse tasks may include internal temperature, RH, VPD, radiation, CO2, ventilation, heating, cooling, shading and transmission only where they connect to an existing model mechanism or confounder. No actuator is requested merely for operational interest.

## Confounder mitigation

The plan preserves 5.14 confounders rather than claiming to remove them. Combined canopy, radiation and biomass observations can support separation of growth scaling terms; temperature and phenology events provide evidence for thermal timing; soil water, irrigation and crop response help separate water effects; temperature/RH/VPD are recorded consistently; CO2 tasks include ventilation and supply context; stress, damage and senescence require observations that distinguish natural senescence from environmental damage.

These designs reduce confounding and provide additional evidence. They do not guarantee identifiability.

## Technician workflow

The blank template is `data/templates/agricultural/observation_campaign.csv`. It extends the existing technician package with `cycle_id`, stage, method, quality, uncertainty, operator, provenance and notes. It contains no measurements. Future real records should preserve timezone-aware timestamps, plot/cycle identity, crop, variety, environment, method, unit and quality, then enter through `ObservationIngestion`.

Use empty values for unknown measurements, never zero as a substitute. Use `VALID`, `MISSING`, `ESTIMATED`, `INVALID`, `DUPLICATE`, `OUT_OF_RANGE` and `UNIT_ERROR` according to the existing ingestion contract. Unknown metrology remains unknown until an instrument or protocol is documented.

## Future calibration boundary

A plan is compatible with:

```text
plan -> actual observations -> ObservationIngestion -> ObservationDataset
     -> TemporalAlignment -> ErrorDiagnostics -> ParameterIdentifiability
     -> future CalibrationCase -> independent validation
```

Phase 5.15 does not create a `CalibrationCase` from an empty plan and does not treat a planned task as a measured observation.

## Limitations and status

Real agronomic data are unavailable. The campaign has not been executed. Measurement uncertainty, sampling quantities, frequencies and instrument protocols remain unknown where the repository has no evidence. The design must be reviewed when real sites and instruments are selected. Future calibration requires actual observations, quality control, coverage, confounder review and independent validation.

**REAL AGRONOMIC DATA: NOT AVAILABLE**  
**OBSERVATION CAMPAIGN: DESIGNED, NOT EXECUTED**  
**CALIBRATION: NOT PERFORMED**  
**DATA ASSIMILATION: NOT IMPLEMENTED**  
**EXPERIMENTAL VALIDATION: NOT CLAIMED**

**PHASE 5.15 COMPLETE — EXPERIMENTAL OBSERVATION / DATA ACQUISITION PLAN READY — REAL AGRONOMIC DATA NOT AVAILABLE — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED**
