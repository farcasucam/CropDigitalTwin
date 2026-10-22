"""Cost of the estimated control energy under a user-defined tariff.

Pure post-processing of a trajectory: the tariff is not part of the simulation request, so changing it never re-runs the simulation, changes a hash or touches the
physical state. Nothing is assumed: with no price for a step, the cost of that step (and the running sum after it) is ``None``, as for an energy that is not estimable.

A tariff combines up to three user-supplied pieces:

* ``flat_per_kwh``: one price for every step.
* ``yearly``: ``{"2027": 0.18, "2030": 0.22}``, a price per calendar year (a future-price scenario). A year missing from the table falls back to ``flat_per_kwh``.
* ``time_of_day``: bands ``{"from_hour": 0, "to_hour": 8, "price_per_kwh": 0.09}`` (absolute price) or ``{..., "factor": 1.5}`` (multiplies the flat/yearly price of the step).
  Hours follow the simulation clock plus ``utc_offset_hours``; ``to_hour`` is exclusive and may be 24; a band may wrap midnight (``from_hour`` 22, ``to_hour`` 6).
  Hours covered by no band use the flat/yearly price unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

TARIFF_FIELDS = ("currency", "flat_per_kwh", "yearly", "time_of_day", "utc_offset_hours")


class TariffError(ValueError):
    pass


def _price(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise TariffError(f"{name} must be a non-negative number")
    return float(value)


@dataclass(frozen=True, slots=True)
class Band:
    from_hour: int
    to_hour: int
    price_per_kwh: float | None
    factor: float | None

    def covers(self, hour: int) -> bool:
        return self.from_hour <= hour < self.to_hour if self.from_hour < self.to_hour else hour >= self.from_hour or hour < self.to_hour


@dataclass(frozen=True, slots=True)
class Tariff:
    currency: str = "EUR"
    flat_per_kwh: float | None = None
    yearly: tuple[tuple[int, float], ...] = ()
    bands: tuple[Band, ...] = ()
    utc_offset_hours: float = 0.0

    @classmethod
    def from_mapping(cls, document: Mapping[str, Any] | None) -> "Tariff":
        if not isinstance(document, Mapping):
            raise TariffError("tariff must be a mapping")
        unknown = sorted(set(document) - set(TARIFF_FIELDS))
        if unknown:
            raise TariffError(f"unknown tariff fields: {', '.join(unknown)}; allowed: {', '.join(TARIFF_FIELDS)}")
        currency = document.get("currency", "EUR")
        if not isinstance(currency, str) or not currency.strip():
            raise TariffError("currency must be a non-empty string")
        flat = None if document.get("flat_per_kwh") is None else _price(document["flat_per_kwh"], "flat_per_kwh")
        yearly_raw = document.get("yearly") or {}
        if not isinstance(yearly_raw, Mapping):
            raise TariffError("yearly must map a year to a price")
        yearly = []
        for key, value in yearly_raw.items():
            try:
                year = int(key)
            except (TypeError, ValueError):
                raise TariffError(f"yearly key {key!r} is not a year") from None
            yearly.append((year, _price(value, f"yearly.{key}")))
        offset = document.get("utc_offset_hours", 0.0)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not -14 <= offset <= 14:
            raise TariffError("utc_offset_hours must be a number between -14 and 14")
        bands_raw = document.get("time_of_day") or []
        if not isinstance(bands_raw, Sequence) or isinstance(bands_raw, str):
            raise TariffError("time_of_day must be a list of bands")
        bands = []
        for index, item in enumerate(bands_raw):
            if not isinstance(item, Mapping) or set(item) - {"from_hour", "to_hour", "price_per_kwh", "factor"}:
                raise TariffError(f"time_of_day[{index}] must hold from_hour, to_hour and price_per_kwh or factor")
            start, end = item.get("from_hour"), item.get("to_hour")
            if any(isinstance(h, bool) or not isinstance(h, int) for h in (start, end)) or not (0 <= start <= 23 and 1 <= end <= 24) or start == end:
                raise TariffError(f"time_of_day[{index}]: from_hour in 0-23 and to_hour in 1-24, different")
            if (item.get("price_per_kwh") is None) == (item.get("factor") is None):
                raise TariffError(f"time_of_day[{index}] needs exactly one of price_per_kwh and factor")
            price = None if item.get("price_per_kwh") is None else _price(item["price_per_kwh"], f"time_of_day[{index}].price_per_kwh")
            factor = None if item.get("factor") is None else _price(item["factor"], f"time_of_day[{index}].factor")
            bands.append(Band(start, end, price, factor))
        for hour in range(24):
            if sum(band.covers(hour) for band in bands) > 1:
                raise TariffError(f"time_of_day bands overlap at hour {hour}")
        return cls(currency.strip(), flat, tuple(sorted(yearly)), tuple(bands), float(offset))

    def price_at(self, when: datetime) -> float | None:
        local = when + timedelta(hours=self.utc_offset_hours)
        base = dict(self.yearly).get(local.year, self.flat_per_kwh)
        for band in self.bands:
            if band.covers(local.hour):
                if band.price_per_kwh is not None:
                    return band.price_per_kwh
                return None if base is None else base * band.factor  # type: ignore[operator]
        return base


def energy_cost(times: Sequence[str], energy_kwh: Sequence[float | None], tariff: Mapping[str, Any] | Tariff) -> dict[str, Any]:
    """Cost per step, running cost and total of an energy series. ``None`` energy or price makes that step, and the running sum from there, ``None``."""
    tariff = tariff if isinstance(tariff, Tariff) else Tariff.from_mapping(tariff)
    if len(times) != len(energy_kwh):
        raise TariffError("time and energy_kwh must have the same length")
    prices: list[float | None] = []
    cost: list[float | None] = []
    cumulative: list[float | None] = []
    running: float | None = 0.0
    priced = unpriced = 0
    for stamp, energy in zip(times, energy_kwh):
        try:
            when = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            raise TariffError(f"time {stamp!r} is not an ISO 8601 timestamp") from None
        if energy is not None and (isinstance(energy, bool) or not isinstance(energy, (int, float)) or not math.isfinite(energy) or energy < 0):
            raise TariffError("energy_kwh values must be non-negative numbers or null")
        price = tariff.price_at(when)
        step = None if price is None or energy is None else energy * price
        priced += step is not None
        unpriced += step is None
        running = None if running is None or step is None else running + step
        prices.append(price)
        cost.append(step)
        cumulative.append(running)
    return {"currency": tariff.currency, "price_per_kwh": prices, "cost": cost, "cost_cumulative": cumulative, "total_cost": running,
            "steps_priced": priced, "steps_without_price_or_energy": unpriced,
            "note": "cost = estimated control energy x the tariff you supplied; no price is assumed, a step without one has no cost"}
