from datetime import datetime, timedelta, timezone

from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.weather import (
    HumidityConfiguration,
    PressureConfiguration,
    RadiationConfiguration,
    TemperatureConfiguration,
    WeatherConfiguration,
    WeatherSimulationConfiguration,
    WindConfiguration,
)


def build_configuration() -> WeatherConfiguration:
    return WeatherConfiguration(
        temperature=TemperatureConfiguration(
            minimum_c=12.0,
            maximum_c=30.0,
            minimum_hour=5.0,
            maximum_hour=15.0,
            variability_c=0.5,
        ),
        radiation=RadiationConfiguration(
            maximum_w_m2=900.0,
            sunrise_hour=6.0,
            sunset_hour=18.0,
            variability_w_m2=15.0,
        ),
        humidity=HumidityConfiguration(
            minimum_pct=35.0,
            maximum_pct=90.0,
            variability_pct=2.0,
        ),
        wind=WindConfiguration(
            base_speed_m_s=2.0,
            variability_m_s=0.5,
            base_direction_deg=180.0,
            direction_variability_deg=20.0,
        ),
        pressure=PressureConfiguration(
            base_hpa=1013.0,
            variability_hpa=4.0,
        ),
        simulation=WeatherSimulationConfiguration(
            seed=42,
            publication_interval_seconds=60,
        ),
    )


def print_state(simulation_time, state):
    print(
        f"{simulation_time.isoformat():25} "
        f"T={state.temperature_c:6.2f} °C  "
        f"RH={state.relative_humidity_pct:6.2f} %  "
        f"RAD={state.solar_radiation_w_m2:7.2f} W/m²  "
        f"WIND={state.wind_speed_m_s:5.2f} m/s  "
        f"DIR={state.wind_direction_deg:6.2f}°  "
        f"RAIN={state.rain_rate_mm_h:5.2f} mm/h  "
        f"P={state.pressure_hpa:7.2f} hPa"
    )


def main():
    configuration = build_configuration()
    engine = WeatherEngine(configuration)

    start = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)

    # ------------------------------------------------------------
    # 1. EVOLUCIÓN METEOROLÓGICA
    # ------------------------------------------------------------

    print("=" * 150)
    print("1. EVOLUCIÓN METEOROLÓGICA - 24 HORAS")
    print("=" * 150)

    states = {}

    for hour in range(24):
        simulation_time = start + timedelta(hours=hour)
        state = engine.generate(simulation_time)
        states[simulation_time] = state
        print_state(simulation_time, state)

    # ------------------------------------------------------------
    # 2. DETERMINISMO
    # ------------------------------------------------------------

    print()
    print("=" * 150)
    print("2. DETERMINISMO")
    print("=" * 150)

    t = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    state_a = engine.generate(t)
    state_b = engine.generate(t)

    print("Primer resultado :")
    print(state_a)

    print()
    print("Segundo resultado:")
    print(state_b)

    print()
    print(f"¿Son idénticos? : {state_a == state_b}")

    assert state_a == state_b

    # ------------------------------------------------------------
    # 3. INDEPENDENCIA DEL HISTORIAL
    # ------------------------------------------------------------

    print()
    print("=" * 150)
    print("3. INDEPENDENCIA DEL HISTORIAL")
    print("=" * 150)

    t1 = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)

    first_pass = {
        t1: engine.generate(t1),
        t2: engine.generate(t2),
        t3: engine.generate(t3),
    }

    engine.reset()

    second_pass = {
        t3: engine.generate(t3),
        t1: engine.generate(t1),
        t2: engine.generate(t2),
    }

    for simulation_time in (t1, t2, t3):
        same = first_pass[simulation_time] == second_pass[simulation_time]

        print(
            f"{simulation_time.isoformat()} -> "
            f"{'OK' if same else 'ERROR'}"
        )

        assert same

    print()
    print("OK: el resultado no depende del orden ni del historial de llamadas.")

    # ------------------------------------------------------------
    # 4. RESUMEN
    # ------------------------------------------------------------

    print()
    print("=" * 150)
    print("PRUEBA COMPLETADA")
    print("=" * 150)
    print()
    print("✓ WeatherEngine responde")
    print("✓ 24 horas generadas")
    print("✓ Determinismo verificado")
    print("✓ Independencia del historial verificada")
    print("✓ Reset verificado indirectamente")


if __name__ == "__main__":
    main()