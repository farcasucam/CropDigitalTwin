from datetime import datetime, timedelta, timezone
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.weather import WeatherConfiguration, WeatherEventType, WeatherPerturbation

def check_radiation_limits():
    engine = WeatherEngine(WeatherConfiguration())
    base_date = datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)
    
    test_times = [
        "05:00:00",
        "05:59:59",
        "06:00:00",
        "18:00:00",
        "18:00:01",
        "23:00:00"
    ]
    
    print("--- 1. VERIFICACIÓN DE RADIACIÓN EXACTAMENTE 0.0 ---")
    for t_str in test_times:
        h, m, s = map(int, t_str.split(':'))
        t = datetime(2026, 8, 27, h, m, s, tzinfo=timezone.utc)
        state = engine.generate(t)
        print(f"Time: {t.isoformat()} -> Radiation: {state.solar_radiation_w_m2} W/m²")
        assert state.solar_radiation_w_m2 == 0.0, f"Error: Radiation is {state.solar_radiation_w_m2} at {t_str}, expected exactly 0.0"
        
    print("\n--- 2. VERIFICACIÓN DE ANOMALÍA RADIATION_MULTIPLIER = 2 EN T0 DIURNO ---")
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    
    # Obtener baseline
    baseline_state = engine.generate(t0)
    baseline_rad = baseline_state.solar_radiation_w_m2
    print(f"T0 ({t0.isoformat()}) Baseline Radiation: {baseline_rad} W/m²")
    assert baseline_rad > 0.0, "La radiación baseline en T0 (12:00) debería ser mayor que 0"
    
    # Crear perturbación
    radiation_anomaly = WeatherPerturbation(
        event_id="rad-anomaly-001",
        event_type=WeatherEventType.RADIATION, # o el tipo que use la aplicación para anomalías de radiación
        start_time=t0 - timedelta(hours=1),
        end_time=t0 + timedelta(hours=1),
        priority=10,
        source="manual-test",
        parameters={
            "radiation_multiplier": 2.0,
        }
    )
    
    engine.add_perturbation(radiation_anomaly)
    perturbed_state = engine.generate(t0)
    perturbed_rad = perturbed_state.solar_radiation_w_m2
    print(f"T0 ({t0.isoformat()}) Perturbed Radiation: {perturbed_rad} W/m²")
    
    expected_rad = baseline_rad * 2.0
    print(f"Expected: {expected_rad} W/m²")
    assert abs(perturbed_rad - expected_rad) < 1e-9, f"Error: Perturbed radiation {perturbed_rad} is not exactly double of baseline {baseline_rad}"
    print("¡Verificación de anomalía completada con éxito!")

if __name__ == '__main__':
    check_radiation_limits()
