# Integrated Digital Twin Configuration

The active crop and plot catalogs are `src/crop_config.json` and
`src/farm_config.json`. The growth contract is `src/growth_model_config.json`.

Configuration provenance is explicit:

- `ENGINEERING_APPROXIMATION`: temporary baseline used to keep the model
  executable when site data is absent;
- scientific/base evidence: method or published context that is traceable but
  not necessarily transferable to a project variety;
- plot/variety-specific: must be supplied by inventory or observations;
- `CALIBRATED`: reserved for validated local parameter fitting.

Greenhouse geometry, thermal properties, actuator capacities, cultivar
parameters, soil hydraulic values, nutrient pools, and phenology event
mapping remain calibration or inventory inputs where currently null.
`CropDigitalTwinOrchestrator` accepts the greenhouse mode and actuator
commands explicitly, so no environment is inferred from a plot name.