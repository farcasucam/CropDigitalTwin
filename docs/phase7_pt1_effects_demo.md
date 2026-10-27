# Phase 7 / PT-1: one greenhouse episode explained by re-simulation (reactive policy and replayed actuation)

Status: DEVELOPMENT. One episode, synthetic, the twin's crop model is uncalibrated. What is checked is arithmetic and replay plumbing; nothing here validates the twin against a real greenhouse, estimates a rate, or supports a confirmatory claim.
Script: `manual_phase7_pt1_effects_demo.py` (writes `data/xai/effects_pt1_report.json`, hash 70c29545…; about 46 s on this machine, a measurement and not part of the report). Framework: `tsxai.effects` (branch `effects-resimulation`, standard library only). Tests: `tests/test_xai_effects.py` here, `tests/test_effects.py` in `tsxai`.

## 1. What was built

* **Contract (`tsxai.effects.query`):** `Outcome` (a scalar of a trajectory: variable, aggregate, window, unit), `Player` (a named perturbation group), `Policy` (`reactive` or `replayed`, with the coalition whose commands are imposed), `EffectQuery` (scenario, outcomes, players, base interventions, policy, admissibility). The definitions of total effect, leave-one-out effect and Shapley share, and the rule that "exact" always carries a qualifier, are in the module docstring.
* **Engine (`tsxai.effects.engine`):** runs each coalition once (cache keyed by scenario, interventions and replayed trace), computes every outcome on the same runs, reports the contrast, the leave-one-out effects, their gap to the contrast, the exact Shapley division over all `2^m` coalitions, the efficiency and additivity residuals, and for a replayed policy whether replaying the source's own commands reproduces the source run. A coalition that is inviable or inadmissible is recorded and never imputed; a division that needs it is reported undefined.
* **Twin side:** `InteractiveSimulationService(controller_factory=...)` (optional, default unchanged; not applied to the EnergyPlus prefix replay of a resumed run), `agri_twin/interfaces/xai_effects.py` (`RecordingController`, `ReplayController`, `trace_of`) and `TwinSimulator.run_traced`. What is replayed is the controller's command trajectory before any manual override (shade, vents, extractors, cooling, heating, irrigation, irrigation target); manual events still override, the equipment translates fractions with its own capacities, and the physical model's protections stay in force. The controller is stateless, so no hidden state is replayed.
* **Verified before use:** a recorded run has the same run hash and series as the ordinary run; replaying a run's own commands reproduces its series and hash exactly; under replay the recorded trace equals the replay.

## 2. The episode

Tomato, greenhouse, climate controller on (illustrative equipment), season 0, a 14-day window starting at hour 960 (March). Four exogenous perturbations as players, at the levels of the benchmark's probes (conventions, not agronomic values): heat wave +8 degC (hours 48-96), cold wave -6 degC (200-248), high radiation x1.3 (72-120, overlapping the heat wave on purpose) and wind x3 (150-186). Reference: no perturbation. Valuation `v(S)`: the outcome with exactly the players of `S` ON. Outcomes: heating and cooling energy (thermal kWh), hours with indoor temperature above 28 degC and with VPD above 1.4 kPa (both the crop catalogue's own stage thresholds, read through `semantic_pack` with their source), peak indoor temperature.

## 3. What came out (this episode only)

| Outcome | Reference | Contrast, reactive | Contrast, replayed | Reading |
|---|---|---|---|---|
| Cooling energy (kWh) | 0.00 | +2043.15 | 0 by construction | all of it is the controller's reaction |
| Heating energy (kWh) | 49.55 | +322.85 | 0 by construction | same |
| Peak indoor temperature (degC) | 26.00 | -0.0000015 | +9.20 | the controller holds the air at 26.0 degC, so the reactive contrast hides the heat |
| Hours above 28 degC | 0 | 0 | +26 | idem |
| Hours VPD above 1.4 kPa | 63 | +32 | +35 | small difference between policies here |

* **The controller masks the perturbation on the physical outcome and pays for it in energy.** Under the reactive policy the air temperature does not move (contrast of about a microkelvin) while the cooling energy rises by 2043 kWh; with the reference's commands imposed, the same perturbations raise the peak by 9.2 K and add 26 hours above 28 degC. The two contrasts answer different questions and are reported side by side; their difference is not called a direct or an indirect effect.
* **Interactions are present in places and small in others.** Cooling energy: removing the heat wave removes all 2043 kWh, removing the high-radiation spell removes 254 kWh, and the sum of removals exceeds the contrast by 254 kWh (12 %); the Shapley shares are 1916 and 127 kWh. Peak temperature under replay: gap of 0.52 K of 9.20 (6 %). Heating: 3 kWh of 323. The Shapley shares add up to the contrast to 2e-13.
* **Shapley depends on its definition.** The 127 kWh of the radiation spell is half of an interaction that exists only when the heat wave is present; a different reference, valuation or grouping would divide it differently. This is why the report states the valuation, and why PT-2 must measure that sensitivity.
* **Cost:** about 1.4 s per run for this window, 16 coalitions per policy, 22 s reactive and 46 s with both policies. The earlier "11-15 s per scenario" belonged to the benchmark's generation, not to a run of this size. For up to 8 players (256 runs, minutes) no optimisation is needed to demonstrate the method; whether it is needed at the planned scale is for the optimisation phase to decide with measurements.

## 4. Checks (all pass)

Efficiency of the division (max residual 2e-13), replay of the reference's own commands reproduces the reference run, the reference is the same run under both policies, all 32 coalitions completed, a second build gives the same report hash. The 17 tests of `tsxai.effects`, the 8 of `tests/test_xai_effects.py`, and the 161 tests of the climate-control, interactive-simulation, adapter, double-twin, semantics-adapter and EnergyPlus lock-step suites pass.

## 5. Limits and open points

* **One episode, one season, one crop:** no rate, no interval, no generality. It answers whether the question is worth asking at scale, and it is: interactions and the policy difference are not negligible here.
* **An outcome that is a function of the commands cannot change when the commands are replayed** (energy): its replayed contrast is zero by construction, not a finding. Meaningful replayed outcomes are the physical ones.
* **Replay holds the command fractions, not the physical result:** an actuator that saturates under the reference saturates under replay too; the report does not flag it.
* **What is not yet done:** admissibility rules beyond "all", sensitivity of the shares to reference and grouping (PT-2/E3), approximate Shapley for more than 8 players, EnergyPlus replay (its checkpoint replays the prefix), the declared causal graph, data-based methods, narrative.
* The twin's levels, the equipment and the controller's set-points are design conventions (D19, `xai_benchmark_design.json`).
