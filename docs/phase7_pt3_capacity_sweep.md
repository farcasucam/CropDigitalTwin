# Phase 7 / PT-3a: where the controller's masking of a perturbation breaks when the cooling capacity is reduced

Status: DEVELOPMENT. One seed (0) per crop, the four PT-2 perturbations applied together as one player, only the cooling capacity varies (a scale on the illustrative 0.45 kW per m2 of floor). Equipment illustrative, crop model uncalibrated, no inferential test.
Script: `manual_phase7_pt3_capacity_sweep.py` (report `data/xai/effects_pt3_capacity_sweep.json`). Reading rules R1, R6, R7, R8 were written in the script's docstring before the run. Grid declared in advance: 1, 0.5, 0.3, 0.2, 0.15, 0.1, 0.07, 0.05, 0.03.

## Results

| crop | masked at scales | first scale not masked (R6) | peak contrast under the reactive controller (scale 0.5 / 0.3 / 0.03) | replayed contrast |
|---|---|---|---|---|
| tomato | 1.0 | 0.5 (partly masked, ratio 0.06) | 0.58 / 2.38 / 4.40 K | 9.20 K |
| pepper | 1.0 | 0.5 (not masked, ratio 0.50) | 4.41 / 7.96 / 7.97 K | 8.76 K down to 7.99 K |
| lettuce | 1.0 and 0.5 | 0.3 (partly masked, ratio 0.38) | 0.0 / 2.47 / 4.45 K | 6.44 K |

* The true break lies between the last masked scale and the first unmasked one of the grid (tomato and pepper between 1.0 and 0.5, lettuce between 0.5 and 0.3); the grid is coarse there and was not refined.
* Mechanism (R7): the hours with the cooling power at 0.99 of the capacity grow as the capacity shrinks (tomato 2 h at 0.5, 17 h at 0.05). In pepper the unperturbed reference itself starts to saturate from scale 0.3 (1 to 21 h), so the replayed contrast shrinks (8.76 to 7.99 K) and the ratio approaches 1.
* Cost (R8): the cooling energy that the controller spends because of the perturbation stops growing with it: tomato 2043 kWh at scale 1, 1662 at 0.3, 209 at 0.03; the energy is capped by the equipment and the temperature starts to show the perturbation.
* Replay reproduces its source run at every scale (checked in the script's engine query).

## Reading, and what it does not say

* The masking found in PT-2 is a property of capacity headroom: with the illustrative capacity it holds for the three crops, and it breaks with roughly half the capacity (a third in lettuce). It is not a statement about real greenhouses, whose capacity is unknown to this twin.
* Consequence for the methods to compare (7.5): where the controller has headroom, the temperature carries no trace of the perturbation and a method that reads only the temperature cannot see it; the trace is in the energy and the commands. Where capacity saturates, the temperature shows part of the effect. This is the regime map to use when comparing data-based methods, with the caveat that both regimes come from one generator.
* Players were applied together: this sweep says nothing about how the division among them (interactions, grouping) behaves under saturation; that is PT-3b.
