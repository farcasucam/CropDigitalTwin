import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from agri_twin.contracts import MessageEnvelope


def test_envelope_serializes_to_the_versioned_schema() -> None:
    envelope = MessageEnvelope(
        simulation_id="sim-001",
        plot_id="plot-001",
        simulation_time="2026-08-27T08:00:00",
        type="weather",
        source="weather-engine",
        data={"temperature_c": 31.2},
    )
    schema_path = Path("schemas/message-envelope-1.0.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(envelope.to_dict())


def test_envelope_rejects_unknown_schema_version() -> None:
    try:
        MessageEnvelope(
            simulation_id="sim-001", plot_id="plot-001", simulation_time="t", type="weather",
            source="test", data={}, schema_version="2.0"
        )
    except ValueError as exc:
        assert "Unsupported schema version" in str(exc)
    else:
        raise AssertionError("An unsupported version must be rejected")


def test_all_documented_phase_zero_schemas_are_valid_json_schemas() -> None:
    for schema_path in Path("schemas").glob("*-1.0.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)