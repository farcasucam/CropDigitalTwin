# pepper greenhouse on on

## Context
- The state of the system is not known for this window; stage thresholds are not applied [observed] [F:835d47d1e5]

## Current state
- temperature_c is stable in 9 stretches (together 207 samples) between samples 0 and 239 [observed] [F:a88ca3b80b]
- temperature_c falls from sample 91 to 96 by 0.713 degC net (-0.119 degC/h) [observed] [F:6bb0d09964]
- temperature_c rises from sample 104 to 114 by 0.631 degC net (0.0574 degC/h) [observed] [F:97839affa6]
- temperature_c falls from sample 121 to 130 by 0.522 degC net (-0.0522 degC/h) [observed] [F:9296c2bc67]
- temperature_c rises from sample 188 to 193 by 0.474 degC net (0.0791 degC/h) [observed] [F:1208b56e4b]
- vpd_kpa is stable in 8 stretches (together 228 samples) between samples 0 and 239 [observed] [F:4bd6de6bd1]
- vpd_kpa rises from sample 55 to 60 by 0.197 kPa net (0.0329 kPa/h) [observed] [F:afffe76a6f]
- vpd_kpa falls from sample 103 to 108 by 0.206 kPa net (-0.0344 kPa/h) [observed] [F:c2f9fb4ab6]
- soil_water_vwc_m3_m3: the domain pack defines no threshold, none is assumed [observed] [F:590cb66f99]
- temperature_c: the domain pack defines no threshold, none is assumed [observed] [F:c8c8a7d98c]
- vpd_kpa: the domain pack defines no threshold, none is assumed [observed] [F:1de0a46bc6]

## Changes detected
- temperature_c shifts up at sample 43 by 0.539 degC (jump, 3.78 noise sigmas) [observed] [F:140186b430]
- temperature_c has 5 further small shifts between samples 50 and 216, the largest 0.407 degC; not listed one by one [observed] [F:eaf4b15fb3]
- temperature_c shifts down at sample 91 by 0.836 degC (jump, 5.85 noise sigmas) [observed] [F:4898cefe8a]
- temperature_c shifts up at sample 97 by 0.832 degC (jump, 5.83 noise sigmas) [observed] [F:089c106fd5]
- temperature_c shifts down at sample 115 by 0.863 degC (jump, 6.05 noise sigmas) [observed] [F:75a5423d19]
- temperature_c shifts up at sample 121 by 1.05 degC (jump, 7.38 noise sigmas) [observed] [F:cb3690f8eb]
- temperature_c shifts down at sample 188 by 0.516 degC (jump, 3.62 noise sigmas) [observed] [F:2939a4ba3c]
- temperature_c shifts up at sample 194 by 0.781 degC (jump, 5.47 noise sigmas) [observed] [F:d353c22ac8]
- vpd_kpa has 8 further small shifts between samples 13 and 218, the largest 0.0653 kPa; not listed one by one [observed] [F:c2f6e3e187]
- vpd_kpa shifts up at sample 109 by 0.0898 kPa (jump, 3.44 noise sigmas) [observed] [F:ee4eac5810]
- greenhouse_cooling_kw over samples 0 to 239: 0 onsets, 0 h on, integral 0 kWh (ON above 19.4, device rating, provisional 5 percent convention of xai_variable_roles.json) [observed] [F:f985262ac0]
- greenhouse_heating_kw over samples 0 to 239: 10 onsets, 57 h on, integral 1389 kWh (ON above 6.48, device rating, provisional 5 percent convention of xai_variable_roles.json) [observed] [F:f3c32cd6bb]
- greenhouse_heating_kw switches on at sample 3 (above 6.48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observed] [F:7d909c760a]
- greenhouse_heating_kw switches on at sample 26 (above 6.48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observed] [F:2fd7ccbd96]
- greenhouse_heating_kw switches on at sample 51 (above 6.48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observed] [F:38ea7ba06e]
- greenhouse_heating_kw switches on at sample 74 (above 6.48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observed] [F:8207d913ee]
- greenhouse_heating_kw switches on at sample 97 (above 6.48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observed] [F:735603b56e]

## Forecast
- lagged-ridge/l1-2-3-24 forecasts temperature_c between 13.2 and 23.9 degC from sample 120 to 167, ending at 16.2 degC [model estimate] [F:295b5e288e]
- temperature_c: the model's nominal 80 % interval spans 12.1 to 26.1 degC; not calibrated [model estimate] [F:5f4487642a]

## What if
- nothing to report

## Data quality
- 16 series are constant over the window: accumulated_stress, biomass_fruit_g_m2, cold_stress, crop_stage, frost_damage, greenhouse_cooling_kw, greenhouse_shading_fraction, heat_stress, irrigation_mm, outdoor_rain_rate_mm_h, precipitation_mm, radiation_stress, root_zone_water_mm, soil_water_vwc_m3_m3, vpd_stress, water_stress [observed] [F:4911b62c83]
