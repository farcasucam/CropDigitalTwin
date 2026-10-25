"""The two twins of decision D15, for the explainer's counterfactuals.

* **Truth twin:** the benchmark's own parameters with the EnergyPlus backend (lock-step with the controller): it generates the data and the true effects. The explainer never consults it.
* **Working twin:** what the explainer owns: the simplified (lumped) model of the same greenhouse, with its placeholder parameters perturbed. Its mismatch with the truth is structural (a different model) and
  parametric (the perturbation). A set of variants gives calibrated evidence ("confirmed in k of n variants").

Levels of mismatch (``src/xai_double_twin.json``, decision D19): ``0`` is the nominal parameters of the simplified model (a ceiling for reference, never a main result: the structure alone already separates the
two twins), ``small`` and ``large`` are relative widths. No sourced uncertainty range exists for these parameters (all are PROVISIONAL_DEFAULT), so the widths are declared design choices, not scientific uncertainty.
Variants are drawn by Latin hypercube from a seeded generator: deterministic and spread evenly over each parameter's range.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from agri_twin.infrastructure.greenhouse_idf import EnvelopeSpec, ThermalSpec

DESIGN_FILE = Path(__file__).resolve().parents[2] / "xai_double_twin.json"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_design(path: Path | str | None = None) -> dict[str, Any]:
    return json.loads(Path(path or DESIGN_FILE).read_text(encoding="utf-8"))


def nominal_values(parameters: Sequence[str]) -> dict[str, float]:
    """The placeholder values of the simplified model (PROVISIONAL_DEFAULT) for the named parameters."""
    envelope, thermal = EnvelopeSpec(), ThermalSpec()
    return {name: float(getattr(envelope if hasattr(envelope, name) else thermal, name).value) for name in parameters}


def variants(level: str, design: Mapping[str, Any] | None = None) -> list[dict[str, float]]:
    """The parameter variants of one mismatch level. Level ``0`` is one variant with no override (the nominal model). Otherwise ``variants_per_level`` Latin-hypercube points in
    ``nominal * (1 +/- width)``, fractions capped at one, reproducible from the design's seed and the level."""
    design = design or load_design()
    widths = design["levels"]
    if level not in widths:
        raise KeyError(f"unknown mismatch level {level!r}; known: {sorted(widths)}")
    width = float(widths[level])
    if width == 0.0:
        return [{}]
    names, n = list(design["parameters"]), int(design["variants_per_level"])
    nominal, capped = nominal_values(names), set(design["fractions_capped_at_one"])
    rng = random.Random(int(_digest({"seed": design["seed"], "level": level})[:12], 16))
    columns = []
    for _ in names:  # one random permutation of the n strata per parameter, one point inside each stratum
        strata = list(range(n))
        rng.shuffle(strata)
        columns.append([(s + rng.random()) / n for s in strata])
    out = []
    for i in range(n):
        point = {}
        for j, name in enumerate(names):
            value = nominal[name] * (1.0 + width * (2.0 * columns[j][i] - 1.0))
            point[name] = round(min(1.0, value) if name in capped else value, 6)
        out.append(point)
    return out


def working_scenario(scenario: Any, parameters: Mapping[str, float]) -> Any:
    """The same scenario (a ``tsxai`` ``ScenarioDescriptor``, handled by duck typing: only the adapter imports the framework) for a working-twin variant: the simplified greenhouse with the variant's parameters (none: the nominal simplified model)."""
    greenhouse = {**dict(scenario.options.get("greenhouse", {})), "backend": "SIMPLIFIED"}
    if parameters:
        greenhouse["parameters"] = dict(parameters)
    return replace(scenario, options={**dict(scenario.options), "greenhouse": greenhouse})


def truth_scenario(scenario: Any) -> Any:
    """The same scenario on the truth twin: EnergyPlus with the nominal parameters. The crop's feedback on the greenhouse air exists only in the simplified model, so a scenario with it has no truth twin."""
    if scenario.labels.get("feedback") == "on":
        raise ValueError("the crop feedback on the greenhouse air is modelled by the simplified greenhouse only: this scenario has no EnergyPlus truth twin")
    return replace(scenario, options={**dict(scenario.options), "greenhouse": {"backend": "ENERGYPLUS"}})
