# Phase 5.1 Scientific Parameter Audit and Traceability

## Scope

This phase creates a formal, deterministic inventory of parameters used by
the completed Phase 4 model. It does not calibrate, optimize, or claim
scientific validation. Existing physical behavior and values are preserved.

The implementation is `ParameterRecord`, `ParameterRegistry`, and
`ParameterAudit` in `src/agri_twin/domain/parameter_audit.py`. The registry is
rebuilt from the active repository files:

- `src/crop_config.json` for stage thresholds;
- `src/growth_model_config.json` for growth, soil, greenhouse, actuators and
  nutrients;
- `src/crop_phenology.csv` for external evidence rows;
- `src/farm_config.json` for plot-specific project data;
- explicit runtime-code inventory for constants currently hardcoded in the
  radiation, greenhouse and water services.

Regenerate the report with:

`python tools/generate_parameter_audit.py`

The generated output is [parameter_audit_report.md](parameter_audit_report.md).

## Traceability fields

Each record contains identity, description, category, subsystem, crop,
variety, internal stage, unit, value/range, source type/reference/detail,
evidence level, confidence, calibration status, calibration permission,
required observations, notes and usage metadata.

Categories are `biological`, `environmental`, `soil`, `management`,
`greenhouse`, and `engineering_default`. The last category is intentionally
separate: a value needed to run the model is not presented as a validated
biological parameter.

Source types are `literature`, `project_data`, `measured_data`, `derived`,
`engineering_default`, `calibrated`, and `unknown`. `evidence_level` describes
the directness and applicability of evidence (`high`, `medium`, `low`,
`none`); `confidence` describes confidence in applying that evidence to this
project scope. They are deliberately independent. For example, a strong
publication for another cultivar may have high evidence but only medium
project confidence.

Calibration statuses are `not_calibrated`, `candidate_for_calibration`,
`calibrated`, `fixed`, and `not_applicable`. A calibrated record must have
source type `calibrated`; this phase creates no such record.

## Validation rules

The deterministic audit detects duplicate IDs, missing units, invalid ranges,
non-finite/out-of-range numeric values, invalid crop/stage scopes, literature
without a reference, inconsistent calibrated metadata, and engineering
defaults incorrectly labelled with high evidence. It also reports records
that are unknown, approximate, low/none evidence, or calibration candidates.

External phenology events such as `budburst`, `flowering`, and `maturity` are
kept as evidence notes, not silently converted into the four internal project
stages. Cultivar names from evidence are preserved only when the source
actually identifies them. The project variety `RAF` therefore does not make a
generic tomato record RAF-specific.

## Calibration and external models

Potential calibration candidates include Tbase/Tupper, thermal/chilling and
forcing requirements, RUE, LAI/SLA, senescence, biomass partition, maturity,
stress-response coefficients, soil hydraulic properties, nutrient pools,
greenhouse properties, and actuator capacities. Observed weather, simulation
time, and system clocks are not crop parameters. Soil, greenhouse and actuator
parameters may be calibrated as external physical subsystems, not treated as
genetic crop coefficients.

DSSAT is an external comparison and calibration reference only. Its cultivar
coefficients are not runtime dependencies and are not copied as universal
values. The same distinction applies to FAO or other method references: a
method source does not automatically validate a project-specific parameter.

## Scientific debt

The generated report lists all unknown, engineering-default, low/none-evidence
and calibration-candidate records by crop. Main current debt is the absence of
local cultivar/plot observations, unfilled greenhouse inventory, null
actuator capacities, approximate hardcoded radiation/ET/greenhouse constants,
and unmapped external phenology events. These are inputs to Phase 5.2, not
silently resolved in this audit.

## Verification

Unit tests are in `tests/test_parameter_audit.py`. The delivery audit is
`manual_phase5_1_parameter_audit_test.py`. Full regression remains mandatory.
This phase establishes traceability and calibration readiness only; it does
not declare the model scientifically validated.