# Phase 7 / PT-3b: three overlapping perturbations under reduced cooling capacity

Status: DEVELOPMENT. One seed (0) per crop, cooling-capacity scales 1, 0.5, 0.3, 0.15, three perturbations that overlap in hours 48-96 (heat wave +8 degC, high radiation x1.3, cold wave -6 degC; the cold wave's offset adds to the heat wave's), both policies, 8 coalitions each. Illustrative equipment, uncalibrated crop model, no inference.
Script: `manual_phase7_pt3b_overlap_capacity.py` (report `data/xai/effects_pt3b_overlap_capacity.json`). Reading rules R2, R3, R4 fixed in its docstring before the run (relative to the contrast, minimums 1 kWh, 1 h, 0.05 K).

## Results against the rules

* **R2 interaction above 10 percent of the contrast: every material cell (all three crops, all scales).** Values reach 0.58 (tomato), 1.2 to 38 (pepper), 3 to 6 (lettuce).
* **R4 grouping above 10 percent:** tomato 6 of 6 merges at every scale (max 0.20); pepper 6 to 9 of 9 or 12 depending on scale (max 0.13, but 5.2 at scale 0.5); lettuce 3 of 6 at scales 1 and 0.5 and 0 of 6 at 0.3 and 0.15.
* **R3 interaction-free score:** the top player agrees in 41 of 42 material cells, but the largest error is 0.7 to 14 times the contrast, against at most 0.07 in PT-2.
* Efficiency residual below 1e-6 everywhere. Tomato is the same at all four scales: its material cells are replayed ones only (the reactive contrast stays below the minimum even at 0.15, this net +2 degC does not saturate the equipment) and the replayed reference does not depend on the capacity there.

## How to read it, with a flaw of the rules

* **The relative-to-contrast rules are ill-conditioned in this design.** The cold wave opposes the heat wave, so the contrast is a net of cancelling shares: sum of |shares| over |contrast| is 1.9 to 7.2 in the material cells (post-hoc inspection of the stored shares, e.g. pepper at scale 1, cooling energy: cold wave -1447, heat wave +2706, radiation +417 kWh, contrast 1676). Values such as 38 come from a contrast of 0.11 K against shares of about 1 K, not from a larger interaction. The rule was fixed before the run and is reported as is; a normaliser that does not cancel (the sum of absolute shares) is the candidate for the confirmatory protocol, a change to be declared, not applied retroactively to this result.
* **What does hold:** with overlapping, opposing perturbations the interaction-free score and the grouping are not harmless: the top place survives (41 of 42) but the magnitudes do not, and merges change the shares in most cells. A report must therefore state the valuation, the grouping and the order of the players, and give the interaction gap beside the shares.
* **Saturation did not change the picture much** for the division in these three crops: lettuce is the one where the grouping effect disappears at scales 0.3 and 0.15 (cooling energy becomes capped), the others do not move systematically. One seed per crop: nothing here estimates how often.
* The opposing-sign design is my construction (it exercises cancellation); a design whose players all push the same way would be less ill-conditioned and is the other half the protocol needs.
