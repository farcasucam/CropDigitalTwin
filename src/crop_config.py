import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CropStageConfig:
    stage_name: str = ""
    months: List[str] = field(default_factory=list)
    stress_thresholds: Dict[str, float] = field(default_factory=dict)
    vpd_thresholds: Dict[str, float] = field(default_factory=dict)
    vwc_thresholds: Dict[str, float] = field(default_factory=dict)
    solar_radiation_thresholds: Dict[str, float] = field(default_factory=dict)
    irrigation: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CropConfig:
    crop_type: str = "Tomato (Solanaceae)"
    location: str = "Smart Greenhouse / Open Field"
    stages: Dict[str, CropStageConfig] = field(default_factory=dict)

    def __post_init__(self):
        """Convierte diccionarios crudos de etapas a objetos CropStageConfig automáticamente."""
        formatted_stages = {}
        for stage_key, stage_val in self.stages.items():
            if isinstance(stage_val, dict):
                formatted_stages[stage_key] = CropStageConfig(**stage_val)
            elif isinstance(stage_val, CropStageConfig):
                formatted_stages[stage_key] = stage_val
            else:
                formatted_stages[stage_key] = stage_val
        self.stages = formatted_stages

    def get_stage(self, stage_key: str) -> Optional[CropStageConfig]:
        """Obtiene la configuración de una etapa fenológica específica."""
        return self.stages.get(stage_key.lower())

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_CROP_LIBRARY: Dict[str, CropConfig] = {
    "tomato": CropConfig(
        crop_type="Tomato (Solanaceae - Solanum lycopersicum)",
        location="Smart Greenhouse / Open Field",
        stages={
            "establishment": CropStageConfig(
                stage_name="Establishment & Rooting",
                months=["March", "April"],
                stress_thresholds={"min_temp_c": 14.0, "max_temp_c": 28.0, "critical_heat_c": 32.0, "critical_frost_c": 2.0},
                vpd_thresholds={"optimal_min_kpa": 0.5, "optimal_max_kpa": 1.0, "stress_max_kpa": 1.4},
                vwc_thresholds={"field_capacity": 0.32, "optimal_min": 0.24, "moderate_min": 0.18, "wilting_point": 0.10},
                solar_radiation_thresholds={"optimal_max_w_m2": 650.0, "photoinhibition_w_m2": 800.0},
                irrigation={"preventive_hours_before_peak": 2, "shading_reduction_pct": 20, "target_vwc_after_irrigation": 0.30},
            ),
            "vegetative_growth": CropStageConfig(
                stage_name="Vegetative Growth & Flowering",
                months=["May", "June"],
                stress_thresholds={"min_temp_c": 12.0, "max_temp_c": 30.0, "critical_heat_c": 34.0, "critical_frost_c": 0.0},
                vpd_thresholds={"optimal_min_kpa": 0.7, "optimal_max_kpa": 1.2, "stress_max_kpa": 1.6},
                vwc_thresholds={"field_capacity": 0.32, "optimal_min": 0.22, "moderate_min": 0.16, "wilting_point": 0.10},
                solar_radiation_thresholds={"optimal_max_w_m2": 800.0, "photoinhibition_w_m2": 900.0},
                irrigation={"preventive_hours_before_peak": 3, "shading_reduction_pct": 25, "target_vwc_after_irrigation": 0.30},
            ),
            "yield_maturation": CropStageConfig(
                stage_name="Fruit Sizing & Ripening",
                months=["July", "August", "September"],
                stress_thresholds={"min_temp_c": 12.0, "max_temp_c": 32.0, "critical_heat_c": 35.0, "critical_frost_c": 0.0},
                vpd_thresholds={"optimal_min_kpa": 0.8, "optimal_max_kpa": 1.3, "stress_max_kpa": 1.8},
                vwc_thresholds={"field_capacity": 0.32, "optimal_min": 0.22, "moderate_min": 0.16, "wilting_point": 0.10},
                solar_radiation_thresholds={"optimal_max_w_m2": 850.0, "photoinhibition_w_m2": 950.0},
                irrigation={"preventive_hours_before_peak": 4, "shading_reduction_pct": 30, "target_vwc_after_irrigation": 0.30},
            ),
            "post_harvest_dormancy": CropStageConfig(
                stage_name="Final Harvest & Senescence",
                months=["October", "November"],
                stress_thresholds={"min_temp_c": 8.0, "max_temp_c": 25.0, "critical_heat_c": 30.0, "critical_frost_c": -1.0},
                vpd_thresholds={"optimal_min_kpa": 0.5, "optimal_max_kpa": 1.1, "stress_max_kpa": 1.5},
                vwc_thresholds={"field_capacity": 0.32, "optimal_min": 0.18, "moderate_min": 0.14, "wilting_point": 0.10},
                solar_radiation_thresholds={"optimal_max_w_m2": 600.0, "photoinhibition_w_m2": 750.0},
                irrigation={"preventive_hours_before_peak": 2, "shading_reduction_pct": 0, "target_vwc_after_irrigation": 0.26},
            ),
        },
    )
}

CROP_LIBRARY: Dict[str, CropConfig] = DEFAULT_CROP_LIBRARY.copy()


def _default_config_path() -> str:
    return os.path.join(os.path.dirname(__file__), "crop_config.json")


def load_json_crop_library(config_path: Optional[str] = None) -> Dict[str, CropConfig]:
    path = config_path or _default_config_path()
    if not os.path.exists(path):
        return CROP_LIBRARY.copy()

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise ValueError("El JSON de cultivos debe contener un objeto con la clave 'crops'.")

    crops_payload = payload.get("crops", payload)
    library: Dict[str, CropConfig] = {}
    for key, value in crops_payload.items():
        if isinstance(value, CropConfig):
            library[key.lower()] = value
        elif isinstance(value, dict):
            library[key.lower()] = CropConfig(**value)
        else:
            raise TypeError(f"Configuración de cultivo inválida para '{key}': {value!r}")

    return library or DEFAULT_CROP_LIBRARY.copy()


def normalize_crop_config(config: Optional[Any] = None, config_path: Optional[str] = None) -> CropConfig:
    if config is None:
        return get_crop_config("tomato", config_path=config_path)
    if isinstance(config, CropConfig):
        return config
    if isinstance(config, dict):
        return CropConfig(**config)
    if isinstance(config, str):
        return get_crop_config(config, config_path=config_path)
    raise TypeError("config debe ser None, CropConfig, dict o nombre de cultivo")


def get_crop_config(crop_key: str = "tomato", config_path: Optional[str] = None, **overrides) -> CropConfig:
    key = (crop_key or "tomato").strip().lower()
    library = load_json_crop_library(config_path)
    default_crop = library.get("tomato") or list(library.values())[0] if library else DEFAULT_CROP_LIBRARY["tomato"]
    base = library.get(key, default_crop)
    
    config_dict = base.to_dict()
    config_dict.update(overrides)
    return CropConfig(**config_dict)


def resolve_crop_config(config: Optional[Any] = None, config_path: Optional[str] = None) -> CropConfig:
    return normalize_crop_config(config, config_path=config_path)


def save_crop_library(config_path: Optional[str] = None, library: Optional[Dict[str, CropConfig]] = None) -> str:
    resolved_path = config_path or _default_config_path()
    data = {"default_crop": "tomato", "crops": {}}
    crop_library = library or CROP_LIBRARY
    for key, value in crop_library.items():
        data["crops"][key] = value.to_dict()

    os.makedirs(os.path.dirname(resolved_path) or ".", exist_ok=True)
    with open(resolved_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return resolved_path