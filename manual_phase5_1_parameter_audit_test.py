"""Offline delivery audit for Phase 5.1 parameter traceability."""

from __future__ import annotations

from pathlib import Path

from agri_twin.domain import ParameterRegistry


ROOT = Path(__file__).resolve().parent
EXPECTED_CROPS = {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    registry = ParameterRegistry.from_repository(ROOT)
    audit = registry.audit()
    records = audit.records
    crops = {record.crop for record in records if record.crop}
    evidence = registry.get("evidence.tomato_tbase_001")
    require(len(records) > 100, "registry is unexpectedly incomplete")
    require(EXPECTED_CROPS <= crops, "seven crops are not represented")
    require(evidence.source_type == "literature" and evidence.source_reference, "literature traceability is missing")
    require(any(record.source_type == "engineering_default" for record in records), "engineering defaults are not identified")
    require(audit.summary["calibration_candidates"] > 0, "calibration candidates are not reported")
    require(not audit.validate(), "registry validation failed: " + "; ".join(audit.validate()))
    report = ROOT / "docs" / "parameter_audit_report.md"
    registry.write_report(report)
    require(report.is_file() and "Scientific debt" in report.read_text(encoding="utf-8"), "audit report was not generated")
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 5.1 PARAMETER AUDIT")
    print("=" * 60)
    print(f"[01] Registry exists and loads.............. PASS  {len(records)} records")
    print(f"[02] Seven crops represented................ PASS  {', '.join(sorted(crops & EXPECTED_CROPS))}")
    print("[03] Literature traceability................. PASS  tomato Tbase evidence retained")
    print("[04] Engineering defaults classified........ PASS  not scientific validation")
    print(f"[05] Scientific debt and candidates.......... PASS  {len(audit.scientific_debt)} records")
    print("[06] Deterministic validation/report......... PASS  report generated")
    print("\nPHASE 5.1 STATUS: AUDIT READY - NOT SCIENTIFICALLY VALIDATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())