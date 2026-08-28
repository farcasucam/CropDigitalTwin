# Phenology Parameters

## Audit conclusion

The effective catalog is `src/crop_config.json`. The file contains seven
crops (`tomato`, `lettuce`, `pepper`, `grape`, `peach`, `plum`, `apple`) and
four project stages per crop. It contains descriptive stage names, month
lists, temperature stress limits, VPD limits, VWC limits, radiation limits,
and irrigation settings.

It does not contain a development base temperature, upper development cutoff,
GDD/GDH targets, accumulated transition values, chilling requirements, biofix,
stage durations, explicit transition rules, or cultivar-specific calibration.
The project stages also do not map unambiguously to published events such as
emergence, flowering, fruit set, veraison, or harvest.

Consequently no numerical phenology values have been copied into the crop
catalog and no automatic transition is active.

## Master table

| Crop | Transition method | Tbase (°C) | Tupper (°C) | Biofix | Chilling (hours/portions) | GDD/GDH targets (°C·day/°C·hour) | Units declared | Source | Confidence | Status |
|---|---|---:|---:|---|---|---|---|---|---|
| tomato | GDD candidate | null | null | null | not applicable/not assessed | null | Tbase °C; GDD °C·day | Penn State Extension, [Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days) | General method only | CALIBRATION_REQUIRED |
| lettuce | GDD candidate | null | null | null | not applicable/not assessed | null | Tbase °C; GDD °C·day | Penn State Extension, [Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days) | General method only | CALIBRATION_REQUIRED |
| pepper | GDD candidate | null | null | null | not applicable/not assessed | null | Tbase °C; GDD °C·day | Penn State Extension, [Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days) | General method only | CALIBRATION_REQUIRED |
| grape | Cultivar-specific forcing candidate | null | null | null | cultivar/site dependent | null | Tbase °C; forcing GDD °C·day; chilling hours/portions | Penn State Extension, [Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days) | General method only | CALIBRATION_REQUIRED |
| peach | Chilling then forcing candidate | null | null | null | null | null | Tbase °C; chilling hours/portions; forcing GDD °C·day | Penn State Extension, [Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days) | No crop/cultivar value established | CALIBRATION_REQUIRED |
| plum | Chilling then forcing candidate | null | null | null | null | null | Tbase °C; chilling hours/portions; forcing GDD °C·day | Penn State Extension, [Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days) | No crop/cultivar value established | CALIBRATION_REQUIRED |
| apple | Chilling then forcing candidate | null | null | null | null | null | Tbase °C; chilling hours/portions; forcing GDD °C·day | Penn State Extension, [Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days) | No crop/cultivar value established | CALIBRATION_REQUIRED |

The cited source supports the general method: GDD uses a crop/pest-specific base
temperature and may use an upper cutoff. It does not justify transition targets
for this project's crops, varieties, locations, or abstract stages. It is
therefore a method reference, not evidence for activating any row above.

## Proposed inactive contract

The existing optional validator accepts a future declaration such as:

```json
{
  "phenology": {
    "method": "gdd",
    "base_temperature_c": null,
    "upper_temperature_c": null,
    "biofix": null,
    "calibration_status": "CALIBRATION_REQUIRED",
    "source": {
      "reference": "...",
      "type": "scientific_publication"
    },
    "stages": [
      {"stage_key": "establishment", "gdd_to_next": null},
      {"stage_key": "vegetative_growth", "gdd_to_next": null}
    ]
  }
}
```

`stage_key` order must match the crop's explicit stage order. Numeric targets
are accepted only with a source reference. Null values are valid placeholders,
but they cannot activate transitions. The validator does not execute a
transition engine.

## Required before activation

For each crop and, where relevant, cultivar and site, supply a documented
biofix, method, Tbase, optional Tupper, chilling model and target, ordered
transition events, target GDD/GDH values, confidence, calibration status, and
the mapping from project stages to observed phenological events. These values
must be reviewed before a later phase activates automatic transitions.
