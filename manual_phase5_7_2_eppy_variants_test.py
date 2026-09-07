"""Manual Phase 5.7.2 audit for optional eppy greenhouse variants."""

from pathlib import Path
import tempfile

from agri_twin.infrastructure.eppy_greenhouse import EppyGreenhouseBuilder, EppyStatus


ROOT = Path(__file__).resolve().parent


def main() -> int:
    original = (ROOT / "templates" / "greenhouse" / "greenhouse_template.idf").read_bytes()
    builder = EppyGreenhouseBuilder(output_dir=Path(tempfile.mkdtemp(prefix="phase5_7_2_")))
    state = builder.status()
    print(f"eppy status: {state.status.value} ({state.detail or 'ready'})")
    if state.status is not EppyStatus.AVAILABLE:
        print("manual generation skipped: install the optional eppy extra and provide ENERGYPLUS_IDD")
        return 0

    baseline = builder.build("baseline")
    high_ventilation = builder.build("high_ventilation")
    shaded = builder.build("shading")
    print(f"baseline: {baseline.generated_idf_path}")
    print(f"high ventilation: {high_ventilation.generated_idf_path}")
    print(f"shading: {shaded.generated_idf_path}")
    print(f"baseline differs from high ventilation: {baseline.generated_idf_path.read_bytes() != high_ventilation.generated_idf_path.read_bytes()}")
    print(f"baseline differs from shading: {baseline.generated_idf_path.read_bytes() != shaded.generated_idf_path.read_bytes()}")
    print(f"template preserved: {(ROOT / 'templates' / 'greenhouse' / 'greenhouse_template.idf').read_bytes() == original}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
