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

## Evidence matrix

The values below are evidence decisions, not operational parameters. `null`
means that no value can currently be defended for the project's crop,
cultivar, location and internal stage mapping.

The general thermal-method reference used in the rows is Penn State Extension,
[Understanding Growing Degree Days](https://extension.psu.edu/understanding-growing-degree-days),
updated 2026. It is cited for method context only, not as evidence for any
crop-specific value.

| Crop | Event mapping | Method | Tbase (°C) | Tupper (°C) | Biofix | Chilling | GDD/GDH target | Units | Source/context | Confidence | Status |
|---|---|---:|---:|---|---|---|---|---|---|
| tomato | internal stages not mapped to emergence/flowering/harvest | GDD candidate | null | null | null | not assessed | null | Tbase °C; GDD °C·day | Penn State Extension (2026), general method; not tomato/cultivar/site data | General method only | CALIBRATION_REQUIRED |
| lettuce | internal stages not mapped to emergence/head formation/harvest | GDD candidate | null | null | null | not assessed | null | Tbase °C; GDD °C·day | Penn State Extension (2026), general method; not lettuce/cultivar/site data | General method only | CALIBRATION_REQUIRED |
| pepper | internal stages not mapped to transplant/flowering/harvest | GDD candidate | null | null | null | not assessed | null | Tbase °C; GDD °C·day | Penn State Extension (2026), general method; not Capsicum cultivar/site data | General method only | CALIBRATION_REQUIRED |
| grape | internal stages not mapped to budburst/veraison/harvest | cultivar-specific forcing candidate | null | null | null | cultivar/site dependent; model unselected | null | Tbase °C; forcing GDD °C·day; chilling hours/portions | Penn State Extension (2026), general cutoff method; not Vitis cultivar data | General method only | CALIBRATION_REQUIRED |
| peach | internal stages not mapped to bloom/pit hardening/harvest | chilling then forcing candidate | null | null | null | null | null | Tbase °C; chilling hours/portions; forcing GDD °C·day | Penn State Extension (2017), cultivar/site production context; no project cultivar model | Contextual only | CALIBRATION_REQUIRED |
| plum | internal stages not mapped to bloom/fruit sizing/harvest | chilling then forcing candidate | null | null | null | null | null | Tbase °C; chilling hours/portions; forcing GDD °C·day | Penn State Extension (2017), related Prunus context; species/cultivar model absent | Contextual only | CALIBRATION_REQUIRED |
| apple | internal stages not mapped to budburst/flowering/harvest | chilling then forcing candidate | null | null | null | null | null | Tbase °C; chilling hours/portions; forcing GDD °C·day | University of Minnesota Extension (2026), cultivar/rootstock context; no project cultivar model | Contextual only | CALIBRATION_REQUIRED |

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

## Local calibration dataset

No local phenology observations were found in the repository. The minimum
dataset should record, per season and plot: crop, cultivar, rootstock when
relevant, farm/plot identity, production system, coordinates, sowing or
transplant date, emergence or budburst, flowering, fruit set, veraison, pit
hardening, head formation, harvest, daily mean/min/max temperature, and the
applicable chilling hours or chill portions for temperate fruit. Each
observation should identify its source and confidence so calibration and
validation seasons remain separate.

The current plots provide `Suplum 26`, `RAF`, `Monastrell` and `Lamuyo`, but no
rootstock or event dates. The meteorological CSV is not a phenology dataset.

## Phase 4.7 deep research attempt and its limitation

A deeper research pass was attempted for all seven crops, prioritizing Murcia,
Spain, Mediterranean, European and then international sources, and
specifically searching for `RAF` tomato, `Lamuyo` pepper, `Monastrell` grape
and `Suplum 26` plum. The session's web access to primary sources returned:

- HTTP 404 or "not found" redirects for USU, Oregon State, and
  grapes.extension.org phenology/GDD pages;
- HTTP 403 or bot-verification walls for ScienceDirect and MDPI;
- zero results from a PubMed search for tomato base temperature/GDD;
- accessible University of Minnesota and Penn State Extension pages that cover
  cultivation practice (planting, pruning, marketing, cultivar lists) but do
  not publish a numeric Tbase, Tupper, GDD/GDH target, or chilling requirement
  for any of the seven crops or their events.

No cultivar-specific (`RAF`, `Lamuyo`, `Monastrell`, `Suplum 26`) phenology
parameter was found through any source reachable in this session. This is
reported explicitly rather than substituted with unverified figures from
general agronomic knowledge that was not confirmed by a fetched, citable
source in this session.

## Master parameter table (Phase 4.7)

| Crop | Cultivar | Model | Tbase °C | Tupper °C | Biofix | Event | GDD/GDH | Evidence | Confidence | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| tomato | RAF (project cultivar; no published thermal-time data found) | GDD (candidate) | none found | none found | none found | emergence/flowering/harvest not quantified | none found | INSUFFICIENT | none | UMN Extension, Penn State Extension: cultivation practice only, no Tbase/GDD figures |
| lettuce | not specified in project | GDD (candidate) | none found | none found | none found | emergence/head formation/harvest not quantified | none found | INSUFFICIENT | none | No lettuce-specific numeric source retrieved this session |
| pepper | Lamuyo (project cultivar; no published thermal-time data found) | GDD (candidate) | none found | none found | none found | transplant/flowering/harvest not quantified | none found | INSUFFICIENT | none | UMN Extension, Penn State Extension (pepper production): cultivation practice only |
| grape | Monastrell (project cultivar; no published thermal-time data found) | chilling + forcing (candidate, not GDD-only) | none found | none found | none found | budburst/veraison/harvest not quantified | none found | INSUFFICIENT | none | Targeted grape-phenology sources (Oregon State, grapes.extension.org) returned 404/unreadable this session |
| peach | not specified in project | chilling then forcing (candidate) | none found | none found | none found | bloom/pit hardening/harvest not quantified | none found | INSUFFICIENT | none | Penn State Extension (Peach Production, 2017): cultivar/production context only, no chill/GDD figures |
| plum | Suplum 26 (project cultivar; identity/breeder data not verifiable this session) | chilling then forcing (candidate) | none found | none found | none found | bloom/fruit sizing/harvest not quantified | none found | INSUFFICIENT | none | No `Prunus domestica`/`salicina` or `Suplum 26`-specific source retrieved this session |
| apple | not specified in project | chilling then forcing (candidate) | none found | none found | none found | budburst/flowering/harvest not quantified | none found | INSUFFICIENT | none | UMN Extension (Growing Apples): cultivar/rootstock context only, no chill/GDD figures |

No row reaches `DIRECT` or `TRANSFERABLE` evidence in this session. All rows
are `INSUFFICIENT` because no fetched source provided a crop-specific,
citable numeric value for Tbase, Tupper, biofix, or a GDD/GDH target.

## Stage mapping and candidate selection (Phase 4.7)

| Crop | Internal stage | Recommended parameter | Value | Unit | Status | Justification |
|---|---|---|---|---|---|---|
| tomato | establishment / vegetative_growth / yield_maturation / post_harvest_dormancy | Tbase, GDD to flowering/harvest | NO_NUMERIC_CANDIDATE | °C, °C·day | INSUFFICIENT_EVIDENCE | No source retrieved this session ties a number to tomato, `RAF`, or these stages |
| lettuce | establishment / vegetative_growth / yield_maturation / post_harvest_dormancy | Tbase, GDD to head formation/harvest | NO_NUMERIC_CANDIDATE | °C, °C·day | INSUFFICIENT_EVIDENCE | No lettuce-specific numeric source retrieved this session |
| pepper | establishment / vegetative_growth / yield_maturation / post_harvest_dormancy | Tbase, GDD to flowering/harvest | NO_NUMERIC_CANDIDATE | °C, °C·day | INSUFFICIENT_EVIDENCE | No source retrieved this session ties a number to pepper, `Lamuyo`, or these stages |
| grape | establishment / vegetative_growth / yield_maturation / post_harvest_dormancy | Chilling target, Tbase, forcing GDD to budburst/veraison | NO_NUMERIC_CANDIDATE | chill units, °C, °C·day | INSUFFICIENT_EVIDENCE | Grape-specific phenology sources were unreachable (404) this session |
| peach | establishment / vegetative_growth / yield_maturation / post_harvest_dormancy | Chilling requirement, Tbase, forcing GDD to bloom | NO_NUMERIC_CANDIDATE | chill hours/portions, °C, °C·day | INSUFFICIENT_EVIDENCE | Retrieved source lacks numeric chilling/GDD data |
| plum | establishment / vegetative_growth / yield_maturation / post_harvest_dormancy | Chilling requirement, Tbase, forcing GDD to bloom | NO_NUMERIC_CANDIDATE | chill hours/portions, °C, °C·day | INSUFFICIENT_EVIDENCE | No `Suplum 26` or species-specific numeric source retrieved this session |
| apple | establishment / vegetative_growth / yield_maturation / post_harvest_dormancy | Chilling requirement, Tbase, forcing GDD to budburst | NO_NUMERIC_CANDIDATE | chill hours/portions, °C, °C·day | INSUFFICIENT_EVIDENCE | Retrieved source lacks numeric chilling/GDD data |

All stage mappings above remain `UNMAPPED` to a specific quantified
phenological event because no candidate value exists to attach to them.

## Seven-crop checklist (Phase 4.7)

For every crop, the answer to each question below is negative given sources
retrieved in this session:

1. Tbase available? No.
2. Tupper available? No.
3. Biofix available? No.
4. GDD/GDH per event available? No.
5. Cultivar-specific evidence available (`RAF`, `Lamuyo`, `Monastrell`,
   `Suplum 26`)? No.
6. Transferable to Murcia? Not applicable; there is no base value to
   transfer.
7. Local data missing: cultivar-confirmed phenological event dates
   (emergence/budburst, flowering, fruit set, veraison when applicable,
   harvest), local daily temperature during those seasons, and for grape,
   peach, plum and apple, chilling observations (hours or portions) at the
   plot locations.

No parameter in this document is marked `CANDIDATE — NOT ACTIVATED`, because
no numeric candidate met even a provisional evidentiary bar in this session.
