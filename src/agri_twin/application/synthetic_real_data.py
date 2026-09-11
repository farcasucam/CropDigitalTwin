"""Synthetic real-data substitute and sensitivity framework.

This phase intentionally does not create a second observation pipeline. It reuses
`ObservationDataset`, `ObservationIngestion`, `TemporalAlignment`,
`ComparisonDataset`, `ErrorDiagnostics`, and the existing registry flow while
making the source-provenance contract explicit and future-real substitution-ready.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from agri_twin.domain.calibration import DatasetRole, Observation, ObservationDataset
from agri_twin.domain.observation_ingestion import ObservationSourceType, ingest_rows
from agri_twin.domain.parameter_audit import ParameterRegistry


@dataclass(frozen=True, slots=True)
class AgronomicDatasetManifest:
    dataset_id: str
    dataset_name: str
    dataset_version: str
    source_type: str
    provenance: str
    created_at_simulation_context: str
    crop_scope: tuple[str, ...]
    variety_scope: tuple[str, ...]
    plot_scope: tuple[str, ...]
    environment_scope: tuple[str, ...]
    cycle_scope: tuple[str, ...]
    variables: tuple[str, ...]
    units: dict[str, str]
    timezone: str = "UTC"
    quality_policy: str = "VALID/MISSING/INVALID/DUPLICATE/OUT_OF_RANGE/UNIT_ERROR; no replacement of scientific quality labels"
    synthetic: bool = True
    substitution_ready: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "source_type": self.source_type,
            "provenance": self.provenance,
            "created_at_simulation_context": self.created_at_simulation_context,
            "crop_scope": list(self.crop_scope),
            "variety_scope": list(self.variety_scope),
            "plot_scope": list(self.plot_scope),
            "environment_scope": list(self.environment_scope),
            "cycle_scope": list(self.cycle_scope),
            "variables": list(self.variables),
            "units": dict(self.units),
            "timezone": self.timezone,
            "quality_policy": self.quality_policy,
            "synthetic": self.synthetic,
            "substitution_ready": self.substitution_ready,
        }


class AgronomicDatasetProvider(Protocol):
    manifest: AgronomicDatasetManifest

    def load(self, *, role: DatasetRole = DatasetRole.TEST) -> ObservationDataset: ...


from agri_twin.application.sensitivity import (
    ParameterSensitivityAnalyzer,
    ParameterSensitivityResult,
    SensitivityReport,
    SensitivityResult,
)


class SyntheticAgronomicDatasetProvider:
    """Synthetic dataset provider that preserves the common observation contract."""

    def __init__(self, root: str | Path, *, dataset_id: str = "synthetic_real_data_substitute") -> None:
        self.root = Path(root)
        self.dataset_id = dataset_id
        self.data_dir = self.root / "data" / "synthetic_real_substitute"
        self.manifest_path = self.data_dir / "manifest.json"
        self.csv_path = self.data_dir / "observations.csv"
        self.readme_path = self.data_dir / "README.md"
        self.manifest = self._load_manifest()

    def load(self, *, role: DatasetRole = DatasetRole.TEST) -> ObservationDataset:
        rows = self._load_rows()
        ingestion = ingest_rows(
            rows,
            dataset_id=self.dataset_id,
            role=role,
            source="synthetic_real_data_substitute",
            source_type=ObservationSourceType.SYNTHETIC_TEST,
            original_filename=self.csv_path.name,
            imported_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        if ingestion.dataset is None:
            rows = self._generate_rows()
            self._write_csv(rows)
            self.manifest = self._build_manifest(rows)
            self.manifest_path.write_text(json.dumps(self.manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            ingestion = ingest_rows(
                rows,
                dataset_id=self.dataset_id,
                role=role,
                source="synthetic_real_data_substitute",
                source_type=ObservationSourceType.SYNTHETIC_TEST,
                original_filename=self.csv_path.name,
                imported_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        if ingestion.dataset is None:
            raise ValueError("synthetic real-data substitute produced no ingestible observations")
        observations = tuple(replace(item, source_type="synthetic") for item in ingestion.dataset.observations)
        return ObservationDataset(
            name=ingestion.dataset.name,
            role=ingestion.dataset.role,
            observations=observations,
            source=ingestion.dataset.source,
            source_type="synthetic",
            original_filename=ingestion.dataset.original_filename,
            imported_at=ingestion.dataset.imported_at,
        )

    def _load_rows(self) -> list[dict[str, Any]]:
        if self.csv_path.exists():
            with self.csv_path.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            if rows and not self._needs_regeneration(rows):
                return rows
        rows = self._generate_rows()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(rows)
        self.manifest = self._build_manifest(rows)
        self.manifest_path.write_text(json.dumps(self.manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.readme_path.write_text(self._readme_text(self.manifest), encoding="utf-8")
        return rows

    @staticmethod
    def _needs_regeneration(rows: list[dict[str, Any]]) -> bool:
        required = {"timestamp", "variable", "value", "unit", "source"}
        return any(
            not required.issubset(row) or row.get("value") in (None, "") or row.get("source") in (None, "")
            or not str(row.get("value", "")).replace(".", "", 1).replace("-", "", 1).isdigit()
            for row in rows
        )

    def _load_manifest(self) -> AgronomicDatasetManifest:
        if self.manifest_path.exists():
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return AgronomicDatasetManifest(
                dataset_id=payload["dataset_id"],
                dataset_name=payload.get("dataset_name", payload["dataset_id"]),
                dataset_version=payload.get("dataset_version", "1.0"),
                source_type=payload.get("source_type", "synthetic"),
                provenance=payload.get("provenance", "SIMULATED_REAL_DATA_SUBSTITUTE"),
                created_at_simulation_context=payload.get("created_at_simulation_context", "SimulationClock"),
                crop_scope=tuple(payload.get("crop_scope", ())),
                variety_scope=tuple(payload.get("variety_scope", ())),
                plot_scope=tuple(payload.get("plot_scope", ())),
                environment_scope=tuple(payload.get("environment_scope", ())),
                cycle_scope=tuple(payload.get("cycle_scope", ())),
                variables=tuple(payload.get("variables", ())),
                units=dict(payload.get("units", {})),
                timezone=payload.get("timezone", "UTC"),
                quality_policy=payload.get("quality_policy", "VALID/MISSING/INVALID/DUPLICATE/OUT_OF_RANGE/UNIT_ERROR; no replacement of scientific quality labels"),
                synthetic=bool(payload.get("synthetic", True)),
                substitution_ready=bool(payload.get("substitution_ready", True)),
            )
        rows = self._generate_rows()
        manifest = self._build_manifest(rows)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._write_csv(rows)
        self.readme_path.write_text(self._readme_text(manifest), encoding="utf-8")
        return manifest

    def _build_manifest(self, rows: list[dict[str, Any]]) -> AgronomicDatasetManifest:
        crops = tuple(sorted({row["crop"] for row in rows if row.get("crop")}))
        varieties = tuple(sorted({row["variety"] for row in rows if row.get("variety")}))
        plots = tuple(sorted({row["plot_id"] for row in rows if row.get("plot_id")}))
        environments = tuple(sorted({row["environment"] for row in rows if row.get("environment")}))
        cycles = tuple(sorted({row["cycle_id"] for row in rows if row.get("cycle_id")}))
        variables = tuple(sorted({row["variable"] for row in rows if row.get("variable")}))
        units = {variable: next(item["unit"] for item in rows if item.get("variable") == variable and item.get("unit")) for variable in variables}
        return AgronomicDatasetManifest(
            dataset_id=self.dataset_id,
            dataset_name=self.dataset_id,
            dataset_version="1.0",
            source_type="synthetic",
            provenance="SIMULATED_REAL_DATA_SUBSTITUTE",
            created_at_simulation_context="SimulationClock(2026-01-01T00:00:00+00:00)",
            crop_scope=crops,
            variety_scope=varieties,
            plot_scope=plots,
            environment_scope=environments,
            cycle_scope=cycles,
            variables=variables,
            units=units,
            timezone="UTC",
            quality_policy="VALID/MISSING/INVALID/DUPLICATE/OUT_OF_RANGE/UNIT_ERROR; synthetic only; no measured-data claim",
            synthetic=True,
            substitution_ready=True,
        )

    def _write_csv(self, rows: list[dict[str, Any]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "timestamp",
            "plot_id",
            "cycle_id",
            "crop",
            "variety",
            "environment",
            "variable",
            "value",
            "unit",
            "source",
            "method",
            "measurement_method",
            "quality",
            "uncertainty",
            "provenance",
            "source_type",
            "observation_type",
        ]
        with self.csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _generate_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        crops = (
            ("tomato", "RAF", "GREENHOUSE", "plot_12010", "cycle_tomato_1"),
            ("lettuce", "", "GREENHOUSE", "plot_14705", "cycle_1"),
            ("lettuce", "", "GREENHOUSE", "plot_14705", "cycle_2"),
            ("pepper", "Lamuyo", "GREENHOUSE", "plot_40811", "cycle_pepper_1"),
            ("grape", "Monastrell", "OUTDOOR", "plot_30412", "cycle_grape_1"),
            ("peach", "", "OUTDOOR", "plot_20500", "cycle_peach_1"),
            ("plum", "Suplum 26", "OUTDOOR", "plot_14705", "cycle_plum_1"),
            ("apple", "", "OUTDOOR", "plot_61200", "cycle_apple_1"),
        )
        variables = [
            ("air_temperature", "degC", 19.0),
            ("relative_humidity", "%", 72.0),
            ("vpd", "kPa", 1.3),
            ("solar_radiation", "W_m-2", 550.0),
            ("co2", "ppm", 420.0),
            ("lai", "m2_m-2", 1.9),
            ("biomass", "g_m-2", 250.0),
            ("soil_water_content", "m3_m-3", 0.28),
            ("yield", "kg_m-2", 0.7),
            ("fruit_weight", "g", 55.0),
        ]
        base = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
        for idx, (crop, variety, environment, plot_id, cycle_id) in enumerate(crops):
            for hour in range(0, 25, 6):
                timestamp = (base + timedelta(hours=hour + idx * 3)).isoformat().replace("+00:00", "+00:00")
                for variable, unit, value in variables:
                    if crop == "lettuce" and variable in {"yield", "fruit_weight"}:
                        if hour < 12:
                            continue
                    row = {
                        "timestamp": timestamp,
                        "plot_id": plot_id,
                        "cycle_id": cycle_id,
                        "crop": crop,
                        "variety": variety,
                        "environment": environment,
                        "variable": variable,
                        "value": round(value + idx * 0.15 + hour * 0.05, 6),
                        "unit": unit,
                        "source": "synthetic_real_data_substitute",
                        "measurement_method": "synthetic_model",
                        "quality": "VALID",
                        "uncertainty": 0.05,
                        "provenance": "SIMULATED_REAL_DATA_SUBSTITUTE",
                        "source_type": "synthetic",
                        "observation_type": "continuous",
                    }
                    rows.append(row)
        return rows

    @staticmethod
    def _readme_text(manifest: AgronomicDatasetManifest) -> str:
        return (
            "THIS IS NOT VERIFIED REAL AGRONOMIC DATA.\n\n"
            "Purpose: provide a fully deterministic synthetic dataset that supports the same\n"
            "ingestion, alignment, diagnostics, and identifiability pathway as the future real\n"
            "agronomic dataset. The dataset remains synthetic and must never be interpreted as a\n"
            "measured or validated dataset.\n\n"
            f"Dataset id: {manifest.dataset_id}\n"
            f"Provenance: {manifest.provenance}\n"
            f"Source type: {manifest.source_type}\n"
            "Generation: deterministic SimulationClock-driven synthetic generation\n"
            "Crops: tomato, lettuce, pepper, grape, peach, plum, apple\n"
            "Plots: plot_12010, plot_14705, plot_30412, plot_40811, plot_20500, plot_61200\n"
            "Environments: GREENHOUSE, OUTDOOR\n"
            "Use: replace the source file with a real dataset while preserving the same `ObservationDataset`\n"
            "contract and pipeline.\n"
        )


class RealAgronomicDatasetProvider(SyntheticAgronomicDatasetProvider):
    """Future real-data swap point. Until a verified real dataset exists, it falls back to the synthetic substitute to preserve the contract."""

    def __init__(self, root: str | Path, *, dataset_id: str = "real_agronomic_dataset") -> None:
        self.real_dataset_id = dataset_id
        super().__init__(root, dataset_id=dataset_id)
        self.real_dir = self.root / "data" / "real"
        self.real_csv = self.real_dir / "observations.csv"
        self.real_manifest = self.real_dir / "manifest.json"

    def load(self, *, role: DatasetRole = DatasetRole.TEST) -> ObservationDataset:
        if self.real_csv.exists() and self.real_manifest.exists():
            rows = list(csv.DictReader(self.real_csv.open("r", encoding="utf-8", newline="")))
            if rows:
                ingestion = ingest_rows(
                    rows,
                    dataset_id=self.real_dataset_id,
                    role=role,
                    source="real_agronomic_dataset",
                    source_type=ObservationSourceType.MEASURED,
                    original_filename=self.real_csv.name,
                    imported_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
                if ingestion.dataset is not None:
                    observations = tuple(replace(item, source_type="measured") for item in ingestion.dataset.observations)
                    return ObservationDataset(
                        name=ingestion.dataset.name,
                        role=ingestion.dataset.role,
                        observations=observations,
                        source=ingestion.dataset.source,
                        source_type="measured",
                        original_filename=ingestion.dataset.original_filename,
                        imported_at=ingestion.dataset.imported_at,
                    )
        synthetic = SyntheticAgronomicDatasetProvider(self.root)
        dataset = synthetic.load(role=role)
        return replace(dataset, source="real_agronomic_dataset", source_type="synthetic")


__all__ = [
    "AgronomicDatasetManifest",
    "AgronomicDatasetProvider",
    "ParameterSensitivityAnalyzer",
    "ParameterSensitivityResult",
    "SensitivityReport",
    "SensitivityResult",
    "SyntheticAgronomicDatasetProvider",
    "RealAgronomicDatasetProvider",
]
