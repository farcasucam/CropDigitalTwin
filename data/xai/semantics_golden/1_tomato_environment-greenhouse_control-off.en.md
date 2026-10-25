# tomato greenhouse off

## Context
- State of the system: establishment (from crop_config.json) [observed] [F:ad07c33aef]

## Current state
- temperature_c is stable in 12 stretches (together 228 samples) between samples 0 and 239 [observed] [F:9ec2e16ba4]
- temperature_c rises from sample 83 to 88 by 3.04 degC net (0.507 degC/h) [observed] [F:022a6b545b]
- temperature_c rises from sample 155 to 160 by 5.38 degC net (0.897 degC/h) [observed] [F:981e3b441a]
- vpd_kpa is stable in 8 stretches (together 201 samples) between samples 0 and 239 [observed] [F:2c05d0c6d7]
- vpd_kpa falls from sample 31 to 36 by 0.963 kPa net (-0.16 kPa/h) [observed] [F:151a26d091]
- vpd_kpa falls from sample 55 to 60 by 0.965 kPa net (-0.161 kPa/h) [observed] [F:fd14372578]
- vpd_kpa rises from sample 82 to 87 by 0.25 kPa net (0.0417 kPa/h) [observed] [F:58b591c0e4]
- vpd_kpa falls from sample 133 to 138 by 0.623 kPa net (-0.104 kPa/h) [observed] [F:7cf3fd019d]
- vpd_kpa falls from sample 139 to 145 by 0.207 kPa net (-0.0295 kPa/h) [observed] [F:9bce184bf7]
- vpd_kpa rises from sample 146 to 153 by 0.252 kPa net (0.0314 kPa/h) [observed] [F:e10234d069]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) from sample 0 to 8, lowest 12 degC, 9 h [observed] [F:82055693b4]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) in 9 runs between samples 0 and 224, 78 h in total, most extreme 12 degC; only the longest runs are listed [observed] [F:1e9673ff51]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) from sample 48 to 56, lowest 12 degC, 9 h [observed] [F:b045c2dfce]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) from sample 96 to 104, lowest 12 degC, 9 h [observed] [F:8b5b85dafd]
- vpd_kpa exceeds 1.4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) from sample 11 to 12, peak 1.8 kPa, 2 h [observed] [F:5ded0dfb24]
- vpd_kpa exceeds 1.4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) in 11 runs between samples 11 and 227, 30 h in total, most extreme 1.96 kPa; only the longest runs are listed [observed] [F:b3098004e5]
- vpd_kpa exceeds 1.4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) from sample 131 to 139, peak 1.87 kPa, 9 h [observed] [F:c07ba71a77]
- vpd_kpa exceeds 1.4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) from sample 152 to 155, peak 1.96 kPa, 4 h [observed] [F:5990689ec9]

## Changes detected
- temperature_c has 9 further small shifts between samples 24 and 205, the largest 1.09 degC; not listed one by one [observed] [F:1ccb6fecbd]
- temperature_c shifts up at sample 133 by 6.5 degC, coinciding with the event HEAT_WAVE; a coincidence, not a cause [associated] [F:052a116954]
- temperature_c shifts down at sample 147 by 1.41 degC (jump, 3.69 noise sigmas) [observed] [F:746fe6f37f]
- temperature_c shifts down at sample 155 by 6.38 degC (jump, 16.7 noise sigmas) [observed] [F:549a111255]
- temperature_c shifts up at sample 161 by 1.79 degC (jump, 4.7 noise sigmas) [observed] [F:7b3f0aea0e]
- vpd_kpa has 2 further small shifts between samples 9 and 177, the largest 0.0681 kPa; not listed one by one [observed] [F:30ac76d69f]
- vpd_kpa shifts down at sample 31 by 0.173 kPa (jump, 4.03 noise sigmas) [observed] [F:bf0dc5d5d5]
- vpd_kpa shifts up at sample 37 by 0.202 kPa (jump, 4.7 noise sigmas) [observed] [F:98f228cb68]
- vpd_kpa shifts down at sample 55 by 0.184 kPa (jump, 4.28 noise sigmas) [observed] [F:15ae840577]
- vpd_kpa shifts up at sample 61 by 0.2 kPa (jump, 4.65 noise sigmas) [observed] [F:2ab9779788]
- vpd_kpa shifts down at sample 82 by 0.254 kPa (jump, 5.93 noise sigmas) [observed] [F:62885cae94]
- vpd_kpa shifts up at sample 88 by 0.211 kPa (jump, 4.92 noise sigmas) [observed] [F:69b5a08bff]
- vpd_kpa shifts up at sample 133 by 1.2 kPa, coinciding with the event HEAT_WAVE; a coincidence, not a cause [associated] [F:8d39e2a19d]
- vpd_kpa shifts down at sample 139 by 0.307 kPa (jump, 7.16 noise sigmas) [observed] [F:3e46208c79]
- vpd_kpa shifts down at sample 146 by 0.32 kPa (jump, 7.45 noise sigmas) [observed] [F:4bfb16510f]
- vpd_kpa shifts down at sample 154 by 0.668 kPa (jump, 15.6 noise sigmas) [observed] [F:e6a001615d]
- vpd_kpa shifts up at sample 160 by 0.143 kPa (jump, 3.34 noise sigmas) [observed] [F:2252ca2b06]

## Forecast
- lagged-ridge/l1-2-3-24 forecasts temperature_c between 11.3 and 30.8 degC from sample 120 to 167, ending at 16 degC [model estimate] [F:9eff4038d4]
- temperature_c: the model's nominal 80 % interval spans 9.54 to 33.5 degC; not calibrated [model estimate] [F:f3f1b75431]

## What if
- The model estimates that the heat wave changes temperature_c by up to 10.6 degC; no simulator check [model estimate] [F:52ee27404f]

## Data quality
- 15 series are constant over the window: biomass_fruit_g_m2, co2_ppm, cold_stress, crop_stage, frost_damage, greenhouse_cooling_kw, greenhouse_shading_fraction, heat_stress, irrigation_mm, outdoor_rain_rate_mm_h, precipitation_mm, radiation_stress, root_zone_water_mm, soil_water_vwc_m3_m3, water_stress [observed] [F:95f7c0c958]
