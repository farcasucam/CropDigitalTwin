# Phase 5.33 — Chilling start: audit and scientific decision

## 1. Implementation before Phase 5.33

- `PhenologyProfile` (domain/phenology.py) holds `perennial`, `chilling_requirement_hours`
  (grape 400, peach 600, plum 500, apple 600 h) and the Chilling Hours thresholds
  `chilling_min_temperature_c = 0.0`, `chilling_max_temperature_c = 7.2`.
- `PhenologyEngine.advance`: while a perennial state has `dormancy_released = False`, each
  step adds `dt/3600` chill hours if `0 <= T <= 7.2 °C`; dormancy is released when the
  requirement is reached; GDD (forcing) accumulates only after release; the first GDD
  stage target (`establishment → vegetative_growth`) is the budburst/leaf-out proxy.
- **Where chilling starts:** implicitly at the start of the simulation record, because
  the dormant state is an initial condition. There is no date, no hemisphere, no
  latitude, no temperature-persistence criterion and no dormancy-induction transition
  (post-harvest never re-enters dormancy). The model counts chill **hours**, not
  Utah units or chill portions. There is no artificial window, but the record start is a
  window: nothing before it can be counted.
- **Traceability gap found:** the runtime requirements and thresholds were not in the
  `ParameterRegistry` (only a `contract.chilling_requirement` placeholder with no value).

## 2. Why peach and apple did not leave dormancy in Phase 5.32

Reproduction with the 5.32 `BASE_SEASON` climate (seed 532), counting from different
experimental record starts:

| Record start | Chill hours available (Oct–Jun) | Peach/apple (600 h) | Plum (500 h) |
| --- | --- | --- | --- |
| 1 Oct | 872 | released 4 Feb | released 24 Jan |
| 1 Nov | 872 | released 4 Feb | released 24 Jan |
| 1 Dec | 825 | released 9 Feb (context incomplete) | released 29 Jan |
| 1 Jan | 589 | not released | released 28 Feb |
| 1 Feb | 301 | not released | not released |

Effective chill starts in mid-November in that synthetic climate. The 5.32 peach/apple
cycles started on 1 February (their existing synthetic planting date), so most of the
chill season was outside the record. **Cause: window (insufficient temporal context).**
The requirement is reachable, forcing and state transitions work, and the model is not
the cause. A February record cannot show whether chilling was sufficient, so the
correct classification is `INSUFFICIENT_TEMPORAL_CONTEXT`, not an impossible requirement.

## 3. Concepts (Lang et al. 1987)

- **Paradormancy:** growth inhibited by signals from other organs (e.g. apical dominance).
- **Endodormancy:** inhibition inside the bud; released by chilling.
- **Ecodormancy:** growth prevented only by unfavourable environment (e.g. cold after release).
- **Chilling accumulation / requirement:** effective cold accumulated during endodormancy and
  the amount needed for release (cultivar-specific, model-specific units).
- **Dormancy release:** end of endodormancy; afterwards heat (forcing) accumulates.
- **Forcing requirement:** heat (GDD/GDH) from release to budburst or flowering.

The project represents endodormancy (`dormancy_released = False`), release, and forcing
through GDD stages. Para- and ecodormancy are not separate states and are not added,
because no project component needs them yet.

## 4. Strategies to start chilling

| Strategy | Description | Advantages | Limitations |
| --- | --- | --- | --- |
| Fixed date | Count from a protocol date (e.g. 1 Nov NH; 1 May SH in South Africa) | Simple, comparable within one protocol | Convention, not physiology; region- and hemisphere-specific; misses early chill or counts ineffective periods; the South African 1 May convention is criticised for early-flowering cultivars (Fresh Quarterly) |
| Local calendar window | Count within a season window (e.g. 1 Oct–1 Apr NH, 1 Apr–1 Nov SH in global analyses) | Covers the chill season broadly | Still conventional; the effective accumulation period deviates with local temperature |
| Dormancy establishment | Count from observed endodormancy onset (leaf fall, bud set) | Physiological | Needs onset observations or an induction model (absent in this project) |
| First effective chill | Count from the first period that the model rates as chilling | Temperature-driven, calendar-free | Equivalent to counting all hours for Chilling Hours; sensitive to isolated cold hours |
| Temperature persistence | Start after persistent cool conditions | Robust to isolated cold spells | Thresholds and durations require evidence per site and cultivar |
| Model-defined | Onset implicit in the model (Utah negative units, Dynamic Model two-step process) | Accounts for warm-period negation | Requires implementing the model and requirements in its units |

## 5. Environmental dependence

