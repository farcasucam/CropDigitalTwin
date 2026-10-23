# Phase 5.47: site resources (equipment, prices, conversions) and season results

Status: **COMPLETE (software qualification)**. User data and post-processing of simulated runs; **not** a model change, and the results come from an uncalibrated model (they rank strategies and show directions, they are not measurements of a real farm).

## Why

The research objective is the whole crop season with three competing goals: yield, water and energy. Equipment efficiencies, the price of energy and water and the conversion of simulated dry matter to marketable units were spread over the bench (equipment and
tariff in `localStorage`) or missing (water price, conversions). They now live in one validated configuration the server, the bench and the future XAI pipeline share.

## The configuration (`src/site_resources.json`, `application/site_resources.py`)

* **equipment**: the `EquipmentSpec` fields (vents and extractors, extractor power, cooling capacity and **COP**, heating capacity and **efficiency**, irrigation limit).
* **prices**: currency; **electricity** (the tariff of phase 5.42: single price, table per year, time-of-day bands); **heating_energy** (own price, empty: electricity is used); **water** (per m3: single price and/or table per calendar year).
* **crops**: `fruit_dry_matter_fraction` per crop (share of dry matter in the fresh product, 0-1).
* The committed file is an **empty template** (`USER_DEFINED_EMPTY_TEMPLATE`): nothing is assumed. Saving (`POST /api/site-resources`, or the bench's "Save to site configuration") validates first, keeps the contract and notes, writes atomically and sets `USER_DEFINED`.
  `content_hash` identifies a configuration; every result computed with it carries it. The configuration never enters a simulation request or a simulation hash.
* `GET /api/site-resources` also returns the plot areas of `src/farm_config.json` (tomato, pepper, grape and plum have one; lettuce, peach and apple do not).

## Season results (`application/season_kpis.py`, `POST /api/kpis/season`)

Vector **A** (yield, water, energy, risk) and view **C** (cost of the resources) of one run. The product has **no price** (an imponderable per season): the economic view is the cost of energy and water, in total, per m2 and per kg of product.

| Block | Content | Needs from the user |
|---|---|---|
| Yield | fruit dry matter (g/m2, kg), fresh product (kg/m2, kg, t/ha); calibre: not modelled | dry-matter share of the crop; area |
| Water | irrigation (mm, m3), drained share, precipitation, transpiration, kg of product per m3 of irrigation, cost | water price; area |
| Energy | thermal heating and cooling (kWh), input energy = thermal / efficiency (+ extractors), per m2, per kg of product, cost | heating efficiency and cooling COP (only when that equipment ran), extractor power, energy price |
| Risk | hours above the stage maximum, below its minimum, above critical heat (thresholds per stage from `crop_config.json`), peak frost damage, accumulated stress | nothing (a stage without threshold is listed, never invented) |
| Cost | energy + water, per m2, per kg, energy share | prices, area, dry-matter share |

* Energy is accounted from the **thermal power of the greenhouse model** divided by the efficiency of the equipment, so a baseline without a controller (the greenhouse's default thermostat) and a controlled run are compared on the same basis. The request's own equipment overrides the configured one field by field.
* **Area:** the run simulates one unit (a greenhouse module of the layout, or the open-field plot). Greenhouse: the floor area of the layout (energy and equipment refer to it); the 3.25 ha tomato plot of the farm file is shown as a **linear scaling** (factor = plot / unit) flagged as an assumption. Open field: the plot area of the farm file.
* Whatever needs an undefined value is `null` and listed in `missing`; the bench shows n/a with the reason.
* Heating uses its own price when given; cooling and extractors use the electricity tariff (one price per kind of energy; no demand charges).

## Bench

Group "6 · Resources and prices" (water price and per-year table, heating fuel price, dry-matter share of the current crop, load/save buttons) and panel **Season results** under the charts: baseline / intervention / delta for every KPI, with the area, the scaling and what is missing. Equipment and electricity tariff stay in the Climate control group; the bench sends the current (even unsaved) resources with each request.

## Observation worth knowing

In the default tomato greenhouse season about 90 % of the irrigation drains (273 mm applied in a month, 89.6 % drained): the base scenario waters far above the crop's demand, so the water objective has a large margin that has nothing to do with the climate strategy.

## Tests

`tests/test_site_resources_kpis.py`: empty template, validation with paths, atomic save, conversions (dry matter to fresh product, area), water volume and cost per year, energy from efficiencies (COP only if cooling ran), request equipment override, own heating price, cost per m2 and per kg, risk hours from the catalogue, linear scaling, open field, and the API on a real run.
