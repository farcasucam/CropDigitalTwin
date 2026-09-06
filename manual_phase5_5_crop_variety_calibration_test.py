"""Offline delivery audit for Phase 5.5 crop/variety calibration protocol."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import ParameterRegistry, ScientificStatus, build_protocol


ROOT = Path(__file__).resolve().parent


def main() -> int:
    registry = ParameterRegistry.from_repository(ROOT)
    combinations = [("tomato", "RAF", "plot_12010"), ("pepper", "Lamuyo", "plot_40811"), ("grape", "Monastrell", "plot_30412"), ("plum", "Suplum 26", "plot_14705"), ("lettuce", None, None), ("peach", None, None), ("apple", None, None)]
    protocols = [build_protocol(ROOT, registry, crop, variety, plot) for crop, variety, plot in combinations]
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 5.5 CROP/VARIETY CALIBRATION")
    print("=" * 60)
    for protocol in protocols:
        print(f"[{protocol.crop:7}] variety={protocol.variety or 'generic':12} plot={protocol.plot or '-':12} status={protocol.status.value:18} observations={protocol.observation_audit.observation_count:3} candidates={len(protocol.parameter_set().values):3}")
    assert all(protocol.status == ScientificStatus.INSUFFICIENT_DATA for protocol in protocols)
    assert all(protocol.observation_audit.observation_count == 0 for protocol in protocols)
    print("\nSYNTHETIC DEMONSTRATION: protocol ready; no real observations calibrated")
    print("NOT REAL CROP VALIDATION")
    print("PHASE 5.5 STATUS: FRAMEWORK READY - INSUFFICIENT_DATA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())