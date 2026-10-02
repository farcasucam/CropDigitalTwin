"""Offline delivery verification for Phase 5.34: chilling model policy, STRICT
fallback and canonical configuration.

Checks DEFAULT == STRICT, the DYNAMIC and UTAH STRICT fallback to CHILLING_HOURS,
canonical JSON round trip, deterministic hashes, no mutation and Phase 5.33
compatibility; builds the artifact twice and requires byte-identical JSON. No
network, no external data. Exit code 0 only if every software check passes.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

from agri_twin.application.chilling_policy import ChillingPolicySuite, request
from agri_twin.domain.phenology import ChillingModelType, canonicalize_dormancy_configuration, parse_dormancy_configuration_json

ROOT = Path(__file__).resolve().parent


def main() -> int:
    checks: list[tuple[str, bool]] = []
    default, strict = (canonicalize_dormancy_configuration(request("CHILLING_HOURS", policy)) for policy in ("DEFAULT", "STRICT"))
    checks.append(("A DEFAULT == STRICT (object, JSON, hashes)", default == strict and default.to_json() == strict.to_json() and default.configuration_hash == strict.configuration_hash))
    for model in ("DYNAMIC", "UTAH"):
        config = canonicalize_dormancy_configuration(request(model, "STRICT"))
        print(f"{model}: {config.to_json()}")
        checks.append((f"B {model} -> CHILLING_HOURS under STRICT, request kept",
                       config.effective_chilling_model is ChillingModelType.CHILLING_HOURS and config.fallback_applied and config.requested_chilling_model.value == model
                       and config.effective_hash == strict.effective_hash and config.configuration_hash != strict.configuration_hash))
    dynamic = canonicalize_dormancy_configuration(request("DYNAMIC", "DEFAULT"))
    checks.append(("C canonical JSON round trip", parse_dormancy_configuration_json(dynamic.to_json()) == dynamic and parse_dormancy_configuration_json(dynamic.to_json()).to_json() == dynamic.to_json()))

    suite = ChillingPolicySuite(ROOT)
    first = suite.build_report()
    second = ChillingPolicySuite(ROOT).build_report()
    payload = first.to_dict()
    with tempfile.TemporaryDirectory() as scratch:
        a, _ = suite.write_report(first, Path(scratch) / "a")
        b, _ = suite.write_report(second, Path(scratch) / "b")
        sha_a, sha_b = hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest()
    checks.append(("D artifact JSON byte-identical across two builds", first.to_json() == second.to_json() and sha_a == sha_b))
    checks.append(("E configuration hash identical across builds", payload["configuration_hash"] == second.to_dict()["configuration_hash"]))
    checks.append(("F no mutation (registry, parameter sets, profiles, weather, requests)", payload["parameter_mutation_result"]["status"] == "PASS"))
    checks.append(("G Phase 5.33 compatibility (artifact rows and full twin)", all(section["status"] == "PASS" for section in payload["regression_result"].values()) and len(payload["regression_result"]) == 2))

    print("\nFallback matrix")
    print("| Requested model | Fallback | Effective model | Fallback applied |")
    for row in payload["fallback_matrix"]:
        print(f"| {row['requested_model']} | {row['fallback']} | {row['effective_model']} | {str(row['fallback_applied']).lower()} |")
    print("| Policy | Canonical policy |")
    for row in payload["policy_matrix"]:
        print(f"| {row['policy']} | {row['canonical_policy']} |")
    print(f"\nsections: {payload['section_status']}")
    report_path, readme_path = suite.write_report(first)
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()}")
    print(f"configuration_hash={payload['configuration_hash']} report_hash={payload['report_hash']} artifact_sha256={hashlib.sha256(report_path.read_bytes()).hexdigest()}")
    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    software_ok = payload["status"] == "PASS" and all(passed for _, passed in checks)
    print("SOFTWARE CHECKS: " + ("PASS" if software_ok else "FAIL"))
    print("SCIENTIFIC STATUS:")
    for line in payload["scientific_status"]:
        print(f"  {line}")
    return 0 if software_ok else 1


if __name__ == "__main__":
    sys.exit(main())
