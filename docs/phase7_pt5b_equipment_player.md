# Phase 7 / PT-5b: an installation fault as a player

Status: DEVELOPMENT. Tomato, greenhouse, controller on, window 336 h from hour 960, four held-out DEV seasons (34, 35, 37, 38), one fault level. Script `manual_phase7_pt5b_equipment_player.py`, report `data/xai/effects_pt5b_equipment_player.json`; reading rules fixed in the script's docstring before the run. Code change: `TwinSimulator` accepts the intervention `COOLING_CAPACITY` (a multiplier of the rated cooling capacity for the whole run, start 0 and the window's duration, controller on; anything else raises), with a test in `tests/test_xai_effects.py`; ordinary runs are unchanged.

## Design
Three players: a heat wave (+8 degC, window hours 48-96), a high-radiation spell (x1.3, hours 72-120) and a cooling-capacity degradation (x0.3 for the whole run). Truth: re-simulation, reactive policy, exact Shapley over 8 coalitions, reference = nominal installation without perturbation. Data method as in PT-5a, trained at the NOMINAL capacity (it never saw a reduced installation), occluding only the players that change an observed outdoor channel: the capacity changes no observed channel, so there is nothing for the method to occlude.

## Results (four seasons; ranges)
| outcome | material cells | true share of the capacity player (of the sum of absolute shares) | fraction of the true total that the data method accounts for |
|---|---|---|---|
| peak temperature | 4 of 4 (truth +2.0 to +2.9 K) | 0.40 to 0.50 | 0.13 to 0.32 (oracle baseline), 0.22 to 0.30 (climatology) |
| hours above stage maximum | 3 of 4 (1 to 5 h) | 0.33 to 0.40 | 0 (it reports none) |
| cooling energy | 4 of 4 (1444 to 1848 kWh) | 0.06 to 0.08 (negative: a smaller plant spends less) | 1.0 to 1.13 |

## Reading
* **For energy the missing player barely matters:** the heat wave explains the energy (a degraded plant spends 100 to 136 kWh less, 6 to 8 percent), and the data method accounts for it (overstating it by up to 13 percent). The PT-5a conclusion for energy stands.
* **For the temperature the data method sees 13 to 32 percent of the effect and for the hours above the maximum none.** The installation's state is not in the observed outdoor channels, so the effect on the air temperature, which exists only if the plant is degraded AND the weather is hot, is not attributable by occlusion of the observed inputs. It reports at most the small spurious effect found in PT-5a. Here the re-simulation says something a data-only method cannot: the peak of +2 to +3 K is due to the pair.
* **The pair is jointly necessary, and Shapley splits that equally.** The heat wave alone is masked (PT-2) and the degraded plant alone does nothing without the heat; only together do they raise the peak. The two get the same share (for example 1.41 and 1.41 K in season 35). That equality reflects the valuation's symmetry, not equal causal contributions. A report must say "the heat wave exceeded what the degraded plant could remove" (a joint necessity, with the interaction stated), not "50 percent each".

## What it does not say
One fault level, one crop and generator, a simple surrogate trained without the fault; a method that was given the installation's state, or trained on episodes in which it varied and was recorded, could attribute it. It shows that a method which only observes the weather cannot, not that no data-based method could. Four seasons per regime.
