# Dormancy / chilling framework (Phase 5.33)

Synthetic software experiments of the environment- and hemisphere-independent dormancy/chilling layer. SOFTWARE_RESULT entries are
model outputs; SCIENTIFIC_EVIDENCE entries are literature rows from src/crop_phenology.csv. Nothing here is calibration or biological validation.

- status: `PASS`; decision: `POLICY_UNCERTAINTY`
- report hash: `2eee01cfbc22fce1ef2d74235c745a0a7314ba4ad48db0e415d2ea5a3585679e`

## Sections

- policy_matrix: `PASS`
- hemisphere_inversion: `PASS`
- calendar_independence: `PASS`
- location_metadata_independence: `PASS`
- climate_comparison: `PASS`
- phase532_reproduction: `PASS`
- multi_plot: `PASS`
- multi_cycle: `PASS`
- twin_integration: `PASS`
- determinism: `PASS`
- static_audit: `PASS`
- parameter_integrity: `PASS`

## Open scientific decisions

- `CHILLING_START_POLICY` (POLICY_UNCERTAINTY): several defensible policies exist (dormancy state, explicit protocol date, effective onset, model-defined onset); literature start dates are protocol conventions that differ by region and hemisphere; the policy stays configurable and no universal calendar date is adopted
- `CHILLING_MODEL_SELECTION` (OPEN_SCIENTIFIC_DECISION): only Chilling Hours is implemented; the project evidence for apple is in chill portions (Dynamic Model), and Murcia studies use the Dynamic Model; implementing Utah/Dynamic requires model parameters and cultivar requirements in the same unit
- `DORMANCY_INDUCTION` (OPEN_MODEL_CAPABILITY): no transition from post-harvest into endodormancy exists; every dormancy season starts from an explicitly configured dormant state
- `CULTIVAR_REQUIREMENTS` (OPEN_SCIENTIFIC_DECISION): runtime requirements are species-level engineering defaults; literature rows exist but are NOT_ACTIVATED and require cultivar selection and unit consistency before use
