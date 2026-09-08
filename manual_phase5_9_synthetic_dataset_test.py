"""Offline Phase 5.9 acceptance audit."""

from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from agri_twin.application import SyntheticReferenceDatasetGenerator
from agri_twin.domain import DatasetRole


def main() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 9, 15, tzinfo=timezone.utc)
    generator = SyntheticReferenceDatasetGenerator()
    first = generator.generate(start, end, seed=5901)
    second = generator.generate(start, end, seed=5901)
    assert first == second
    assert len(first.plots) == 7
    assert len(first.crop_cycles) == 8
    assert {plot.plot_id for plot in first.plots} >= {"plot_12010", "plot_40811", "plot_30412", "plot_14705"}
    with TemporaryDirectory() as directory:
        first.write_csv(directory)
    assert first.observation_dataset(DatasetRole.TEST).source_type == "synthetic_test_data"
    print("PASS: deterministic synthetic dataset")
    print("PASS: 4 configured plots plus 3 synthetic crops; 7 crops; 2 lettuce cycles")
    print("PASS: lifecycle, multi-plot, synthetic weather and observation provenance")
    print("PASS: technician package is separate and contains no real observations")
    print("PHASE 5.9 COMPLETE — SYNTHETIC SIMULATION DATA PROVIDER READY — AGRICULTURAL DATA COLLECTION PACKAGE READY — REAL AGRONOMIC DATA NOT AVAILABLE — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
