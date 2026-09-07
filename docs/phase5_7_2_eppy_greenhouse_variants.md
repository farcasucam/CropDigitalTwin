# Phase 5.7.2: eppy greenhouse variants

## Architecture

Phase 5.7.2 adds an optional configuration boundary around the simplified
Phase 5.7.1 greenhouse model. `EppyGreenhouseBuilder` loads a reproducible IDF
template, applies a small whitelist of greenhouse edits, validates the edited
objects, and saves a new IDF. It does not run EnergyPlus and does not change
the `GreenhousePhysicalModel` or `SimplifiedGreenhouseModel` contracts.

`GreenhouseVariant` records the name, description, source configuration,
modifications, configuration hash, and generated path. Its hash is SHA-256 of
canonical JSON, excluding the output path, so the same configuration produces
the same variant identity and filename.

## Optional dependency and status

The package extra is `eppy` (`eppy>=0.6.7,<0.7`); the core installation does
not import or require it. `detect_eppy()` reports one of `AVAILABLE`,
`UNAVAILABLE`, `INCOMPATIBLE`, or `MISCONFIGURED`. Generation also requires an
EnergyPlus IDD path through `idd_path` or `ENERGYPLUS_IDD`. Missing eppy or IDD
is an explicit configuration state, never a failure of the main test suite.

Install the optional tooling with:

```powershell
python -m pip install -e ".[dev,eppy]"
$env:ENERGYPLUS_IDD = "C:\EnergyPlusV23-1-0\Energy+.idd"
```

## IDF template

`templates/greenhouse/greenhouse_template.idf` is a minimal one-zone,
10 m x 8 m x 4 m greenhouse. It contains a floor, roof, glazed south wall and
window, infiltration, design ventilation, an ideal-load HVAC object, a shade
schedule/control, and output variables for temperature, humidity, CO2,
transmitted solar radiation, infiltration, and ventilation. It is an input
artifact for future integration, not a dynamic simulator in this phase.

## Variants and parameters

The builder exposes these deterministic variants:

| Variant | IDF parameter | Interpretation |
|---|---|---|
| `baseline` | none | template engineering baseline |
| `high_ventilation` / `low_ventilation` | `ventilation_ach` | design air changes per hour |
| `high_solar_transmission` / `low_solar_transmission` | `solar_transmission` | glazing solar heat gain coefficient |
| `shading` | `shading_fraction` | constant fractional shading schedule |
| `high_heating` / `low_heating` | `heating_supply_temperature_c` | ideal-load heating supply temperature |
| `high_cooling` / `low_cooling` | `cooling_supply_temperature_c` | ideal-load cooling supply temperature |

These are greenhouse engineering parameters. Existing equivalent
`ParameterRegistry` IDs remain the scientific provenance boundary; the builder
does not create a second scientific registry. Values in the template are
engineering defaults pending site inventory and calibration. No variant is
calibrated, and no crop or variety parameters are introduced.

## Reproducibility and validation

Only whitelisted objects and fields can be modified. The original template is
loaded and saved to a separate output directory. Object existence and modified
field presence are checked before saving. Invalid names and values raise
explicit errors. Output names include the first 12 hash characters and are
stable for equal variant configurations.

Run the focused tests with:

```powershell
python -m pytest tests/test_eppy_greenhouse_variants.py
python manual_phase5_7_2_eppy_variants_test.py
```

Tests requiring an installed eppy and IDD are skipped in a controlled way;
core tests cover detection, unavailable states, hashing, invalid configuration,
template location, and output contracts without eppy.

## Scope and scientific status

eppy is used here as an IDF configuration and variant-generation tool only.
This phase does not implement EnergyPlus Runtime, DataExchange, an
`EnergyPlusGreenhouseModel` backend, crop/microclimate feedback, or comparison
against the simplified model. The IDF values are reproducible engineering
placeholders, not measured, validated, or calibrated greenhouse parameters.
