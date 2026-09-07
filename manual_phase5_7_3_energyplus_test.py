"""Manual Phase 5.7.3 diagnostic; never fakes EnergyPlus availability."""

from agri_twin.infrastructure.energyplus_greenhouse import EnergyPlusGreenhouseModel, detect_energyplus


def main() -> int:
    availability = detect_energyplus()
    print(f"status: {availability.status.value}")
    print(f"version: {availability.version or 'not detected'}")
    print(f"executable: {availability.executable or 'not detected'}")
    print(f"idd: {availability.idd or 'not detected'}")
    print(f"python_api: {availability.python_api}")
    print(f"detail: {availability.detail or 'ready'}")
    model = EnergyPlusGreenhouseModel(availability=availability)
    if availability.status.value != "AVAILABLE":
        print("backend remains explicit and non-operational; no simulation was faked")
        return 0
    print("EnergyPlus is available; configure an IDF variant, EPW, and run the integration-specific command before executing this manual check.")
    print(f"backend status: {model.availability.status.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
