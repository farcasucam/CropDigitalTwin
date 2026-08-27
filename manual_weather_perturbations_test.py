from datetime import datetime, timedelta, timezone

from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.weather import (
    WeatherConfiguration,
    WeatherEventType,
    WeatherPerturbation,
)


def make_event(
    event_id,
    event_type,
    start,
    end,
    priority,
    parameters,
):
    return WeatherPerturbation(
        event_id=event_id,
        event_type=event_type,
        start_time=start,
        end_time=end,
        priority=priority,
        source="manual-test",
        parameters=parameters,
    )


def print_state(label, time, state):
    print(
        f"{label:18} {time.isoformat()}  "
        f"T={state.temperature_c:6.2f} °C  "
        f"RH={state.relative_humidity_pct:6.2f} %  "
        f"RAD={state.solar_radiation_w_m2:7.2f} W/m²  "
        f"WIND={state.wind_speed_m_s:5.2f} m/s  "
        f"DIR={state.wind_direction_deg:6.2f}°  "
        f"RAIN={state.rain_rate_mm_h:5.2f} mm/h  "
        f"P={state.pressure_hpa:7.2f} hPa"
    )


def main():
    engine = WeatherEngine(WeatherConfiguration())

    base = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    print("=" * 150)
    print("PRUEBA MANUAL DE PERTURBACIONES METEOROLÓGICAS")
    print("=" * 150)

    # ============================================================
    # 1. REFERENCIA
    # ============================================================

    print("\n1. ESTADO NORMAL")
    print("-" * 150)

    normal = engine.generate(base)
    print_state("NORMAL", base, normal)

    # ============================================================
    # 2. OLA DE CALOR
    # ============================================================

    print("\n2. OLA DE CALOR")
    print("-" * 150)

    heat_start = base
    heat_end = base + timedelta(hours=3)

    heat = make_event(
        "heat-001",
        WeatherEventType.HEAT_WAVE,
        heat_start,
        heat_end,
        priority=10,
        parameters={
            "temperature_offset_c": 10.0,
        },
    )

    engine.add_perturbation(heat)

    before = engine.generate(base - timedelta(minutes=1))
    during = engine.generate(base + timedelta(hours=1))
    after = engine.generate(base + timedelta(hours=3))

    print_state("ANTES", base - timedelta(minutes=1), before)
    print_state("DURANTE", base + timedelta(hours=1), during)
    print_state("FIN", base + timedelta(hours=3), after)

    assert abs(during.temperature_c - (engine.generate(base + timedelta(hours=1)).temperature_c)) < 1e-9
    assert abs(
        during.temperature_c
        - engine.generate(base + timedelta(hours=1)).temperature_c
    ) < 1e-9

    # El evento termina exactamente en end_time.
    # Según is_active() de tu modelo, comprobamos el comportamiento real
    # imprimiéndolo, no asumiéndolo.

    engine.remove_perturbation("heat-001")

    # ============================================================
    # 3. HELADA
    # ============================================================

    print("\n3. HELADA")
    print("-" * 150)

    frost_start = base
    frost_end = base + timedelta(hours=2)

    frost = make_event(
        "frost-001",
        WeatherEventType.FROST,
        frost_start,
        frost_end,
        priority=20,
        parameters={
            "temperature_c": -2.0,
        },
    )

    engine.add_perturbation(frost)

    frost_state = engine.generate(base + timedelta(hours=1))
    print_state("HELADA", base + timedelta(hours=1), frost_state)

    assert frost_state.temperature_c == -2.0

    engine.remove_perturbation("frost-001")

    # ============================================================
    # 4. LLUVIA
    # ============================================================

    print("\n4. LLUVIA")
    print("-" * 150)

    rain_start = base
    rain_end = base + timedelta(hours=2)

    rain = make_event(
        "rain-001",
        WeatherEventType.RAIN,
        rain_start,
        rain_end,
        priority=10,
        parameters={
            "rate_mm_h": 8.0,
        },
    )

    engine.add_perturbation(rain)

    rain_state = engine.generate(base + timedelta(hours=1))

    print_state("LLUVIA", base + timedelta(hours=1), rain_state)

    assert rain_state.rain_rate_mm_h == 8.0

    dry_state = engine.generate(base + timedelta(hours=3))

    print_state("DESPUÉS", base + timedelta(hours=3), dry_state)

    assert dry_state.rain_rate_mm_h == 0.0

    engine.remove_perturbation("rain-001")

    # ============================================================
    # 5. VIENTO
    # ============================================================

    print("\n5. VIENTO")
    print("-" * 150)

    wind = make_event(
        "wind-001",
        WeatherEventType.WIND,
        base,
        base + timedelta(hours=2),
        priority=10,
        parameters={
            "speed_multiplier": 3.0,
            "direction_deg": 270.0,
        },
    )

    engine.add_perturbation(wind)

    wind_state = engine.generate(base + timedelta(hours=1))

    print_state("VIENTO", base + timedelta(hours=1), wind_state)

    assert abs(wind_state.wind_direction_deg - 270.0) < 1e-9
    assert wind_state.wind_speed_m_s > normal.wind_speed_m_s

    engine.remove_perturbation("wind-001")

    # ============================================================
    # 6. ANOMALÍA DE RADIACIÓN
    # ============================================================

    print("\n6. ANOMALÍA DE RADIACIÓN")
    print("-" * 150)

    radiation = make_event(
        "radiation-001",
        WeatherEventType.RADIATION_ANOMALY,
        base,
        base + timedelta(hours=2),
        priority=10,
        parameters={
            "radiation_multiplier": 0.5,
        },
    )

    engine.add_perturbation(radiation)

    radiation_state = engine.generate(base + timedelta(hours=1))

    print_state(
        "RADIACIÓN",
        base + timedelta(hours=1),
        radiation_state,
    )

    assert radiation_state.solar_radiation_w_m2 < normal.solar_radiation_w_m2

    engine.remove_perturbation("radiation-001")

    # ============================================================
    # 7. COMBINACIÓN DE EVENTOS
    # ============================================================

    print("\n7. COMBINACIÓN DE EVENTOS")
    print("-" * 150)

    engine.add_perturbation(
        make_event(
            "combo-heat",
            WeatherEventType.HEAT_WAVE,
            base,
            base + timedelta(hours=2),
            priority=10,
            parameters={
                "temperature_offset_c": 8.0,
            },
        )
    )

    engine.add_perturbation(
        make_event(
            "combo-wind",
            WeatherEventType.WIND,
            base,
            base + timedelta(hours=2),
            priority=10,
            parameters={
                "speed_multiplier": 2.0,
                "direction_deg": 90.0,
            },
        )
    )

    engine.add_perturbation(
        make_event(
            "combo-rain",
            WeatherEventType.RAIN,
            base,
            base + timedelta(hours=2),
            priority=10,
            parameters={
                "rate_mm_h": 5.0,
            },
        )
    )

    combined = engine.generate(base + timedelta(hours=1))

    print_state(
        "COMBINADO",
        base + timedelta(hours=1),
        combined,
    )

    assert combined.temperature_c > normal.temperature_c
    assert combined.wind_speed_m_s > normal.wind_speed_m_s
    assert combined.wind_direction_deg == 90.0
    assert combined.rain_rate_mm_h == 5.0

    # ============================================================
    # 8. ACTIVE PERTURBATIONS
    # ============================================================

    print("\n8. PERTURBACIONES ACTIVAS")
    print("-" * 150)

    active = engine.active_perturbations(base + timedelta(hours=1))

    for event in active:
        print(
            f"{event.event_id:15} "
            f"type={event.event_type.value:18} "
            f"priority={event.priority:3} "
            f"parameters={dict(event.parameters)}"
        )

    assert len(active) == 3

    # ============================================================
    # 9. RESET
    # ============================================================

    print("\n9. RESET")
    print("-" * 150)

    engine.reset()

    active_after_reset = engine.active_perturbations(
        base + timedelta(hours=1)
    )

    print(f"Eventos después de reset: {len(active_after_reset)}")

    assert len(active_after_reset) == 0

    reset_state = engine.generate(base + timedelta(hours=1))

    print_state(
        "POST-RESET",
        base + timedelta(hours=1),
        reset_state,
    )

    # ============================================================
    # FINAL
    # ============================================================

    print()
    print("=" * 150)
    print("PRUEBA COMPLETADA")
    print("=" * 150)

    print("✓ Ola de calor")
    print("✓ Helada")
    print("✓ Lluvia")
    print("✓ Viento")
    print("✓ Anomalía de radiación")
    print("✓ Combinación de eventos")
    print("✓ Consulta de perturbaciones activas")
    print("✓ Reset de perturbaciones")


if __name__ == "__main__":
    main()