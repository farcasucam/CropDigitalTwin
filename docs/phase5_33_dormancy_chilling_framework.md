# Phase 5.33 — Environment- and hemisphere-independent dormancy and chilling framework

## Result

```text
DORMANCY / CHILLING FRAMEWORK: POLICY_UNCERTAINTY (configurable policy; no universal start date)
NORTHERN AND SOUTHERN HEMISPHERE: same physiological abstraction; inversion test exact
ENVIRONMENT-DEPENDENT START: supported through explicit ChillingStartPolicy selection
CHILLING MODEL: CHILLING_HOURS implemented; UTAH / DYNAMIC declared, not implemented (OPEN)
REAL AGRICULTURAL DATA VERIFIED: NO    CALIBRATION PERFORMED: NO    BIOLOGICAL VALIDITY CLAIMED: NO
```

## 1. Scientific problem

When does chilling start, how is it counted, and how much is required, when species,
cultivar, latitude, hemisphere, altitude, climate and chilling model all vary? See
`docs/phase5_33_chilling_start_scientific_decision.md` for the audit, the Phase 5.32
diagnosis and the literature.

## 2. Why no universal date

Literature start dates (for example 1 November in Mediterranean Spain, 1 May in South
Africa, and 1 October / 1 April windows in global analyses) are analysis or protocol
conventions. The effective accumulation period follows local temperature and differs
within a single region (Murcia: altitude, coast). A fixed constant would also anchor the
twin to one hemisphere.

## 3. Architecture

```text
SimulationClock (only time authority)
      ↓ timestamp
WeatherState
      ↓
PhenologyEngine (existing)
      └── DormancyChillingController
            ├── ChillingStartPolicy   WHEN TO COUNT
            ├── ChillingModel          HOW TO COUNT
            └── profile requirement    HOW MUCH IS REQUIRED
      ↓ dormancy state (dormancy_released)
growth-stage eligibility (PhenologyEngine.growth_active) → growth engines
```

- `ChillingModel`: `model_type`, `unit`, `temperature_resolution`, `applicability`,
  `traceability`. `CHILLING_HOURS` (0–7.2 °C, the existing rule) is implemented;
  `UTAH` and `DYNAMIC` raise `MODEL_NOT_SUPPORTED`.
- `ChillingStartPolicy`:
  - `DORMANCY_STATE`, the default: count whenever endodormant;
  - `FIXED_DATE`: only with an explicit, timezone-aware configured instant; there is no built-in date;
  - `EFFECTIVE_CHILL_ONSET`: equivalent to `DORMANCY_STATE` under Chilling Hours, with the onset recorded;
  - `MODEL_DEFINED` and `ENVIRONMENTAL_WINDOW`: declared, not implemented.
- The default controller reproduces the previous computation bit for bit. No
  clock, state field, second phenology engine or chilling engine is added. The
  orchestrator accepts an optional `PhenologyEngine`, so a policy can be used in
  full-twin runs.
- Location (`latitude`, `longitude`, `elevation`) is metadata. The hemisphere is derived
  from latitude and used only to generate the synthetic climate calendar and to label
  results. The static audit checks that `domain/phenology.py` has no month names,
  calendar constructors, calendar attributes or location identifiers.

## 4. Outcomes of a dormancy season

`RELEASED`, `RELEASED_INCOMPLETE_CONTEXT`, `NO_CHILL`, `INSUFFICIENT_TEMPORAL_CONTEXT`,
`DORMANCY_NOT_RELEASED`, `MODEL_NOT_SUPPORTED`.

The temporal context counts as complete only if the record shows at least 24 h without
effective chill before the first effective chill hour. This is an engineering
classification rule: a record that begins inside the chill season cannot rule out
earlier accumulation.

## 5. Experiments (synthetic software experiments, not climatology)

- **Locations** (latitude, synthetic winter):
  - 20°N warm winter; 38°N Mediterranean (the 5.32 base profile); 50°N continental;
  - 20°S warm winter; 35°S temperate; 50°S cold.
  - Northern locations have their warmest day on day 150 or 200, southern ones on day 17.
