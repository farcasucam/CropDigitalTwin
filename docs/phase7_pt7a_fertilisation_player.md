# Phase 7 / nutrients, level 0b: the declared graph 0.3 and fertilisation as a player (PT-7a)

Status: DEVELOPMENT. The nutrient model is the reduced single-pool one, UNCALIBRATED: everything below is a property of that structure, not an agronomic finding. Scripts `manual_phase7_pt4a_graph_check.py` (graph check) and `manual_phase7_pt7a_fertilisation_player.py`; reports `data/xai/effects_pt4a_graph_check_v0_3_*.json` and `data/xai/effects_pt7a_fertilisation_player.json`; reading rules fixed in the script's docstring before the run (a surrogate-quality diagnostic was added after the first run; it does not change the rules).

## Declared graph 0.3
Written BEFORE any check from `nutrient_balance.py` and the update order of `step_at` (`src/xai_declared_graph.json`, history field): the entry point of `FERTILIZATION` (`nutrient_applied_kg_ha`), the nodes pool, uptake, leaching and status, the edge status to `growth_factor`, and an assumed edge status to `accumulated_stress` (marked `?`). The leaching is declared as a function of the previous pool, the dose and the uptake, which avoids a same-step cycle with the pool. The benchmark design `xai_benchmark_design.json` is NOT changed: the factor is available to effect queries but not part of the frozen benchmark `gctsb-1`; a new benchmark version would add it.

Check (the PT-4a script, now with a `FERTILIZATION` probe of 20 kg/ha in total over 72 h; the report name carries the graph version from 0.3 on): **19 of 19 consistent, no missing edge, on tomato 34, pepper 1 and lettuce 2** (dev seasons; the earlier checks of 0.1 and 0.2 used tomato 0, a test-partition season, disclosed in PT-5a). The dose changes 11 to 14 series; 2 to 6 predicted descendants did not move (thresholds not crossed). All series are covered by the graph. Low power as before: descendant sets are large.

## PT-7a: amount against timing, with a heat wave
Tomato, outdoor (no controller), 336 h from hour 1500, DEV seasons 34, 35, 37, 38. Players: heat wave (+6 degC, hours 48-144), `fert_early` (24 kg/ha in total over 24 h from hour 20), `fert_late` (the same 24 kg/ha from hour 280). Reference: unfertilised and unperturbed. Truth: exact Shapley over 8 coalitions.

### Truth
* Total effect on the end biomass: -19.1 to -21.4 g/m2. The net hides a compensation: the heat wave costs 48.4 to 50.2 g/m2, the early dose gives +24.7 to +25.4 and the late dose +4.0 to +4.4.
* **Timing:** the doses are equal, and the early one is worth 5.8 to 6.2 times the late one for the biomass (7.0 times for the mean nutrient status): in this model a dose is worth the time left to benefit from it, not only its amount.
* Interaction between the players: 11.6 to 11.9 percent of the sum of absolute shares (the heat wave costs less where the pool is higher).

### Data method told the applied dose (PT-6b style, 24 training episodes)
* **Mean nutrient status:** recovered (explained fraction 0.94 to 1.01, top player right in 4 of 4, normalised error 0.01 to 0.06, early above late in 4 of 4). It is a nearly mechanical outcome of the dose and the uptake; the status RMSE of the surrogate is 0.006 to 0.014.
* **End biomass: not recovered.** All signs of the three players are right (12 of 12) and it ranks the early dose above the late one (4 of 4), but the total effect has the WRONG sign (explained fraction -2.4 to -0.14: it reports +6 to +50 g/m2 against a true -20), the top player agrees in 1 of 4 cells with the oracle baseline and 0 of 4 with climatology, and the normalised error is 0.22 to 0.62. The surrogate is weak for this outcome: end-biomass error 14 to 56 percent of the window's growth, hourly-increment RMSE 0.43 to 0.61 of its standard deviation (0.27 to 0.42 in PT-6a with fewer inputs). A negative result for this surrogate with 24 episodes and eight observed channels, not for data-based methods.

## Reading
* For the explanation layer, a dose is an ordinary player: the engine accepted it without any change and the compensation (heat wave against doses) and the timing are statements it can make, which the net effect hides.
* The twin's value here is the same as before: the truth of the compensation and of the timing; a data method with more episodes or a state-aware design could do better, which is a question for the benchmark, not a claim.
* Not shown: leaching, fertiliser type, N/P/K, quality, other crops, a calibrated response. The linear slope below the reserve (about 0.93 g/m2 per kg/ha) comes from the structure "status multiplies growth".
