"""Manual audit for the Phase 4.3 phenology configuration design."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from agri_twin.domain import CropConfigRepository, FarmConfigRepository, validate_phenology_configuration

ROOT = Path(__file__).resolve().parent
CROP_CANDIDATES = (ROOT / "config" / "crop_config.json", ROOT / "src" / "crop_config.json")
FARM_CANDIDATES = (ROOT / "config" / "farm_config.json", ROOT / "src" / "farm_config.json")
APP = ROOT / "config" / "app.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(name: str, function, results: list[tuple[str, str, str]]) -> None:
    try:
        results.append((name, "PASS", str(function() or "verified")))
    except Exception as exc:
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def existing_path(candidates):
    return next((path for path in candidates if path.is_file()), None)


def effective_crop_path():
    for path in CROP_CANDIDATES:
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload.get("crops"), dict) and payload["crops"]:
            return path
    return existing_path(CROP_CANDIDATES)


def config_check() -> str:
    crop_path = effective_crop_path()
    farm_path = existing_path(FARM_CANDIDATES)
    require(crop_path is not None and farm_path is not None and APP.is_file(), "required configuration file missing")
    crop_payload = json.loads(crop_path.read_text(encoding="utf-8"))
    require(isinstance(crop_payload.get("crops"), dict), "crop config has no crops object")
    CropConfigRepository(crop_path)
    FarmConfigRepository(farm_path)
    return f"crop={crop_path.relative_to(ROOT)}, farm={farm_path.relative_to(ROOT)}"


def phenology_audit() -> str:
    crop_path = effective_crop_path()
    payload = json.loads(crop_path.read_text(encoding="utf-8"))
    missing = {"base_temperature_c", "gdd_to_next", "gdd_accumulated", "duration", "transition_threshold", "entry_rule", "exit_rule"}
    found = set()
    for crop in payload["crops"].values():
        for stage in crop["stages"].values():
            found |= missing.intersection(stage)
    require(not found, f"unexpected active phenology fields found: {sorted(found)}")
    return "no GDD or transition values are active; current stage order is JSON insertion order"


def schema_audit() -> str:
    validate_phenology_configuration(None)
    valid = {"method": "gdd", "base_temperature_c": None, "stages": [{"stage_key": "establishment", "gdd_to_next": None}]}
    validate_phenology_configuration(valid)
    try:
        validate_phenology_configuration({"method": "gdd", "base_temperature_c": None, "stages": [{"stage_key": "establishment", "gdd_to_next": None}, {"stage_key": "establishment", "gdd_to_next": None}]})
    except ValueError:
        return "optional schema accepts null agronomic values and rejects duplicates"
    raise AssertionError("duplicate stages accepted")


def future_metadata_audit() -> str:
    validate_phenology_configuration({
        "method": "gdd",
        "base_temperature_c": None,
        "upper_temperature_c": None,
        "biofix": None,
        "calibration_status": "CALIBRATION_REQUIRED",
        "source": {"reference": "method-reference", "type": "technical_reference"},
        "stages": [{"stage_key": "establishment", "gdd_to_next": None}],
    })
    return "future parameters support source traceability and calibration status"


def references_check() -> str:
    farm = FarmConfigRepository(existing_path(FARM_CANDIDATES))
    crops = CropConfigRepository(effective_crop_path())
    for plot in farm.plots:
        crops.resolve_stage(plot.crop_key, plot.current_stage)
    return f"{len(farm.plots)} Farm -> Crop -> Stage references valid"


def no_http_or_mutation() -> str:
    before = hashlib.sha256(APP.read_bytes()).hexdigest()
    forbidden = ("requests", "httpx", "aiohttp", "urllib", "urlopen")
    for path in (ROOT / "src" / "agri_twin" / "domain").rglob("*.py"):
        require(not any(token in path.read_text(encoding="utf-8") for token in forbidden), f"HTTP reference in {path}")
    load = __import__("agri_twin.application", fromlist=["load_weather_source_configuration"])
    load.load_weather_source_configuration(APP)
    require(hashlib.sha256(APP.read_bytes()).hexdigest() == before, "app.json changed during audit")
    return "domain audit and config load performed without HTTP or app mutation"


def reproducibility_check() -> str:
    crop_path = effective_crop_path()
    first = CropConfigRepository(crop_path).crops
    second = CropConfigRepository(crop_path).crops
    require(first == second, "crop repository result is not reproducible")
    return "same JSON produces identical ordered crop/stage definitions"


def regression_check() -> str:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    require(completed.returncode == 0, completed.stdout[-500:] or completed.stderr[-500:])
    return completed.stdout.strip().splitlines()[-1]


def main() -> int:
    results: list[tuple[str, str, str]] = []
    run_check("JSON configuration", config_check, results)
    run_check("Phenology parameter audit", phenology_audit, results)
    run_check("Optional phenology schema", schema_audit, results)
    run_check("Traceability and calibration metadata", future_metadata_audit, results)
    run_check("Farm -> Crop -> Stage references", references_check, results)
    run_check("No HTTP and no app mutation", no_http_or_mutation, results)
    run_check("Reproducibility", reproducibility_check, results)
    results.append(("GDD/stage-transition activation", "SKIP", "Tbase, GDD thresholds, durations and entry/exit rules are absent; transition engine intentionally not implemented"))
    run_check("Regression", regression_check, results)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.3 CONFIG AUDIT")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(results, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    passed = sum(status == "PASS" for _, status, _ in results)
    failed = sum(status == "FAIL" for _, status, _ in results)
    skipped = sum(status == "SKIP" for _, status, _ in results)
    print("\n" + "=" * 60)
    print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
    print("PHASE 4.3 CONFIG STATUS: " + ("READY FOR AGRONOMIC DATA" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
