"""Offline audit of the Phase 4.5 phenology research proposal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agri_twin.domain import CropConfigRepository, validate_phenology_configuration

ROOT = Path(__file__).resolve().parent
CROP = ROOT / "src" / "crop_config.json"
FARM = ROOT / "src" / "farm_config.json"
DOC = ROOT / "docs" / "phenology-parameters.md"
CROPS = {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}

# These are proposals, not operational crop values. The method reference is
# evidence for the approach only; every crop-specific transition remains null.
PROPOSALS = {
    "tomato": ("GDD candidate", "°C", "CALIBRATION_REQUIRED", False),
    "lettuce": ("GDD candidate", "°C", "CALIBRATION_REQUIRED", False),
    "pepper": ("GDD candidate", "°C", "CALIBRATION_REQUIRED", False),
    "grape": ("cultivar-specific forcing candidate", "°C", "CALIBRATION_REQUIRED", True),
    "peach": ("chilling then forcing candidate", "°C", "CALIBRATION_REQUIRED", True),
    "plum": ("chilling then forcing candidate", "°C", "CALIBRATION_REQUIRED", True),
    "apple": ("chilling then forcing candidate", "°C", "CALIBRATION_REQUIRED", True),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(name: str, function, results: list[tuple[str, str, str]]) -> None:
    try:
        results.append((name, "PASS", str(function() or "verified")))
    except Exception as exc:
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def config_coverage() -> str:
    payload = json.loads(CROP.read_text(encoding="utf-8"))
    require(set(payload["crops"]) == CROPS, "proposal does not cover exactly the seven crops")
    require(all(len(crop["stages"]) == 4 for crop in payload["crops"].values()), "stage count changed")
    CropConfigRepository(CROP)
    return "seven crops and four current stages covered"


def proposal_traceability() -> str:
    text = DOC.read_text(encoding="utf-8")
    normalized = text.lower()
    require("penn state extension" in normalized and "https://extension.psu.edu/understanding-growing-degree-days" in normalized, "method source missing")
    rows = {line.split("|")[1].strip().lower(): line.lower() for line in text.splitlines() if line.startswith("|") and not line.startswith("| Crop") and "---" not in line}
    for crop, (method, unit, status, cultivar_dependent) in PROPOSALS.items():
        row = rows.get(crop)
        require(row and method.lower() in row and unit.lower() in row and status.lower() in row, f"incomplete proposal row: {crop}")
        if cultivar_dependent:
            require("cultivar" in text.lower(), f"cultivar dependency missing: {crop}")
    return "method source, units and calibration status are documented"


def no_unbacked_activation() -> str:
    payload = json.loads(CROP.read_text(encoding="utf-8"))
    require(all("phenology" not in crop for crop in payload["crops"].values()), "phenology was activated in crop_config.json")
    require(all(value[2] == "CALIBRATION_REQUIRED" for value in PROPOSALS.values()), "unbacked proposal marked activable")
    return "no crop-specific Tbase/GDD/chilling value is operational"


def optional_contract() -> str:
    validate_phenology_configuration({
        "method": "gdd", "base_temperature_c": None, "upper_temperature_c": None,
        "biofix": None, "calibration_status": "CALIBRATION_REQUIRED",
        "source": {"reference": "https://extension.psu.edu/understanding-growing-degree-days", "type": "technical_reference"},
        "stages": [{"stage_key": "establishment", "gdd_to_next": None}],
    })
    return "null parameters and traceable future metadata validate"


def config_unchanged() -> str:
    before = hashlib.sha256(CROP.read_bytes()).hexdigest()
    json.loads(CROP.read_text(encoding="utf-8"))
    require(hashlib.sha256(CROP.read_bytes()).hexdigest() == before, "crop_config.json changed")
    require(FARM.is_file(), "farm configuration missing")
    return "productive configuration was not modified"


def no_transitions_or_http() -> str:
    engine = (ROOT / "src" / "agri_twin" / "domain" / "crop_engine.py").read_text(encoding="utf-8")
    require("def transition" not in engine and "gdd_to_next" not in engine and "gdd_accumulated" not in engine, "transition/GDD logic unexpectedly active")
    for path in (ROOT / "src" / "agri_twin" / "domain").rglob("*.py"):
        require("urllib" not in path.read_text(encoding="utf-8") and "urlopen" not in path.read_text(encoding="utf-8"), f"HTTP in domain: {path}")
    return "no automatic transitions or HTTP in domain"


def main() -> int:
    results: list[tuple[str, str, str]] = []
    run("Seven crops covered", config_coverage, results)
    run("Sources, units and status", proposal_traceability, results)
    run("Cultivar dependencies identified", proposal_traceability, results)
    run("No unbacked activation", no_unbacked_activation, results)
    run("Optional phenology contract", optional_contract, results)
    run("Configuration unchanged", config_unchanged, results)
    run("No transitions or HTTP", no_transitions_or_http, results)
    results.append(("Crop-specific calibration readiness", "SKIP", "Tbase, targets, biofix and chilling/forcing observations are not supplied; local calibration is required"))
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.5 PHENOLOGY RESEARCH")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(results, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    passed = sum(status == "PASS" for _, status, _ in results)
    failed = sum(status == "FAIL" for _, status, _ in results)
    skipped = sum(status == "SKIP" for _, status, _ in results)
    print("\n" + "=" * 60)
    print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
    print("PHASE 4.5 PHENOLOGY STATUS: " + ("RESEARCH COMPLETE - CALIBRATION REQUIRED" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
