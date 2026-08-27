import json
from typing import Dict, Any, List, Optional


class FarmManager:
    """Gestiona la configuración de parcelas y cruza lecturas con umbrales agronómicos."""

    def __init__(self, farm_config_path: str = "farm_config.json", crop_config_path: str = "crop_config_2.json"):
        self.farm_config_path = farm_config_path
        self.crop_config_path = crop_config_path
        self.plots: List[Dict[str, Any]] = []
        self.crops: Dict[str, Any] = {}
        self.load_configurations()

    def load_configurations(self) -> None:
        """Carga y parsea ambos archivos JSON de configuración."""
        with open(self.farm_config_path, "r", encoding="utf-8") as f:
            self.plots = json.load(f).get("plots", [])

        with open(self.crop_config_path, "r", encoding="utf-8") as f:
            self.crops = json.load(f).get("crops", {})

    def get_plot(self, plot_id: str) -> Optional[Dict[str, Any]]:
        """Busca una parcela por su identificador único."""
        return next((plot for plot in self.plots if plot["id"] == plot_id), None)

    def get_plot_active_thresholds(self, plot_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene la parcela vinculada a las métricas del cultivo en su etapa actual."""
        plot = self.get_plot(plot_id)
        if not plot:
            return None

        crop_key = plot.get("crop_key")
        current_stage = plot.get("current_stage")

        crop_info = self.crops.get(crop_key, {})
        stage_info = crop_info.get("stages", {}).get(current_stage, {})

        return {
            "plot_id": plot["id"],
            "farm_name": plot["farm_name"],
            "plot_code": plot["plot_code"],
            "crop_key": crop_key,
            "crop_type": crop_info.get("crop_type"),
            "crop_variety": plot.get("crop_variety"),
            "current_stage": current_stage,
            "stage_name": stage_info.get("stage_name"),
            "stress_thresholds": stage_info.get("stress_thresholds"),
            "vpd_thresholds": stage_info.get("vpd_thresholds"),
            "vwc_thresholds": stage_info.get("vwc_thresholds"),
            "solar_radiation_thresholds": stage_info.get("solar_radiation_thresholds"),
            "irrigation": stage_info.get("irrigation")
        }

    def evaluate_sensor_data(self, plot_id: str, temp_c: float, vwc: float, vpd_kpa: float) -> Dict[str, Any]:
        """Evalúa datos meteorológicos o de suelo frente a los umbrales activos de la parcela."""
        thresholds = self.get_plot_active_thresholds(plot_id)
        if not thresholds:
            return {"error": f"Parcela {plot_id} no encontrada."}

        alerts = []
        stress = thresholds.get("stress_thresholds", {})
        vwc_limits = thresholds.get("vwc_thresholds", {})
        vpd_limits = thresholds.get("vpd_thresholds", {})

        # Evaluación de temperatura
        if stress and temp_c >= stress.get("critical_heat_c", 99):
            alerts.append(f"CRÍTICO - Calor extremo: {temp_c}°C (Límite: {stress['critical_heat_c']}°C)")
        elif stress and temp_c > stress.get("max_temp_c", 99):
            alerts.append(f"ADVERTENCIA - Temp. alta: {temp_c}°C (Máx óptimo: {stress['max_temp_c']}°C)")

        # Evaluación de humedad de suelo (VWC)
        if vwc_limits and vwc < vwc_limits.get("wilting_point", 0):
            alerts.append(f"CRÍTICO - Punto de marchitez: VWC {vwc} (Límite: {vwc_limits['wilting_point']})")
        elif vwc_limits and vwc < vwc_limits.get("optimal_min", 0):
            alerts.append(f"RIEGO REQUERIDO - VWC {vwc} por debajo de óptimo ({vwc_limits['optimal_min']})")

        # Evaluación de déficit de presión de vapor (VPD)
        if vpd_limits and vpd_kpa > vpd_limits.get("stress_max_kpa", 99):
            alerts.append(f"ESTRÉS HÍDRICO - VPD alto: {vpd_kpa} kPa (Máx estrés: {vpd_limits['stress_max_kpa']} kPa)")

        return {
            "plot_id": plot_id,
            "farm_name": thresholds["farm_name"],
            "crop": f"{thresholds['crop_type']} ({thresholds['crop_variety']})",
            "stage": thresholds["stage_name"],
            "status": "ALERT" if alerts else "OPTIMAL",
            "alerts": alerts
        }


if __name__ == "__main__":
    # Ejemplo de uso con la parcela de ciruelo
    manager = FarmManager("farm_config.json", "crop_config_2.json")
    
    # 1. Consultar umbrales vigentes para la parcela plot_14705
    active_data = manager.get_plot_active_thresholds("plot_14705")
    print("--- Umbrales Activos de la Parcela ---")
    print(json.dumps(active_data, indent=2, ensure_ascii=False))

    # 2. Simular lectura de sensores (Temperatura: 37°C, Humedad del suelo VWC: 0.15, VPD: 2.3 kPa)
    telemetry_result = manager.evaluate_sensor_data(
        plot_id="plot_14705",
        temp_c=37.0,
        vwc=0.15,
        vpd_kpa=2.3
    )
    print("\n--- Resultado de Evaluación de Telemetría ---")
    print(json.dumps(telemetry_result, indent=2, ensure_ascii=False))