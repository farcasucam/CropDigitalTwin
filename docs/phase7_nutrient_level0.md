# Phase 7 / nutrients, level 0: the fertilisation event and the nutrient series

Status: DEVELOPMENT. No model equation changed. Script `manual_phase7_nutrient_level0.py`, report `data/xai/nutrient_level0.json`, tests `tests/test_nutrient_event.py`.

## What was missing
The twin has a reduced single-pool nutrient model (`domain/nutrient_balance.py`: one available pool capped at a reserve of 200 kg/ha, uptake proportional to the potential growth times a stage factor, the pool over the reserve multiplies the growth; ENGINEERING_APPROXIMATION, requires calibration). It was reachable only from the scenario runner (the first `fertilization` scenario event, its amount applied in every step it was active), not from the interactive simulation, the web bench or the explanation layer, and its state was not a result series.

## What level 0 adds
* **Runtime event `FERTILIZATION`** (`application/runtime_events.py`), offered by the web bench through the event contract: `amount_kg_ha` is a **total dose over the event's interval**, split evenly over its one-hour steps and **added** to the available pool. Events add up (several doses, split applications). It never replaces a plan (compare the `IRRIGATION` event, which replaces the outdoor plan: PT-6b). Range (0, 1000], a software input guard, not an agronomic limit. Efficiency 1 and no leaching are assumed.
* **Scenario runner**: a runtime fertilisation event contributes `amount * dt / duration` per active step, summed over events; a historical `fertilization` scenario event keeps its old meaning (its amount in every step it is active) and is added on top. The scenario hash and the runs without the event are unchanged.
* **Five result series** (`interactive_simulation.VARIABLES`, so they reach the web charts and the explanation layer): `nutrient_available_kg_ha` (pool), `nutrient_applied_kg_ha` (the dose OFFERED to the pool in the step; the pool is capped at the reserve, so not all of it is retained), `nutrient_extracted_kg_ha`, `nutrient_leached_kg_ha`, `nutrient_status` (pool over the reserve = the nutrient factor of the growth). `CropSimulationSnapshot` carries the step's `NutrientBalanceResult`.
* **Web bench** (`frontend/bench.js`): labels for the series, the unit of the event and a quick preset (a demonstration value of 20 kg/ha, not an agronomic recommendation). The runtime page builds its event list from the contract, so the new event type appears there without change.

## What the reduced model does with a dose (tomato, outdoor, DEV season 34, 336 h from hour 1500; a response of the model, not an agronomic result)
* Without fertilisation the pool falls from 132 to 77 kg/ha (status 0.66 to 0.38) in the window: the reduced model is nutrient-limited here, so a dose matters.
* Below the cap the response is linear: each kg/ha raises the end pool by 1 kg/ha and the end biomass by about 0.93 g/m2 (12 kg/ha: +11.2; 24: +22.4; 48: +44.9 g/m2). For comparison the heat wave of PT-6a costs about 23 g/m2. That slope is a property of the structure (status multiplies growth), not of tomato.
* Above the reserve nothing is gained: 100 and 900 kg/ha give the same pool at the end (164.8) and biomass within 0.8 g/m2; the offered series still counts the 900.
* Timing matters through the time left to benefit: the same 24 kg/ha gives +30.0 g/m2 at hour 20 and +4.4 g/m2 at hour 280, with the same end pool.

## What it does not do
No N/P/K split, no fertiliser type or efficiency, no dependence of the leaching on water, no nutrient dynamics beyond one pool, no quality variable, no calibration; the series are labelled uncalibrated. The explanation layer's benchmark design (`xai_benchmark_design.json`) and the declared temporal graph (`xai_declared_graph.json`, version 0.2) do not yet contain the fertilisation factor or the nutrient node: that is the next step (level 0b), together with a fertilisation player test. The scope question (which models, for which crops and situations) is in the project memory and the conversation: a general simplified model with explicit uncalibrated parameters, not a per-crop literature model.
