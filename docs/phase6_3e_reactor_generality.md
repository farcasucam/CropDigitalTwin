# Phase 6.3e: does the latent-threshold mechanism generalise? Counterfactual gate on the PLC reactor

Synthetic teaching model (`tsxai.examples.PlcReactor`, two units, 6 seasons each = 12 independent groups); exploratory, not the preregistered evaluation; no quality claim.
Script: `manual_phase6_3e_reactor_generality.py`; report: `data/xai/reactor_gate_report.json` (hash 7fd19577…).

## 1. Question and reading rule (stated before the numbers)

6.3c explained the greenhouse failure by lack of prior excitation: a forecaster cannot learn the response to a threshold it never saw crossed. The reactor has the same kind of mechanism, a latched high-temperature interlock
(a regime switch). Pairs are stratified by what the forecaster SAW: **tripped-seen** (the interlock was tripped at some sample of the context window) or **never-tripped**. Failing only in never-tripped supports the excitation reading;
failing in both says excitation does not explain it. A second, descriptive stratum uses the truth (did the intervention change the interlock state within the compared horizon): it labels cases, never feeds a forecaster.

## 2. Design

1008 cases: 2 units x 6 seasons x 7 interventions (SETPOINT 340/360/375 K, FEED_CONC +1/+2 mol/L, COOLANT_TEMP +15/+30 K) x 6 start times x {not excited, excited}. An excited case has a trip burst in the plant's past, shared by both paired runs
(new option `scenario.options["history"]` of the reactor; context 240 min, burst ends before the cut-off, never tripped at the cut-off). Horizon 120 min, targets: temperature, concentration, cooling duty. Plan variables: the set-point and the forcings the intervention sets.
Backends: persistence (seasonal naive p1), lagged ridge with the 6.3d safety net, lagged ridge without it.

## 3. Results

| Backend | Pairs | Sign agreement | Spearman of peaks | Net acted |
|---|---|---|---|---|
| persistence | 2896 | 0.000 (predicts no effect by construction) | undefined | - |
| lagged ridge (net) | 2896 | 0.562 | 0.138 | 22 336 of 486 528 steps (4.6 %) |
| lagged ridge (no net) | 2896 | 0.565 | 0.138 | - |

Ridge by what it saw: tripped-seen 0.569 (95 % interval 0.538-0.599, 12 groups) vs never-tripped 0.556 (0.493-0.618): **no difference**. By truth: interventions that change the interlock 0.613 (357 pairs), those that do not 0.555 (2539 pairs).
Nothing approaches the preregistered 0.8 sign agreement; the net changes no conclusion.

## 4. Reading

* The **excitation explanation of 6.3c does not generalise**: the ridge fails equally with and without having seen the interlock trip, and also where the interlock plays no role. In the reactor the failure is generic to a linear lagged model against a closed-loop
  plant (the PI loop compensates the decision, so the observed effect is not linear in the plan), not specific to the threshold. 6.3c's mechanism stays a hypothesis valid for the greenhouse thermostat, not a general law.
* The persistence "0.000" is not a measure of skill: it only says it never reacts. The safety net acts more here (4.6 %) than in the greenhouse (1.4 %): the closed loop makes the recursion diverge more often.
* TimesFM was not run on the reactor (the service is not needed for a development reading); the conclusion concerns the two baselines. Consequence for the paper (D14): the negative finding C2 is reported with this mechanism-level nuance.

Limits: teaching model with illustrative constants; two units; 12 groups; one horizon and context length; the 5x net acts in a non-negligible share of steps.