Chill availability depends on temperature regime, diurnal amplitude, altitude, distance
to the sea and interannual variability, not on latitude alone. For the Región de Murcia
(49 stations), interpolation of mean and safe winter chill (Dynamic Model) is best
explained by altitude (plus latitude for safe winter chill); coastal localities are
overestimated by all methods (Eur. J. Agron. 2024). Mediterranean and warm-winter areas
are where chill models diverge most (Luedeling & Brown 2011) and where future chill losses
are largest (Luedeling 2012). Continental climates may accumulate chill early in autumn
and stop accumulating when air falls below the lower threshold.

## 6. Hemispheres

The process is the same in both hemispheres: dormancy → chilling → release → forcing →
budburst, following local autumn → winter → spring. Only the calendar differs. The
framework therefore takes time only from `SimulationClock` and temperature from
`WeatherState`; the hemisphere is metadata derived from latitude and used to generate the
synthetic climate calendar and to label results. It is never a physiological input, and
the code does not shift anything by six months.

## 7. Chilling models

- **Chilling Hours** (Weinberger 1950): hours below 7.2 °C (the project uses the 0–7.2 °C variant).
- **Utah** (Richardson, Seeley & Walker 1974): weighted chill units with negative weights for warm hours.
- **Dynamic Model** (Fishman, Erez & Couvillon 1987): two-step process with a reversible
  precursor destroyed by high temperatures and an irreversible cooperative transition into
  chill portions. It is argued to be the most plausible structure and is recommended for
  warm climates (Luedeling 2012), and it is used in the Murcia studies.
- The models are not interchangeable: their results diverge strongly between climates
  (Luedeling & Brown 2011), and the project's evidence rows keep chill hours and chill
  portions separate (`crop_phenology.csv`).

## 8. Decision

**POLICY_UNCERTAINTY.** Several strategies are defensible, and the literature's start
dates are protocol conventions. No universal calendar date is scientifically justified.
The start policy stays explicit and configurable (`ChillingStartPolicy`):
- `DORMANCY_STATE` is the engineering default: count from the start of the record
  whenever the crop is endodormant;
- `FIXED_DATE` requires an explicit configured instant;
- `EFFECTIVE_CHILL_ONSET` records the first effective chill;
- `MODEL_DEFINED` and `ENVIRONMENTAL_WINDOW` are declared but not implemented.

Open questions:
1. Selecting a chilling model (Chilling Hours vs Dynamic Model) per species and region.
2. Dormancy induction (entry into endodormancy after harvest or leaf fall).
3. Cultivar requirements in consistent units (the literature rows are `NOT_ACTIVATED`).
4. Record starts for the project's plot campaigns: to avoid `INSUFFICIENT_TEMPORAL_CONTEXT`,
   a perennial record must start before local chill onset. This is a configuration choice,
   not a biological constant.

## References

- Lang, G.A., Early, J.D., Martin, G.C., Darnell, R.L. (1987). Endo-, para-, and ecodormancy: physiological terminology and classification for dormancy research. *HortScience* 22, 371–377.
- Weinberger, J.H. (1950). Chilling requirements of peach varieties. *Proc. Am. Soc. Hortic. Sci.* 56, 122–128.
- Richardson, E.A., Seeley, S.D., Walker, D.R. (1974). A model for estimating the completion of rest for 'Redhaven' and 'Elberta' peach trees. *HortScience* 9(4), 331–332.
- Fishman, S., Erez, A., Couvillon, G.A. (1987). The temperature dependence of dormancy breaking in plants: mathematical analysis of a two-step model involving a cooperative transition. *J. Theor. Biol.* 124, 473–483; and computer simulation of processes studied under controlled temperatures, *J. Theor. Biol.* 126, 309–321.
- Luedeling, E., Brown, P.H. (2011). A global analysis of the comparability of winter chill models for fruit and nut trees. *Int. J. Biometeorol.* 55, 411–421. https://pmc.ncbi.nlm.nih.gov/articles/PMC3077742/
- Luedeling, E. (2012). Climate change impacts on winter chill for temperate fruit and nut production: a review. *Scientia Horticulturae* 144, 218–229. https://www.sciencedirect.com/science/article/pii/S0304423812003305
- A comparison of interpolation methods to predict chill accumulation in a Mediterranean stone fruit production area (Región de Murcia, SE Spain). *European Journal of Agronomy* (2024). https://www.sciencedirect.com/science/article/pii/S1161030124002375
- Chill-accumulation conventions in the Southern Hemisphere: Fresh Quarterly, "Know your chill models" and "The fundamental flaws of chill models". https://www.freshquarterly.co.za/know-your-chill-models/
- Project evidence rows: `src/crop_phenology.csv` (SRC-011 Drogoudi et al. 2023; SRC-014 Guerrero et al. 2024; SRC-015 Ruiz, Campoy & Egea 2018; SRC-016 González Noguer et al. 2023; SRC-017 Díez-Palet et al. 2019).
