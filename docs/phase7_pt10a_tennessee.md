# Phase 7 / second domain: PT-10a, effect queries on the Tennessee Eastman process

Status: DEVELOPMENT. Truth by re-simulation only, three noise seeds, one disturbance design, no data-based method, no calibration. The plant is a benchmark of the literature (Downs and Vogel), run through a third-party Python backend (`tep`, jkitchin/tennessee-eastman-profbraatz; the Illinois licence notice must travel with any redistribution). `tep` is not a dependency of this repository: its source directory is given by `TEP_SRC`. Code `src/process_twins/tennessee_eastman.py`, tests `tests/test_tennessee_eastman.py` (skipped without `TEP_SRC`), script `manual_phase7_pt10a_tennessee.py`, report `data/xai/effects_pt10a_tennessee.json`. The design and the reading rules are fixed in the script's docstring before the run.

## The technical check that preceded it (outside the repository)
Same seed gives an identical run and another seed a different one; a deep copy of the simulator is a valid snapshot (identical continuation, equal to the uninterrupted run); replaying the recorded manipulated variables in manual mode reproduces the closed loop exactly (an off-by-one in my first replay gave 8 percent error: the variable recorded after step k is the one applied in step k). One simulated hour takes 6.5 s.

## The host
One sample per second; sample `a` is the measurement of the state after step `a` (the package's own measurement is one step late, so the host refreshes it: with that, an intervention at index `s` first changes sample `s+1` and nothing before, checked on IDV1, IDV4 and IDV6). Season = seed of the process noise. Factors IDV1..IDV20 (on/off). The actuation trace is the twelve manipulated variables as applied; a replay overrides the named ones over the plant's own controller.

## PT-10a design and results
Window 1800 s from second 600; players idv1 (A/C feed ratio, from index 100), idv4 (reactor cooling water inlet temperature, from 300), idv5 (condenser cooling water inlet temperature, from 200), 1200 s each; exact Shapley over 8 coalitions; reactive policy against replaying the undisturbed run's manipulated variables (all twelve, or only the two cooling valves). No coalition shut the plant down; replaying the source's own trace reproduced the source run in all 6 checks.

| outcome | reactive (controller acts) | replayed, all twelve variables imposed |
|---|---|---|
| Mean reactor temperature, total (shares idv1 / idv4 / idv5) | +0.004 C (-0.005 / +0.013 / -0.003) | +9.8 C (-2.1 / +9.1 / +2.8) |
| Maximum reactor pressure, total | +17.3 to +19.8 kPa (idv1 +13.1..+16.2, idv4 -0.7..-0.5, idv5 +1.7..+7.4) | +9.8 to +11.3 kPa (idv1 +88..+89, idv4 -49..-48, idv5 -31..-29) |
| Mean reactor cooling valve | +2.3 percent (idv4 +2.5) | 0 (imposed) |
| Mean reactor level | +0.59 percent (idv5 +0.56) | +0.33 percent (idv4 -0.78, idv5 +0.89) |

* **The controller hides the disturbance.** Under the closed loop the temperature does not move (+0.004 C) because the cooling valve opens by 2.5 percent; with the manipulated variables held, the same disturbance heats the reactor by 9.1 C. An explanation that only looks at the closed-loop temperature would say "nothing happened".
* **Pressure: the net hides large opposite shares and the controller changes who matters.** With the variables held, idv1 (+88) and idv4/idv5 (-48, -30) nearly cancel (net about +10); under the closed loop idv1 shrinks to about +13..+16 (the controller absorbs roughly 85 percent of it) and idv5 changes sign (-30 held, +2..+7 reactive). The reactive pressure shares have a large interaction (0.42 to 0.86 of the sum of absolute shares) and a maximum aggregate: with three noise seeds the idv5 share is not stable, and I make no claim on it beyond the sign flip across policies.
* **Partial replay** (only the two cooling valves held) gives intermediate values (temperature +7.6 C, so about 2.2 C of the compensation comes from the other manipulated variables).
* The reactor temperature, the cooling valve and the level are very stable across the three seeds (shares within a few percent); the pressure maximum is the noisy outcome.

## What it does not say
Truth only; one disturbance design and window; three noise seeds; no comparison with a data-based method yet; the set-point as a player is not available (it needs an injection point in the controller); no claim about real plants. The tool question this answers is only whether the same effect queries run on a second domain unchanged: yes, with a host of about 120 lines and no change to `tsxai`.
