# Phase 7 / PT-4a: the twin's declared temporal graph, tested by intervention

Status: DEVELOPMENT. A hypothesis about the twin, not about real greenhouses. Files: `src/xai_declared_graph.json` (provisional declaration, version 0.2, history inside), `manual_phase7_pt4a_graph_check.py`, reports `data/xai/effects_pt4a_graph_check_<crop><season>.json` and the preserved first result `effects_pt4a_graph_check_v0_1_tomato0.json`.

## What was done
The graph (child: parents, lag 0 within a step, `@1` previous step, `?` assumed edge) was written from the update order of `CropDigitalTwinOrchestrator.step_at` and from the controller's contract BEFORE any check. The check re-simulates one intervention per factor at the benchmark's probe level (from window hour 48, 72 h) under the reactive policy and, for the weather factors, under replayed actuation (the six command variables lose their incoming edges), and compares the variables whose series changed with the descendants of the intervention's entry points. A changed variable that is not a descendant is a MISSING EDGE (the graph is wrong); a predicted descendant that did not move is not a refutation (a threshold not crossed, a null effect). The reading rule (consistent = no missing edge) was fixed in the script before the run.

## Results
* **Version 0.1, tomato season 0: 13 of 17 (intervention, policy) pairs consistent.** The four failures are one omission: heat and cold waves also change `outdoor_relative_humidity_pct` (the twin recomputes the outdoor humidity from the shifted temperature). A real falsification, found by the check, not by reading the code.
* **Version 0.2** adds that edge (change recorded in the file's history). **17 of 17 on tomato season 0 (the episode it was corrected on, so not a test), and 17 of 17 on pepper season 1 and lettuce season 2** (episodes not used to correct it).
* Predicted descendants that did not move are many: WIND changes only its own series (on this greenhouse outdoor wind reaches no other variable), RAIN and CO2 the same, IRRIGATION two. The graph over-declares what the code allows; whether those edges are structurally null, below a threshold or inactive in the greenhouse mode cannot be told from one probe level.

## What it does not say
* **Low power.** Descendant sets cover most of the 42 series (36 of 42 for the weather factors), so a missing edge can only show in the few variables outside them. A pass says there is no omission among those, not that the graph is right.
* Lags and edge directions inside the descendant set are not tested; no individual edge is confirmed by this check; one probe level per factor; one synthetic generator; the controller-feedback edges (greenhouse-crop feedback is off here) are not exercised.
* Use: the declared graph is a documented structural prior for the data-based methods of 7.5 (which need to know what may cause what), with the check as a guard that it is not contradicted by the twin; never as discovered structure.