- **Analysis window:** 365 days from the warmest day of the preceding synthetic summer.
  This window is derived from the climate, not from physiology.
- **Species:** peach, apple, plum. Plum keeps Suplum 26; the species requirements are
  unchanged.
- **Policy matrix:**
  - `DORMANCY_STATE`;
  - `FIXED_DATE` at an explicit protocol instant (1 Nov in the north, 1 May in the south);
  - the same with a shifted instant (1 Dec / 1 Jun);
  - `EFFECTIVE_CHILL_ONSET`;
  - `MODEL_DEFINED`.
- **Hemisphere inversion:** thermally equivalent years (daily anomalies off) at 38°N and
  35°S. Release happens at the same elapsed time (difference 0 h): 5 Feb in the north,
  6 Aug in the south. A deliberately northern-anchored counter that excludes
  June–September recovers only 45 of 861 chill hours, so an implementation anchored to
  October–May would fail.
- **Calendar independence:** the same recorded thermal sequence replayed from starts
  shifted by 0/40/91/182 days gives identical elapsed-time trajectories. Only an explicit
  `FIXED_DATE` instant changes the result: it excludes 129 h and delays release by 15 days.
- **Latitude / longitude:** the same weather with six different coordinate sets gives
  identical trajectories.
- **Climate:** warm, moderate, cold and highly variable winters at 38°N. Only the warm
  vs moderate ordering is asserted; a warm winter (+4 °C) leaves peach/apple/plum at 110 h
  (`DORMANCY_NOT_RELEASED`).
- **Phase 5.32 reproduction:**
  - record starts 1 Oct / 1 Nov → `RELEASED`;
  - 1 Dec → `RELEASED_INCOMPLETE_CONTEXT`;
  - 1 Jan / 1 Feb for peach and apple → `INSUFFICIENT_TEMPORAL_CONTEXT`.
- **Full twin:** peach through `ScenarioRunner` and the orchestrator from an explicit
  1-Nov record start. No growth before release, growth after it, maturity reached;
  restarts from 25/50/75 % checkpoints are exact, and the replay is identical.
- **Multi-plot:** three dormancy plots on one `SimulationClock` / `SimulationScheduler`
  equal their isolated runs.
- **Multi-cycle:** a second season starts from a fresh dormant state; carrying the
  released state forward would skip chilling. Dormancy induction remains an
  `OPEN_MODEL_CAPABILITY`.

## 6. Traceability

Registered in `ParameterRegistry`:
- `phenology.<crop>.chilling_requirement_hours`: grape, peach, plum, apple;
  `engineering_default`, `candidate_for_calibration`; the notes compare them with the
  literature ranges in `crop_phenology.csv`;
- `phenology.chilling_hours.lower_threshold` / `upper_threshold`: 0 / 7.2 °C;
- `phenology.chilling_model = CHILLING_HOURS`;
- `phenology.chilling_start_policy = DORMANCY_STATE`.

No value is labelled `literature` without evidence, and no parameter changed value.

## 7. Artifact

`data/phenology/chilling_framework_report.json` and `chilling_framework_README.md`.

- **Contents:** phase, status, species, varieties, hemispheres, latitudes, climate
  scenarios, chilling models, start policies, experiments, determinism, parameter
  integrity, static audit, open scientific decisions and limitations.
- **Separation of results:** `SOFTWARE_RESULT` rows are kept apart from the
  `SCIENTIFIC_EVIDENCE` literature rows.

## 8. What is NOT validated

It is not validated that the twin reproduces real dormancy of peach, apple, plum or any
other fruit tree. The following all remain pending real observations:
- cultivar requirements;
- the choice of chilling model;
- dormancy onset;
- the correctness of the release dates.

This phase shows only computational and temporal coherence, hemisphere independence,
policy behaviour, the absence of hard-coded physiological dates, traceability and
determinism.
