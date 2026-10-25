# Phase 6.5r, step 4: RQ4b widened, does "k of n variants" carry information?

Development partition; synthetic data; both twins uncalibrated, EnergyPlus is not the real greenhouse; exploratory, no quality claim. Script: `manual_phase6_5r_rq4b_wide.py`; report: `data/xai/rq4b_wide_report.json` (hash d7336263…).
The first experiment (8 cases, two interventions, two energy targets) had every variant agree in every case, so the "not confirmed" branch was never exercised. This one widens it.

## 1. Design

Tomato greenhouse with the climate controller. 7 interventions at the benchmark's probe levels (heat wave, cold wave, low and high radiation, wind, vent opening, shade screen), 2 windows (spring and late May), 4 seasons: **56 cases**, truth on EnergyPlus (lock-step).
5 targets: heating and cooling energy, indoor temperature, relative humidity, vapour deficit (each the sum of the effect over 48 h). Working twin: levels small (±10 %) and large (±30 %), 7 variants each (the nominal level has one variant and cannot be confirmed).
A pair is *material* when the truth's effect is at least 1 % of the baseline's magnitude over the horizon; a variant claiming a direction where the truth is below that is a *spurious* claim.
Reading rule, stated before the numbers: the evidence rule is informative only if some claims fail the quorum and a confirmed claim is right more often than an unconfirmed one; otherwise it only certifies robustness. Wilson intervals over pairs ignore clustering in (window, season) groups: read them as optimistic.

## 2. Results

| Level | Claims (material) | Direction correct among material (95 %) | Confirmed: correct / total (95 % of precision) | Unconfirmed: correct / total | Truth inside the variants' range | Ratio working/truth: p10, median, p90 |
|---|---|---|---|---|---|---|
| small | 173 (163) | 155 / 163 = 0.95 (0.91-0.98) | 154 / 167 = 0.92 (0.87-0.95) | 1 / 6 | 22 of 163 | 0.71, 1.25, 2.55 |
| large | 176 (166) | 155 / 166 = 0.93 (0.89-0.96) | 153 / 167 = 0.92 (0.86-0.95) | 2 / 9 | 41 of 166 | 0.73, 1.23, 2.64 |

By target (small level, claims correct among material): indoor temperature 36 / 36, cooling energy 27 / 27, heating energy 22 / 22, relative humidity 30 / 31 with 8 spurious claims, vapour deficit 40 / 47. At the large level the same ordering holds (vapour deficit 42 / 48, humidity 28 / 32 plus 8 spurious).
Of the claims where all seven variants agreed (165 at the small level), **13 are wrong** (4 in direction, 9 spurious): the errors are shared by every variant.

## 3. Reading

* **The quorum carries some information**: confirmed claims are right about 92 % of the time (0.87-0.95), the few unconfirmed ones about one in five (1 of 6 and 2 of 9: too few to estimate). The earlier "it only certifies robustness" is softened, not reversed.
* **But "confirmed" is not certainty:** about 8 % of confirmed claims are wrong, and unanimity does not prevent it, because the mismatch is structural (a different model) and every variant inherits it. The k of n of D15 measures fragility to parameters, not reliability against the structure.
* **Reliability depends on the kind of variable:** thermal and energy targets were always right in direction; the humidity-related targets (relative humidity, vapour deficit) carry almost all the errors and spurious claims.
* **Magnitude:** the ratio working/truth is centred near 1.2 but spreads from 0.7 to 2.6 (the first experiment's 1.9 was specific to two interventions); the variants' range contains the truth in 13 % (small) to 25 % (large) of the pairs: it is not an interval for the size.

## 4. Consequence in the semantic layer (decision D20)

`DomainPack.confirmable_variables` (tsxai) lets the host say which variables the twin may confirm. The twin's pack declares `temperature_c`, `greenhouse_heating_kw` and `greenhouse_cooling_kw`, from this **development** evidence only; for the others,
agreement of the variants is reported as such ("not confirmed by the twin: its direction was unreliable in development") at the model level. The list must be frozen in the preregistration before the test partition is touched, and re-checked there: it is tuned on development.
Together with the wording of 6.5r (direction only, size not confirmed), a confirmed fact now says what the evidence supports: the direction, for thermal and energy variables, with an empirical precision of about 0.9 in these synthetic cases.

## 5. Limits

One crop and one controller; synthetic data; two windows; 56 cases (within-group correlation not modelled); the 1 % materiality threshold and the 0.8 quorum are conventions; EnergyPlus is a reference model, not the real greenhouse; intervals are optimistic.
