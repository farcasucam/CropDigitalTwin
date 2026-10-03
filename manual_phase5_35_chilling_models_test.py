"""Offline delivery verification for Phase 5.35: Utah and Dynamic chilling models.

Checks the twelve required items (Chilling Hours, Utah, Dynamic, STRICT fallback,
canonical configuration, round trip, determinism, checkpoint/restart, unit
incompatibilities, absence of scientific evidence, no mutation, Phase 5.34
compatibility), builds the artifact twice and requires byte-identical JSON. No
network and no external data. Ends with PASS only if every software check passes.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

from agri_twin.application.chilling_models_framework import ChillingModelsSuite, request
from agri_twin.domain.phenology import PhenologyError, canonicalize_dormancy_configuration, parse_dormancy_configuration_json

ROOT = Path(__file__).resolve().parent


def main() -> int:
    suite = ChillingModelsSuite(ROOT)
    first = suite.build_report()
    second = ChillingModelsSuite(ROOT).build_report()
    payload, again = first.to_dict(), second.to_dict()
    results, software = payload["results"], payload["software_result"]

    unit_errors = []
    for model, unit in (("UTAH", "chill_hours"), ("DYNAMIC", "chill_hours"), ("UTAH", "chill_portions")):
        try:
            canonicalize_dormancy_configuration(request(model, requirement={"value": 10.0, "unit": unit, "evidence": "SOFTWARE_TEST_ONLY"}))
            unit_errors.append(None)
        except PhenologyError as exc:
            unit_errors.append(str(exc))
    dynamic = canonicalize_dormancy_configuration(request("DYNAMIC", requirement={"value": 50.0, "unit": "chill_portions", "evidence": "SOFTWARE_TEST_ONLY"}))

    with tempfile.TemporaryDirectory() as scratch:
        a, _ = suite.write_report(first, Path(scratch) / "a")
        b, _ = suite.write_report(second, Path(scratch) / "b")
        sha_a, sha_b = hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest()

    analytical = results["analytical_cases"]
    checks = [
        ("1 CHILLING_HOURS limits, accumulation and 5.34 identity", analytical["chilling_hours"]["passed"] and results["twin_integration"]["chilling_hours_identical_to_phase534"]),
        ("2 UTAH published table, shape, units", analytical["utah"]["passed"] and software["seasons"]["units_never_reported_as_hours"]),
        ("3 DYNAMIC reference loop, closed form, irreversibility", analytical["dynamic"]["passed"]),
        ("4 STRICT fallback (unparameterized -> CHILLING_HOURS, request kept, injected MODEL_NOT_READY)", software["fallback_matrix"]["status"] == "PASS" and software["seasons"]["fallback_rows_identical_to_chilling_hours"]),
        ("5 canonical configuration and hash separation", software["configurations"]["status"] == "PASS"),
        ("6 round trip", all(row["round_trip"] for row in software["configurations"]["rows"]) and parse_dormancy_configuration_json(dynamic.to_json()) == dynamic),
        ("7 determinism (two builds: JSON, configuration/effective/report hash, SHA-256)", first.to_json() == second.to_json() and sha_a == sha_b
         and (payload["configuration_hash"], payload["effective_hash"], payload["report_hash"]) == (again["configuration_hash"], again["effective_hash"], again["report_hash"])),
        ("8 checkpoint / restart through JSON", results["checkpoint_restart"]["status"] == "PASS"),
        ("9 unit incompatibilities rejected", all(error is not None and "expects" in error and "received" in error for error in unit_errors)),
        ("10 no activated scientific evidence, no claims", payload["evidence"]["activated_requirement_rows"] == [] and payload["scientific_claims"] == [] and software["readiness_matrix"]["status"] == "PASS"),
        ("11 no mutation (registry, parameter sets, profiles, weather, configurations, constants)", software["parameter_mutation"]["status"] == "PASS"),
        ("12 Phase 5.34 / 5.33 compatibility (hashes, artifact rows, twin)", results["phase534_hash_preservation"]["status"] == "PASS" and results["regression_533"]["status"] == "PASS"
         and results["twin_integration"]["status"] == "PASS"),
    ]
    print("Models")
    for row in payload["models"]["rows"]:
        print(f"  {row['model']:<15} unit={row['unit']:<17} implemented={row['implemented']} status={row['status_without_requirement']} scientifically_active=False")
    print("Fallback")
    for row in payload["fallback_matrix"]:
        print(f"  {row['case']:<36} requested={row['requested_model']:<15} effective={row['effective_model']:<15} fallback_applied={row['fallback_applied']} reason={row['fallback_reason']}")
    for error in unit_errors:
        print(f"  unit error: {error}")
    print(f"Dynamic reference: per-hour identical={analytical['dynamic']['per_hour_identical_to_reference_transcription']} 6C/1000h={analytical['dynamic']['constant_6c_1000h_cp']:.4f} CP 20C/1000h={analytical['dynamic']['constant_20c_1000h_cp']} CP")
    print(f"sections: {payload['section_status']}")
    report_path, readme_path = suite.write_report(first)
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()}")
    print(f"configuration_hash={payload['configuration_hash']}\neffective_hash={payload['effective_hash']}\nreport_hash={payload['report_hash']}\nartifact_sha256={hashlib.sha256(report_path.read_bytes()).hexdigest()}")
    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    software_ok = payload["status"] == "PASS" and all(passed for _, passed in checks)
    print("SCIENTIFIC STATUS:")
    for line in payload["scientific_status"]:
        print(f"  {line}")
    print("PASS" if software_ok else "FAIL")
    return 0 if software_ok else 1


if __name__ == "__main__":
    sys.exit(main())
