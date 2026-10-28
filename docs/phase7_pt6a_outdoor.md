# Phase 7 / PT-6a: a short outdoor test

Status: DEVELOPMENT. Tomato, outdoor (no climate controller), window 336 h from hour 1500, four held-out DEV seasons (34, 35, 37, 38), three weather players. Script `manual_phase7_pt6a_outdoor.py`, report `data/xai/effects_pt6a_outdoor.json`; reading rules fixed in the script's docstring before the run.

## Design
Players: heat wave (+8 degC, hours 48-96), low-radiation spell (x0.6, 100-148), cold wave (-6 degC, 200-248). Outcomes: total and fruit biomass at the end of the window. Truth: re-simulation, exact Shapley over 8 coalitions. Data method: the PT-5a surrogate on the outdoor forcing plus the window-start stocks and the hour index, predicting the hourly biomass increment; occlusion with the segments given.

Exploration before the design (one season): irrigation x2 and rain x4 change the end biomass by 0.2 and 0.1 g/m2; the root zone stays at 150 mm, so water is not limiting in this window and neither is a player here. `DRYNESS` takes no intensity. The nutrient model is not exposed to the XAI layer (no fertilisation player yet).

## Results (four seasons; ranges)
* **Truth.** The total effect of the three perturbations on the end biomass is about -29.5 g/m2 in every season. The heat wave carries 22.8 to 24.0 g/m2 (about three quarters), the radiation spell 5.2 to 6.1, the cold wave 0.5 to 0.9. The interaction gap is 0.0 to 0.2 percent of the sum of absolute shares: outdoors the effects are additive, and leave-one-out, Shapley and the interaction-free score coincide in practice. No masking (nothing regulates), and no distinction between reactive and replayed actuation.
* **Data method.** Top player right in 4 of 4 cells; sign right in 8 of 8 players with a share of at least 5 percent; normalised error of the shares 0.20 to 0.36; **explained fraction 0.39 to 0.65**: it ranks and signs correctly but accounts for only about half of the magnitude. No false effects (all cells material). Surrogate quality: end biomass error 0.6 to 16 percent of the window's growth, hourly increment RMSE 0.27 to 0.42 of its standard deviation.
* The fruit biomass gives the same shares as the total (it is a fixed fraction of it here): it is not independent information.

## Reading
* Outdoors the explanation is simpler (additive, no controller), and the question "which weather episode cost how much biomass" can be answered by the twin with a split that does not depend on the valuation. The data method gets the order and the sign and loses about half of the size.
* A plausible reason, NOT tested: a heat wave changes the crop's state (phenology and leaf area) and that effect persists after the window of the perturbation; a surrogate with three lags and constant window-start stocks cannot carry that memory through occlusion. A model with the crop's state as input, or a longer memory, would show whether the loss is structural for this surrogate or for the method.
* The players that mattered in the greenhouse (equipment, controller policy) do not exist outdoors; the ones that would matter outdoors (irrigation in a dry spell, fertilisation, sowing date) either do nothing in this weather or are not yet available to the framework. That is the real limit of this test, not the heat wave result.

## What it does not say
One crop, one generator, one window, segments given, one simple surrogate, three weather players. A dry-spell scenario (to make irrigation matter), other crops and a fertilisation player are open.
