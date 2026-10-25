# tomato outdoor off

## Context
- State of the system: establishment (from crop_config.json) [observed] [F:ad07c33aef]

## Current state
- temperature_c is stable in 11 stretches (together 213 samples) between samples 0 and 239 [observed] [F:6c1cc6957e]
- temperature_c falls from sample 28 to 33 by 1.13 degC net (-0.188 degC/h) [observed] [F:c8115fb47b]
- temperature_c falls from sample 34 to 39 by 1.14 degC net (-0.191 degC/h) [observed] [F:287bf48eca]
- temperature_c falls from sample 40 to 45 by 1.15 degC net (-0.192 degC/h) [observed] [F:81ab568ad2]
- temperature_c rises from sample 207 to 215 by 0.763 degC net (0.0848 degC/h) [observed] [F:7b6b2eec4d]
- vpd_kpa is stable in 11 stretches (together 225 samples) between samples 0 and 239 [observed] [F:a17f4f255c]
- vpd_kpa falls from sample 24 to 32 by 0.0564 kPa net (-0.00627 kPa/h) [observed] [F:ab84350556]
- vpd_kpa falls from sample 42 to 47 by 0.0692 kPa net (-0.0115 kPa/h) [observed] [F:787c677681]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) in 11 runs between samples 0 and 239, 133 h in total, most extreme 5.34 degC; only the longest runs are listed [observed] [F:ee5de46b2b]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) from sample 45 to 58, lowest 5.88 degC, 14 h [observed] [F:df2048225a]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) from sample 93 to 107, lowest 5.67 degC, 15 h [observed] [F:007ead50ed]
- temperature_c falls below 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) from sample 117 to 130, lowest 5.83 degC, 14 h [observed] [F:0ecd4dfb8a]

## Changes detected
- temperature_c shifts up at sample 22 by 2.45 degC (jump, 10.3 noise sigmas) [observed] [F:e49d3849bb]
- temperature_c shifts down at sample 28 by 0.877 degC (jump, 3.7 noise sigmas) [observed] [F:89ed250193]
- temperature_c shifts down at sample 34 by 1.15 degC (jump, 4.85 noise sigmas) [observed] [F:2718ebafc0]
- temperature_c shifts down at sample 40 by 1.14 degC (jump, 4.81 noise sigmas) [observed] [F:7fe99aacc7]
- temperature_c shifts up at sample 46 by 0.901 degC (jump, 3.8 noise sigmas) [observed] [F:8b1bfc57b9]
- temperature_c shifts up at sample 70 by 1.04 degC (jump, 4.39 noise sigmas) [observed] [F:e203732e0b]
- temperature_c has 6 further small shifts between samples 79 and 216, the largest 0.694 degC; not listed one by one [observed] [F:7a13427410]
- temperature_c shifts down at sample 85 by 0.82 degC (jump, 3.46 noise sigmas) [observed] [F:95c9ca2c19]
- temperature_c shifts up at sample 207 by 0.744 degC (jump, 3.14 noise sigmas) [observed] [F:825a75a1d5]
- vpd_kpa shifts up at sample 24 by 0.0608 kPa (jump, 4.06 noise sigmas) [observed] [F:a2d8331d75]
- vpd_kpa shifts down at sample 33 by 0.0673 kPa (jump, 4.5 noise sigmas) [observed] [F:9ad955a306]
- vpd_kpa has 8 further small shifts between samples 42 and 216, the largest 0.0425 kPa; not listed one by one [observed] [F:9728ae8aaf]
- vpd_kpa shifts down at sample 81 by 0.0474 kPa (jump, 3.17 noise sigmas) [observed] [F:d95649f9d6]
- vpd_kpa shifts up at sample 164 by 0.0579 kPa (jump, 3.87 noise sigmas) [observed] [F:3cff825843]

## Forecast
- lagged-ridge/l1-2-3-24 forecasts temperature_c between 7.34 and 17.2 degC from sample 120 to 167, ending at 10.8 degC [model estimate] [F:02b8dd827e]
- temperature_c: the model's nominal 80 % interval spans 6.91 to 18 degC; not calibrated [model estimate] [F:425fb8d4ce]

## What if
- nothing to report

## Data quality
- 11 series are constant over the window: biomass_fruit_g_m2, crop_stage, frost_damage, heat_stress, irrigation_mm, precipitation_mm, radiation_stress, root_zone_water_mm, soil_water_vwc_m3_m3, vpd_stress, water_stress [observed] [F:7029614251]
