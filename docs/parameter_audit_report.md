# Parameter Audit Report

## Summary

- `total_parameters`: 526
- `literature_parameters`: 35
- `project_data_parameters`: 8
- `measured_parameters`: 0
- `derived_parameters`: 0
- `engineering_defaults`: 16
- `unknown_parameters`: 467
- `calibrated_parameters`: 0
- `calibration_candidates`: 522

## By crop

- `apple`: 70 parameters
- `grape`: 72 parameters
- `lettuce`: 68 parameters
- `peach`: 68 parameters
- `pepper`: 69 parameters
- `plum`: 72 parameters
- `tomato`: 72 parameters

## Scientific debt

| ID | Name | Source | Evidence | Status | Scope | Notes |
|---|---|---|---|---|---|---|
| actuator.co2.capacity | co2 capacity | unknown | none | candidate_for_calibration | global |  |
| actuator.cooling.capacity | cooling capacity | unknown | none | candidate_for_calibration | global |  |
| actuator.heating.capacity | heating capacity | unknown | none | candidate_for_calibration | global |  |
| actuator.hvac.capacity | hvac capacity | unknown | none | candidate_for_calibration | global |  |
| actuator.irrigation.capacity | irrigation capacity | unknown | none | candidate_for_calibration | global |  |
| actuator.misting.capacity | misting capacity | unknown | none | candidate_for_calibration | global |  |
| actuator.shading.capacity | shading capacity | unknown | none | candidate_for_calibration | global |  |
| actuator.ventilation.capacity | ventilation capacity | unknown | none | candidate_for_calibration | global |  |
| contract.biomass_partitioning | biomass_partitioning | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.chilling_requirement | chilling_requirement | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.gdd_to_next_stage | gdd_to_next_stage | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.lai_max | lai_max | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.maturity_response | maturity_response | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.radiation_response | radiation_response | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.root_depth_m | root_depth_m | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.rue | rue | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.thermal_base_temperature_c | thermal_base_temperature_c | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.thermal_upper_temperature_c | thermal_upper_temperature_c | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| contract.vpd_response | vpd_response | unknown | none | candidate_for_calibration | global | contract currently has no operational default |
| crop.apple.establishment.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.establishment.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | apple/establishment | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.post_harvest_dormancy.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | apple/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.vegetative_growth.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | apple/vegetative_growth | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.apple.yield_maturation.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | apple/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.establishment.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.establishment.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | grape/establishment | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.post_harvest_dormancy.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | grape/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.vegetative_growth.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | grape/vegetative_growth | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.grape.yield_maturation.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | grape/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.establishment.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | lettuce/establishment | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.post_harvest_dormancy.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | lettuce/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.vegetative_growth.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | lettuce/vegetative_growth | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.lettuce.yield_maturation.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | lettuce/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.establishment.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.establishment.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | peach/establishment | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.post_harvest_dormancy.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | peach/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.vegetative_growth.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | peach/vegetative_growth | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.peach.yield_maturation.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | peach/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.establishment.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.establishment.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | pepper/establishment | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.post_harvest_dormancy.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | pepper/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.vegetative_growth.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | pepper/vegetative_growth | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.pepper.yield_maturation.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | pepper/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.establishment.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.establishment.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | plum/establishment | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.post_harvest_dormancy.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | plum/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.vegetative_growth.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | plum/vegetative_growth | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.plum.yield_maturation.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | plum/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.establishment.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.establishment.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | tomato/establishment | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.post_harvest_dormancy.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | tomato/post_harvest_dormancy | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.vegetative_growth.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | tomato/vegetative_growth | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.irrigation.preventive_hours_before_peak | preventive_hours_before_peak | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.irrigation.shading_reduction_pct | shading_reduction_pct | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.irrigation.target_vwc_after_irrigation | target_vwc_after_irrigation | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.solar_radiation_thresholds.optimal_max_w_m2 | optimal_max_w_m2 | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.solar_radiation_thresholds.photoinhibition_w_m2 | photoinhibition_w_m2 | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.stress_thresholds.critical_frost_c | critical_frost_c | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.stress_thresholds.critical_heat_c | critical_heat_c | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.stress_thresholds.max_temp_c | max_temp_c | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.stress_thresholds.min_temp_c | min_temp_c | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.vpd_thresholds.optimal_max_kpa | optimal_max_kpa | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.vpd_thresholds.optimal_min_kpa | optimal_min_kpa | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.vpd_thresholds.stress_max_kpa | stress_max_kpa | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.vwc_thresholds.field_capacity | field_capacity | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.vwc_thresholds.moderate_min | moderate_min | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.vwc_thresholds.optimal_min | optimal_min | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| crop.tomato.yield_maturation.vwc_thresholds.wilting_point | wilting_point | unknown | none | candidate_for_calibration | tomato/yield_maturation | crop stage thresholds have no source metadata |
| evidence.apple_chill_portions_001 | chill_portions | literature | high | candidate_for_calibration | apple/Golden Delicious; Granny Smith; Gala; Fuji | external event endodormancy_release; evidence retained; not activated |
| evidence.apple_chill_portions_002 | chill_portions | literature | high | candidate_for_calibration | apple/12 apple cultivars | external event endodormancy_release; evidence retained; not activated |
| evidence.apple_flowering_001 | GDD | literature | high | candidate_for_calibration | apple/cultivars unspecified | external event flowering; evidence retained; not activated |
| evidence.apple_flowering_002 | GDD | literature | high | candidate_for_calibration | apple/cultivars unspecified | external event flowering; evidence retained; not activated |
| evidence.apple_forcing_001 | GDH | literature | high | candidate_for_calibration | apple/Cox Orange to Gala | external event flowering; evidence retained; not activated |
| evidence.apple_forcing_002 | GDH | literature | high | candidate_for_calibration | apple/12 apple cultivars | external event flowering; evidence retained; not activated |
| evidence.grape_budburst_001 | GDD | literature | high | candidate_for_calibration | grape/Treixadura | external event budburst; evidence retained; not activated |
| evidence.grape_flowering_001 | GDD | literature | high | candidate_for_calibration | grape/Godello | external event flowering; evidence retained; not activated |
| evidence.grape_harvest_001 | GDD | literature | high | candidate_for_calibration | grape/Red Globe; Superior Seedless | external event harvest; evidence retained; not activated |
| evidence.grape_tbase_001 | Tbase | literature | high | candidate_for_calibration | grape/Treixadura | external event budburst; evidence retained; not activated |
| evidence.grape_tbase_002 | Tbase | literature | high | candidate_for_calibration | grape/Godello | external event flowering; evidence retained; not activated |
| evidence.grape_tbase_003 | Tbase | literature | high | candidate_for_calibration | grape | external event flowering; evidence retained; not activated |
| evidence.lettuce_tbase_001 | Tbase | literature | high | candidate_for_calibration | lettuce | external event not mapped; evidence retained; not activated |
| evidence.lettuce_tbase_002 | Tbase | literature | medium | candidate_for_calibration | lettuce | external event not mapped; evidence retained; not activated |
| evidence.lettuce_tbase_003 | Tbase | literature | medium | candidate_for_calibration | lettuce | external event not mapped; evidence retained; not activated |
| evidence.lettuce_tupper_001 | Tupper | literature | high | candidate_for_calibration | lettuce | external event not mapped; evidence retained; not activated |
| evidence.peach_chill_hours_001 | chill_hours | literature | high | candidate_for_calibration | peach/14 peach and nectarine cultivars | external event endodormancy_release; evidence retained; not activated |
| evidence.peach_chill_hours_002 | chill_hours | literature | high | candidate_for_calibration | peach/15 cultivars | external event endodormancy_release; evidence retained; not activated |
| evidence.peach_chill_portions_001 | chill_portions | literature | high | candidate_for_calibration | peach/14 peach and nectarine cultivars | external event endodormancy_release; evidence retained; not activated |
| evidence.peach_forcing_001 | GDH | literature | high | candidate_for_calibration | peach/14 peach and nectarine cultivars | external event flowering; evidence retained; not activated |
| evidence.pepper_tbase_001 | Tbase | literature | high | candidate_for_calibration | pepper/bell pepper, unspecified | external event not mapped; evidence retained; not activated |
| evidence.pepper_tbase_002 | Tbase | literature | medium | candidate_for_calibration | pepper | external event not mapped; evidence retained; not activated |
| evidence.pepper_tbase_003 | Tbase | literature | medium | candidate_for_calibration | pepper | external event not mapped; evidence retained; not activated |
| evidence.plum_chill_hours_001 | chill_hours | literature | high | candidate_for_calibration | plum/21 Japanese plum-type cultivars | external event endodormancy_release; evidence retained; not activated |
| evidence.plum_chill_hours_002 | chill_hours | literature | high | candidate_for_calibration | plum/8 Japanese plum-type cultivars | external event endodormancy_release; evidence retained; not activated |
| evidence.plum_chill_portions_001 | chill_portions | literature | high | candidate_for_calibration | plum/21 Japanese plum-type cultivars | external event endodormancy_release; evidence retained; not activated |
| evidence.plum_chill_portions_002 | chill_portions | literature | high | candidate_for_calibration | plum/Earliqueen | external event endodormancy_release; evidence retained; not activated |
| evidence.plum_forcing_001 | GDH | literature | high | candidate_for_calibration | plum/21 Japanese plum-type cultivars | external event flowering; evidence retained; not activated |
| evidence.plum_forcing_002 | GDH | literature | high | candidate_for_calibration | plum/Ambra | external event flowering; evidence retained; not activated |
| evidence.tomato_maturity_001 | GDD | literature | high | candidate_for_calibration | tomato | external event maturity; evidence retained; not activated |
| evidence.tomato_tbase_001 | Tbase | literature | high | candidate_for_calibration | tomato | external event not mapped; evidence retained; not activated |
| evidence.tomato_tbase_002 | Tbase | literature | high | candidate_for_calibration | tomato | external event not mapped; evidence retained; not activated |
| evidence.tomato_tbase_003 | Tbase | literature | medium | candidate_for_calibration | tomato/varieties unspecified | external event transplant; evidence retained; not activated |
| evidence.tomato_tupper_001 | Tupper | literature | high | candidate_for_calibration | tomato | external event not mapped; evidence retained; not activated |
| evidence.tomato_tupper_002 | Tupper | literature | high | candidate_for_calibration | tomato | external event not mapped; evidence retained; not activated |
| greenhouse.cover_transmission | default greenhouse transmission | engineering_default | none | candidate_for_calibration | global | must not be presented as biological validation |
| greenhouse.outdoor.solar_transmission_fraction | solar_transmission_fraction | engineering_default | none | candidate_for_calibration | global |  |
| plot.plot_12010.area_ha | plot area | project_data | none | not_applicable | tomato/RAF |  |
| plot.plot_12010.soil_type | soil type | project_data | none | candidate_for_calibration | tomato/RAF |  |
| plot.plot_14705.area_ha | plot area | project_data | none | not_applicable | plum/Suplum 26 |  |
| plot.plot_14705.soil_type | soil type | project_data | none | candidate_for_calibration | plum/Suplum 26 |  |
| plot.plot_30412.area_ha | plot area | project_data | none | not_applicable | grape/Monastrell |  |
| plot.plot_30412.soil_type | soil type | project_data | none | candidate_for_calibration | grape/Monastrell |  |
| plot.plot_40811.area_ha | plot area | project_data | none | not_applicable | pepper/Lamuyo |  |
| plot.plot_40811.soil_type | soil type | project_data | none | candidate_for_calibration | pepper/Lamuyo |  |
| radiation.extinction_coefficient | Beer-Lambert extinction coefficient | engineering_default | none | candidate_for_calibration | global | must not be presented as biological validation |
| radiation.par_fraction | PAR fraction of shortwave | engineering_default | none | candidate_for_calibration | global | must not be presented as biological validation |
| radiation.rue | radiation use efficiency | engineering_default | none | candidate_for_calibration | global | must not be presented as biological validation |
| radiation.sla | specific leaf area | engineering_default | none | candidate_for_calibration | global | must not be presented as biological validation |
| soil.calcareous_loam.available_water_capacity_mm_m | available_water_capacity_mm_m | engineering_default | none | candidate_for_calibration | global |  |
| soil.calcareous_loam.field_capacity_vwc | field_capacity_vwc | engineering_default | none | candidate_for_calibration | global |  |
| soil.calcareous_loam.wilting_point_vwc | wilting_point_vwc | engineering_default | none | candidate_for_calibration | global |  |
| soil.clay_loam.available_water_capacity_mm_m | available_water_capacity_mm_m | engineering_default | none | candidate_for_calibration | global |  |
| soil.clay_loam.field_capacity_vwc | field_capacity_vwc | engineering_default | none | candidate_for_calibration | global |  |
| soil.clay_loam.wilting_point_vwc | wilting_point_vwc | engineering_default | none | candidate_for_calibration | global |  |
| soil.sandy_loam.available_water_capacity_mm_m | available_water_capacity_mm_m | engineering_default | none | candidate_for_calibration | global |  |
| soil.sandy_loam.field_capacity_vwc | field_capacity_vwc | engineering_default | none | candidate_for_calibration | global |  |
| soil.sandy_loam.wilting_point_vwc | wilting_point_vwc | engineering_default | none | candidate_for_calibration | global |  |
| water.et_temperature_range | ET approximation temperature range | engineering_default | none | candidate_for_calibration | global | must not be presented as biological validation |

## Validation

- status: PASS
- errors: none
