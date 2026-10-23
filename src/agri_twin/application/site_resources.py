"""Site resources: the user's equipment, prices and conversions in one validated configuration.

Equipment efficiencies and capacities, the price of electricity, heating fuel and water, and the share of dry matter of the fresh product live together in ``src/site_resources.json``.
Every field is empty until the user defines it; nothing is assumed, and a result that needs an empty field is reported as not computable (see ``season_kpis``).

The configuration is user data, not a model parameter: it never enters the simulation request (the equipment of a request is given in its ``control`` block as before) and it does not change a
hash of the simulation. A result computed with it carries the configuration's own ``content_hash``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agri_twin.application.energy_cost import Tariff, TariffError
from agri_twin.application.scientific_benchmark import KNOWN_CROPS
from agri_twin.domain.climate_control import ClimateControlError, EquipmentSpec

SITE_RESOURCES_FILE = Path(__file__).resolve().parents[2] / "site_resources.json"
SECTIONS = ("contract", "version", "status", "note", "equipment", "prices", "crops", "meanings")
PRICE_FIELDS = ("currency", "electricity", "heating_energy", "water")


class SiteResourcesError(ValueError):
    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(message)
        self.message, self.path = message, path


def _positive(value: Any, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise SiteResourcesError("must be a non-negative number or empty", path)
    return float(value)


@dataclass(frozen=True, slots=True)
class WaterPrice:
    """Price of irrigation water per cubic metre: a single price and/or a table per calendar year (a year missing from the table falls back to the single price)."""

    flat_per_m3: float | None = None
    yearly: tuple[tuple[int, float], ...] = ()

    @classmethod
    def from_mapping(cls, document: Mapping[str, Any] | None) -> "WaterPrice":
        document = dict(document or {})
        unknown = sorted(set(document) - {"flat_per_m3", "yearly"})
        if unknown:
            raise SiteResourcesError(f"unknown water price fields: {', '.join(unknown)}; allowed: flat_per_m3, yearly", f"prices.water.{unknown[0]}")
        flat = _positive(document.get("flat_per_m3"), "prices.water.flat_per_m3")
        yearly_raw = document.get("yearly") or {}
        if not isinstance(yearly_raw, Mapping):
            raise SiteResourcesError("must map a year to a price", "prices.water.yearly")
        yearly = []
        for key, value in yearly_raw.items():
            try:
                year = int(key)
            except (TypeError, ValueError):
                raise SiteResourcesError(f"{key!r} is not a year", "prices.water.yearly") from None
            yearly.append((year, _positive(value, f"prices.water.yearly.{key}") or 0.0))
        return cls(flat, tuple(sorted(yearly)))

    @property
    def defined(self) -> bool:
        return self.flat_per_m3 is not None or bool(self.yearly)

    def as_tariff(self, currency: str) -> Tariff:
        """The same price mechanics as the energy tariff (the unit is the caller's: m3 here)."""
        return Tariff.from_mapping({"currency": currency, "flat_per_kwh": self.flat_per_m3, "yearly": {str(year): price for year, price in self.yearly}})

    def to_dict(self) -> dict[str, Any]:
        return {"flat_per_m3": self.flat_per_m3, "yearly": {str(year): price for year, price in self.yearly}}


@dataclass(frozen=True, slots=True)
class SiteResources:
    equipment: EquipmentSpec
    currency: str
    electricity: Tariff
    heating_energy: Tariff | None
    water: WaterPrice
    fruit_dry_matter_fraction: tuple[tuple[str, float | None], ...]

    @classmethod
    def from_mapping(cls, document: Mapping[str, Any]) -> "SiteResources":
        if not isinstance(document, Mapping):
            raise SiteResourcesError("the configuration must be a mapping")
        unknown = sorted(set(document) - set(SECTIONS))
        if unknown:
            raise SiteResourcesError(f"unknown section {unknown[0]!r}; allowed: {', '.join(SECTIONS)}", unknown[0])
        try:
            equipment = EquipmentSpec.from_mapping(document.get("equipment"))
        except ClimateControlError as exc:
            raise SiteResourcesError(str(exc), "equipment") from None
        prices = document.get("prices") or {}
        if not isinstance(prices, Mapping):
            raise SiteResourcesError("must be a mapping", "prices")
        unknown = sorted(set(prices) - set(PRICE_FIELDS))
        if unknown:
            raise SiteResourcesError(f"unknown price field {unknown[0]!r}; allowed: {', '.join(PRICE_FIELDS)}", f"prices.{unknown[0]}")
        currency = prices.get("currency", "EUR")
        if not isinstance(currency, str) or not currency.strip():
            raise SiteResourcesError("must be a non-empty string", "prices.currency")
        try:
            electricity = Tariff.from_mapping({"currency": currency, **_tariff_fields(prices.get("electricity"))})
            heating = None if not prices.get("heating_energy") else Tariff.from_mapping({"currency": currency, **_tariff_fields(prices.get("heating_energy"))})
        except TariffError as exc:
            raise SiteResourcesError(str(exc), "prices") from None
        crops_raw = document.get("crops") or {}
        if not isinstance(crops_raw, Mapping):
            raise SiteResourcesError("must be a mapping", "crops")
        fractions = []
        for crop, entry in crops_raw.items():
            if crop not in KNOWN_CROPS:
                raise SiteResourcesError(f"unknown crop {crop!r}; known: {', '.join(KNOWN_CROPS)}", f"crops.{crop}")
            if not isinstance(entry, Mapping) or set(entry) - {"fruit_dry_matter_fraction"}:
                raise SiteResourcesError("must hold only fruit_dry_matter_fraction", f"crops.{crop}")
            fraction = _positive(entry.get("fruit_dry_matter_fraction"), f"crops.{crop}.fruit_dry_matter_fraction")
            if fraction is not None and not 0.0 < fraction <= 1.0:
                raise SiteResourcesError("must be a share between 0 (exclusive) and 1", f"crops.{crop}.fruit_dry_matter_fraction")
            fractions.append((crop, fraction))
        return cls(equipment, currency.strip(), electricity, heating, WaterPrice.from_mapping(prices.get("water")), tuple(sorted(fractions)))

    def fraction_for(self, crop: str) -> float | None:
        return dict(self.fruit_dry_matter_fraction).get(crop)

    def to_dict(self) -> dict[str, Any]:
        return {"equipment": self.equipment.to_dict(),
                "prices": {"currency": self.currency, "electricity": _tariff_document(self.electricity), "heating_energy": None if self.heating_energy is None else _tariff_document(self.heating_energy),
                           "water": self.water.to_dict()},
                "crops": {crop: {"fruit_dry_matter_fraction": fraction} for crop, fraction in self.fruit_dry_matter_fraction}}

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _tariff_fields(document: Any) -> dict[str, Any]:
    if not document:
        return {}
    if not isinstance(document, Mapping):
        raise TariffError("a tariff must be a mapping")
    return {key: value for key, value in document.items() if value not in (None, [], {}) or key == "flat_per_kwh" and value is not None}


def _tariff_document(tariff: Tariff) -> dict[str, Any]:
    return {"flat_per_kwh": tariff.flat_per_kwh, "yearly": {str(year): price for year, price in tariff.yearly},
            "time_of_day": [{"from_hour": band.from_hour, "to_hour": band.to_hour, **({"price_per_kwh": band.price_per_kwh} if band.price_per_kwh is not None else {"factor": band.factor})} for band in tariff.bands],
            "utc_offset_hours": tariff.utc_offset_hours}


def load_site_resources(path: Path | str | None = None) -> tuple[SiteResources, dict[str, Any]]:
    """(validated resources, the raw document with its notes). The empty template validates to an all-empty configuration."""
    source = Path(path) if path is not None else SITE_RESOURCES_FILE
    document = json.loads(source.read_text(encoding="utf-8"))
    return SiteResources.from_mapping(document), document


def save_site_resources(update: Mapping[str, Any], path: Path | str | None = None) -> SiteResources:
    """Validate ``update`` (equipment, prices, crops) and write it into the file, keeping its contract, notes and meanings. Atomic: a failed validation changes nothing."""
    target = Path(path) if path is not None else SITE_RESOURCES_FILE
    document = json.loads(target.read_text(encoding="utf-8"))
    merged = {**document, **{key: update[key] for key in ("equipment", "prices", "crops") if key in update}}
    unknown = sorted(set(update) - {"equipment", "prices", "crops"})
    if unknown:
        raise SiteResourcesError(f"only equipment, prices and crops can be saved, not {unknown[0]!r}", unknown[0])
    resources = SiteResources.from_mapping(merged)
    merged["status"] = "USER_DEFINED"
    handle, temporary = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return resources
