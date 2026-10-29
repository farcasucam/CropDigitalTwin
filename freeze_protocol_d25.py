"""Check and freeze the confirmatory protocol D25 (src/xai_protocol_d25.json and docs/xai/PROTOCOL_D25.md).

    python -u freeze_protocol_d25.py            # check: partitions, exposure register, open parameters; writes nothing
    python -u freeze_protocol_d25.py --freeze   # only when the check is clean and no pilot_fixed entry is null: writes data/xai/protocol_d25_freeze.json

The freeze record holds the hashes of the protocol, its document, the benchmark design, the variable roles and the declared graph (text normalised to LF), the test partitions as computed from the salt, the exposure register, and the
git heads of both repositories. After it exists, tests/test_protocol_d25.py fails when any of those files changes: a later change is a dated deviation in the document, not an edit. Nothing here runs a confirmatory experiment.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from tsxai.bench.rng import partition_of  # noqa: E402

PROTOCOL = ROOT / "src" / "xai_protocol_d25.json"
DOCUMENT = ROOT / "docs" / "xai" / "PROTOCOL_D25.md"
TRACKED = {"protocol": PROTOCOL, "document": DOCUMENT, "benchmark_design": ROOT / "src" / "xai_benchmark_design.json", "variable_roles": ROOT / "src" / "xai_variable_roles.json",
           "declared_graph": ROOT / "src" / "xai_declared_graph.json"}
FREEZE = ROOT / "data" / "xai" / "protocol_d25_freeze.json"
TSXAI = ROOT.parent / "tsxai"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def partitions(protocol: dict) -> dict:
    agri, tep = protocol["domains"]["agri"], protocol["domains"]["tep"]
    out = {"agri": {c: [s for s in range(agri["seasons"]) if partition_of(f"crop={c}|season={s}", agri["salt"], agri["test_share"]) == "test"] for c in agri["crops"]},
           "tep": [s for s in range(tep["seasons"]) if partition_of(f"{tep['group_label']}|season={s}", tep["salt"], tep["test_share"]) == "test"]}
    return out


def manifest_test_groups() -> dict[str, str]:
    """Every scenario of a generated bank whose split is test: group -> the bank directory (these are exposures to register)."""
    found: dict[str, str] = {}
    for manifest in sorted((ROOT / "data" / "xai").glob("*/manifest.json")):
        for scenario in json.loads(manifest.read_text(encoding="utf-8")).get("scenarios", []):
            if isinstance(scenario, dict) and scenario.get("split") == "test":
                found[scenario["group"]] = manifest.parent.name
    return found


def problems(protocol: dict) -> list[str]:
    found, parts = [], partitions(protocol)
    for entry in protocol["exposure"]["agri"]:
        if entry["season"] not in parts["agri"].get(entry["crop"], []):
            found.append(f"exposure register lists {entry['crop']} season {entry['season']}, which is not in the test partition")
    for entry in protocol["exposure"]["tep"]:
        if entry["season"] not in parts["tep"]:
            found.append(f"exposure register lists tep season {entry['season']}, which is not in the test partition")
    registered = {f"crop={e['crop']}|season={e['season']}" for e in protocol["exposure"]["agri"]}
    for group, bank in manifest_test_groups().items():
        if group not in registered:
            found.append(f"bank {bank} generated a test scenario of {group} that the exposure register does not list")
    return found


def open_parameters(protocol: dict) -> list[str]:
    return [key for key, value in protocol["pilot_fixed"].items() if value is None or (isinstance(value, dict) and any(v is None for v in value.values()))]


def git_head(path: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def record(protocol: dict) -> dict:
    return {"contract": "xai_protocol_d25_freeze", "protocol_version": protocol["version"], "hashes": {name: file_hash(path) for name, path in TRACKED.items()}, "partitions": partitions(protocol),
            "exposure": protocol["exposure"], "git_heads": {"CropDigitalTwin": git_head(ROOT), "tsxai": git_head(TSXAI)}, "tep_commit": protocol["tep_source"]["commit"]}


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    parts, issues, open_ = partitions(protocol), problems(protocol), open_parameters(protocol)
    print("test partitions:", json.dumps(parts))
    print("problems:", issues or "none")
    print("open pilot_fixed parameters:", open_ or "none")
    if "--freeze" in sys.argv:
        if issues or open_:
            print("REFUSED: the check is not clean or parameters are still open")
            return 1
        FREEZE.write_text(json.dumps(record(protocol), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("frozen:", FREEZE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
