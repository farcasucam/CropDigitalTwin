"""Generate the deterministic Phase 5.1 parameter audit report."""

from pathlib import Path

from agri_twin.domain import ParameterRegistry


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    audit = ParameterRegistry.from_repository(ROOT).write_report(ROOT / "docs" / "parameter_audit_report.md")
    errors = audit.validate()
    print(f"parameters={len(audit.records)}")
    print(f"errors={len(errors)}")
    print(f"scientific_debt={len(audit.scientific_debt)}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())