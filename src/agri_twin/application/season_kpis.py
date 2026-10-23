"""Season results of a simulated run: yield, water, energy and risk (vector A) and the cost of the resources (view C).

Pure post-processing of a trajectory with the user's ``SiteResources``: it never changes a simulation or a hash. Nothing is assumed: a figure that needs a value the user has not defined (an
efficiency, a price, the dry-matter share of the product, the area) is ``None`` and the report lists what is missing. The fruit has no price here (a market imponderable per season):
the economic view is the **cost of energy and water**, in total, per m2 and per kg of product.

The run simulates ONE unit (a greenhouse module of the chosen layout, or one square metre of open field). Quantities are per m2 and, with an area, totals for that area. For a plot larger than the
simulated unit the report also gives the linear scaling to the plot of the farm configuration, flagged as an assumption (it supposes the plot is made of identical units).
The results come from an uncalibrated model: they rank strategies and show directions, they are not absolute grams, litres, kilowatt-hours or euros of a real farm.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from agri_twin.application.climate_control import stage_setpoints
from agri_twin.application.energy_cost import energy_cost
from agri_twin.application.site_resources import SiteResources
from agri_twin.domain.climate_control import EquipmentSpec

STATUS = "SIMULATED_UNCALIBRATED_RANKING_NOT_ABSOLUTE"


def _sum(values: Sequence[float | None]) -> float | None:
    total = 0.0
    for value in values:
        if value is None:
            return None
        total += float(value)
    return total


def _series(series: Mapping[str, Sequence[Any]], name: str) -> list[float] | None:
    values = series.get(name)
    if values is None:
        return None
    return [0.0 if value is None else float(value) for value in values]


def _merge_equipment(base: EquipmentSpec, override: Mapping[str, Any] | None) -> EquipmentSpec:
    if not override:
        return base
    merged = {name: getattr(base, name) for name in EquipmentSpec.FIELDS}
    merged.update({name: value for name, value in override.items() if value is not None})
    return EquipmentSpec.from_mapping(merged)


def season_kpis(resources: SiteResources, *, crop: str, times: Sequence[str], series: Mapping[str, Sequence[Any]], area_m2: float | None, area_source: str,
                plot_area_m2: float | None = None, equipment: Mapping[str, Any] | None = None, step_hours: float = 1.0) -> dict[str, Any]:
    """Vector A (yield, water, energy, risk) and view C (cost of resources) of one run. ``equipment`` (the request's) overrides the configured one field by field."""
    missing: list[str] = []
    equip = _merge_equipment(resources.equipment, equipment)
    steps = len(times)
    fraction = resources.fraction_for(crop)
    per_area = area_m2 if area_m2 and area_m2 > 0 else None
    if per_area is None:
        missing.append("area (the plot has no area in the farm configuration and the run has no layout)")

    # ---- yield -----------------------------------------------------------------------------------------------------------------------------------
    fruit = _series(series, "biomass_fruit_g_m2")
    yield_block: dict[str, Any] = {"fruit_dry_matter_g_m2": None, "fruit_dry_matter_peak_g_m2": None, "total_dry_matter_g_m2": None, "dry_matter_kg": None, "fresh_product_kg_m2": None,
                                   "fresh_product_kg": None, "fresh_product_t_ha": None, "calibre": "not modelled", "note": "marketable yield is fresh product; the model gives dry matter"}
    if fruit:
        gain = fruit[-1] - fruit[0]
        yield_block.update(fruit_dry_matter_g_m2=gain, fruit_dry_matter_peak_g_m2=max(fruit))
        total = _series(series, "biomass_total_g_m2")
        yield_block["total_dry_matter_g_m2"] = None if not total else total[-1] - total[0]
        if per_area:
            yield_block["dry_matter_kg"] = gain * per_area / 1000.0
        if fraction is None:
            missing.append(f"fruit_dry_matter_fraction of {crop}")
        else:
            yield_block["fresh_product_kg_m2"] = gain / 1000.0 / fraction
            if per_area:
                yield_block["fresh_product_kg"] = gain * per_area / 1000.0 / fraction
            yield_block["fresh_product_t_ha"] = gain / 1000.0 / fraction * 10.0
    fresh_kg_m2 = yield_block["fresh_product_kg_m2"]
    dry_kg_m2 = None if yield_block["fruit_dry_matter_g_m2"] is None else yield_block["fruit_dry_matter_g_m2"] / 1000.0

    # ---- water -----------------------------------------------------------------------------------------------------------------------------------
    irrigation, drainage, rain, transpiration = (_series(series, name) for name in ("irrigation_mm", "drainage_mm", "precipitation_mm", "transpiration_mm"))
    water_block: dict[str, Any] = {"irrigation_mm": None, "irrigation_m3": None, "drainage_mm": None, "drained_share": None, "precipitation_mm": None, "transpiration_mm": None,
                                   "product_per_m3_irrigation_kg": None, "cost": None, "cost_per_m2": None}
    if irrigation is not None:
        applied = sum(irrigation)
        water_block.update(irrigation_mm=applied, irrigation_m3=None if not per_area else applied * per_area / 1000.0)
        received = applied + (sum(rain) if rain else 0.0)
        if drainage is not None:
            water_block.update(drainage_mm=sum(drainage), drained_share=None if received <= 0 else sum(drainage) / received)
        water_block.update(precipitation_mm=None if rain is None else sum(rain), transpiration_mm=None if transpiration is None else sum(transpiration))
        if applied > 0:
            water_block["product_per_m3_irrigation_kg"] = None if fresh_kg_m2 is None else fresh_kg_m2 / (applied / 1000.0)
            water_block["dry_matter_per_m3_irrigation_kg"] = None if dry_kg_m2 is None else dry_kg_m2 / (applied / 1000.0)
        water_cost = None
        if not resources.water.defined:
            missing.append("water price")
        else:
            step_m3 = [mm / 1000.0 for mm in irrigation]  # per m2: the price per m3 times the volume per m2
            water_cost = energy_cost(times, step_m3, resources.water.as_tariff(resources.currency))["total_cost"]
        water_block.update(cost=None if water_cost is None or not per_area else water_cost * per_area, cost_per_m2=water_cost)
    else:
        missing.append("irrigation series")

    # ---- energy ----------------------------------------------------------------------------------------------------------------------------------
    heating, cooling, extractor_level = (_series(series, name) for name in ("greenhouse_heating_kw", "greenhouse_cooling_kw", "control_extractor_level"))
    energy_block: dict[str, Any] = {"heating_thermal_kwh": None, "cooling_thermal_kwh": None, "heating_input_kwh": None, "cooling_input_kwh": None, "extractor_kwh": None, "input_kwh": None,
                                    "input_kwh_per_m2": None, "cost": None, "cost_per_m2": None, "basis": "thermal power of the greenhouse model divided by the efficiency of the equipment, plus the extractors"}
    if heating is not None and cooling is not None:
        heating_kwh, cooling_kwh = sum(heating) * step_hours, sum(cooling) * step_hours
        energy_block.update(heating_thermal_kwh=heating_kwh, cooling_thermal_kwh=cooling_kwh)
        parts: dict[str, list[float] | None] = {}
        for label, thermal_series, thermal, efficiency, name in (("heating", heating, heating_kwh, equip.heating_efficiency, "heating_efficiency"), ("cooling", cooling, cooling_kwh, equip.cooling_cop, "cooling_cop")):
            if thermal <= 0:
                parts[label] = [0.0] * steps
            elif efficiency is None:
                parts[label] = None
                missing.append(f"equipment.{name} (the greenhouse used {label})")
            else:
                parts[label] = [kw * step_hours / efficiency for kw in thermal_series]
        if extractor_level is None or not any(extractor_level):
            parts["extractors"] = [0.0] * steps
        elif equip.extractor_power_kw is None:
            parts["extractors"] = None
            missing.append("equipment.extractor_power_kw (extractors ran)")
        else:
            parts["extractors"] = [level * equip.extractor_power_kw * step_hours for level in extractor_level]
        energy_block.update(heating_input_kwh=None if parts["heating"] is None else sum(parts["heating"]), cooling_input_kwh=None if parts["cooling"] is None else sum(parts["cooling"]),
                            extractor_kwh=None if parts["extractors"] is None else sum(parts["extractors"]))
        total = _sum([energy_block["heating_input_kwh"], energy_block["cooling_input_kwh"], energy_block["extractor_kwh"]])
        energy_block["input_kwh"] = total
        if total is not None and per_area:
            energy_block["input_kwh_per_m2"] = total / per_area
        # cost: heating at its own price when the user gave one, cooling and extractors at the electricity price
        electricity_priced = resources.electricity.flat_per_kwh is not None or resources.electricity.yearly or any(band.price_per_kwh is not None for band in resources.electricity.bands)
        heating_tariff = resources.heating_energy if resources.heating_energy is not None else resources.electricity
        heating_priced = heating_tariff.flat_per_kwh is not None or heating_tariff.yearly or any(band.price_per_kwh is not None for band in heating_tariff.bands)
        if parts["heating"] is not None and parts["cooling"] is not None and parts["extractors"] is not None:
            needs_electricity = any(parts[name] and sum(parts[name]) > 0 for name in ("cooling", "extractors"))
            needs_heating = bool(parts["heating"] and sum(parts["heating"]) > 0)
            if (needs_electricity and not electricity_priced) or (needs_heating and not heating_priced):
                missing.append("energy price (electricity" + ("" if not needs_heating or resources.heating_energy is not None else " or heating") + ")")
            else:
                electric = [c + e for c, e in zip(parts["cooling"], parts["extractors"])]
                heating_cost = energy_cost(times, parts["heating"], heating_tariff)["total_cost"] if needs_heating else 0.0
                electric_cost = energy_cost(times, electric, resources.electricity)["total_cost"] if needs_electricity else 0.0
                if heating_cost is None or electric_cost is None:
                    missing.append("energy price for every year of the run (the yearly table does not cover them all and there is no single price)")
                else:
                    cost = heating_cost + electric_cost
                    energy_block.update(cost=cost, cost_per_m2=None if not per_area else cost / per_area)
    else:
        energy_block["basis"] = "open field: no greenhouse climate equipment in the model"

    # ---- risk (hours outside the stage's range, from the crop catalogue) --------------------------------------------------------------------------
    temperature, stages = _series(series, "temperature_c"), series.get("crop_stage")
    risk: dict[str, Any] = {"hours_above_max_temp": None, "hours_below_min_temp": None, "hours_above_critical_heat": None, "peak_frost_damage": None, "peak_accumulated_stress": None,
                            "mean_heat_stress": None, "mean_water_stress": None, "thresholds": "per stage from src/crop_config.json; a stage without a threshold is not counted and is listed in undefined_thresholds"}
    undefined: set[str] = set()
    if temperature is not None and stages is not None:
        above = below = critical = 0
        for value, stage in zip(temperature, stages):
            setpoints = stage_setpoints(crop, str(stage))
            if setpoints.max_temp_c is None:
                undefined.add(f"max_temp_c@{stage}")
            elif value > setpoints.max_temp_c:
                above += 1
            if setpoints.min_temp_c is None:
                undefined.add(f"min_temp_c@{stage}")
            elif value < setpoints.min_temp_c:
                below += 1
            if setpoints.critical_heat_c is None:
                undefined.add(f"critical_heat_c@{stage}")
            elif value > setpoints.critical_heat_c:
                critical += 1
        risk.update(hours_above_max_temp=above * step_hours, hours_below_min_temp=below * step_hours, hours_above_critical_heat=critical * step_hours)
    for key, name, reducer in (("peak_frost_damage", "frost_damage", max), ("peak_accumulated_stress", "accumulated_stress", max)):
        values = _series(series, name)
        risk[key] = None if not values else reducer(values)
    for key, name in (("mean_heat_stress", "heat_stress"), ("mean_water_stress", "water_stress")):
        values = _series(series, name)
        risk[key] = None if not values else sum(values) / len(values)
    risk["undefined_thresholds"] = sorted(undefined)

    # ---- view C: cost of the resources ---------------------------------------------------------------------------------------------------------------
    parts_cost = [energy_block["cost"] if energy_block["input_kwh"] is not None else None, water_block["cost"]] if energy_block.get("heating_thermal_kwh") is not None else [water_block["cost"]]
    resource_cost = _sum(parts_cost) if all(part is not None for part in parts_cost) else None
    cost_block = {"currency": resources.currency, "resource_cost": resource_cost, "resource_cost_per_m2": None if resource_cost is None or not per_area else resource_cost / per_area,
                  "resource_cost_per_kg_product": None if resource_cost is None or not per_area or not yield_block["fresh_product_kg"] else resource_cost / yield_block["fresh_product_kg"],
                  "energy_share": None if resource_cost in (None, 0.0) or energy_block["cost"] is None else energy_block["cost"] / resource_cost,
                  "note": "cost of energy and water only: the product has no price here and nothing else (labour, inputs, depreciation) is modelled"}
    kwh_per_kg = None if energy_block["input_kwh"] is None or not yield_block["fresh_product_kg"] else energy_block["input_kwh"] / yield_block["fresh_product_kg"]

    plot_scaling = None
    if per_area and plot_area_m2 and plot_area_m2 != per_area:
        factor = plot_area_m2 / per_area
        plot_scaling = {"factor": factor, "plot_area_m2": plot_area_m2, "assumption": "linear: the plot is taken as identical units of the simulated one",
                        "fresh_product_kg": None if yield_block["fresh_product_kg"] is None else yield_block["fresh_product_kg"] * factor,
                        "irrigation_m3": None if water_block["irrigation_m3"] is None else water_block["irrigation_m3"] * factor,
                        "input_kwh": None if energy_block["input_kwh"] is None else energy_block["input_kwh"] * factor,
                        "resource_cost": None if resource_cost is None else resource_cost * factor}
    return {"status": STATUS, "crop": crop, "steps": steps, "step_hours": step_hours, "area": {"m2": per_area, "source": area_source}, "yield": yield_block, "water": water_block,
            "energy": {**energy_block, "kwh_per_kg_product": kwh_per_kg}, "risk": risk, "cost": cost_block, "plot_scaling": plot_scaling,
            "missing": sorted(set(missing)), "resources_hash": resources.content_hash,
            "statement": "simulated results of an uncalibrated model: they rank strategies and show directions; they are not measurements of a real farm"}
