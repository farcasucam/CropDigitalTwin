# tomato greenhouse off

## Contexto
- Estado del sistema: establishment (según crop_config.json) [observado] [F:ad07c33aef]

## Estado actual
- temperature_c es estable en 12 tramos (en total 228 muestras) entre las muestras 0 y 239 [observado] [F:9ec2e16ba4]
- temperature_c sube entre las muestras 83 y 88 un neto de 3,04 degC (0,507 degC/h) [observado] [F:022a6b545b]
- temperature_c sube entre las muestras 155 y 160 un neto de 5,38 degC (0,897 degC/h) [observado] [F:981e3b441a]
- vpd_kpa es estable en 8 tramos (en total 201 muestras) entre las muestras 0 y 239 [observado] [F:2c05d0c6d7]
- vpd_kpa baja entre las muestras 31 y 36 un neto de 0,963 kPa (-0,16 kPa/h) [observado] [F:151a26d091]
- vpd_kpa baja entre las muestras 55 y 60 un neto de 0,965 kPa (-0,161 kPa/h) [observado] [F:fd14372578]
- vpd_kpa sube entre las muestras 82 y 87 un neto de 0,25 kPa (0,0417 kPa/h) [observado] [F:58b591c0e4]
- vpd_kpa baja entre las muestras 133 y 138 un neto de 0,623 kPa (-0,104 kPa/h) [observado] [F:7cf3fd019d]
- vpd_kpa baja entre las muestras 139 y 145 un neto de 0,207 kPa (-0,0295 kPa/h) [observado] [F:9bce184bf7]
- vpd_kpa sube entre las muestras 146 y 153 un neto de 0,252 kPa (0,0314 kPa/h) [observado] [F:e10234d069]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) entre las muestras 0 y 8, mínimo 12 degC, 9 h [observado] [F:82055693b4]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) en 9 tramos entre las muestras 0 y 224, 78 h en total, el más extremo 12 degC; solo se listan los más largos [observado] [F:1e9673ff51]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) entre las muestras 48 y 56, mínimo 12 degC, 9 h [observado] [F:b045c2dfce]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) entre las muestras 96 y 104, mínimo 12 degC, 9 h [observado] [F:8b5b85dafd]
- vpd_kpa supera 1,4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) entre las muestras 11 y 12, máximo 1,8 kPa, 2 h [observado] [F:5ded0dfb24]
- vpd_kpa supera 1,4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) en 11 tramos entre las muestras 11 y 227, 30 h en total, el más extremo 1,96 kPa; solo se listan los más largos [observado] [F:b3098004e5]
- vpd_kpa supera 1,4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) entre las muestras 131 y 139, máximo 1,87 kPa, 9 h [observado] [F:c07ba71a77]
- vpd_kpa supera 1,4 kPa (crop_config.json tomato/establishment/vpd_thresholds.stress_max_kpa) entre las muestras 152 y 155, máximo 1,96 kPa, 4 h [observado] [F:5990689ec9]

## Cambios detectados
- temperature_c tiene 9 cambios pequeños más entre las muestras 24 y 205, el mayor de 1,09 degC; no se listan uno a uno [observado] [F:1ccb6fecbd]
- temperature_c sube en la muestra 133 6,5 degC, coincidiendo con el evento HEAT_WAVE; una coincidencia, no una causa [asociado] [F:052a116954]
- temperature_c baja en la muestra 147 1,41 degC (jump, 3,69 sigmas de ruido) [observado] [F:746fe6f37f]
- temperature_c baja en la muestra 155 6,38 degC (jump, 16,7 sigmas de ruido) [observado] [F:549a111255]
- temperature_c sube en la muestra 161 1,79 degC (jump, 4,7 sigmas de ruido) [observado] [F:7b3f0aea0e]
- vpd_kpa tiene 2 cambios pequeños más entre las muestras 9 y 177, el mayor de 0,0681 kPa; no se listan uno a uno [observado] [F:30ac76d69f]
- vpd_kpa baja en la muestra 31 0,173 kPa (jump, 4,03 sigmas de ruido) [observado] [F:bf0dc5d5d5]
- vpd_kpa sube en la muestra 37 0,202 kPa (jump, 4,7 sigmas de ruido) [observado] [F:98f228cb68]
- vpd_kpa baja en la muestra 55 0,184 kPa (jump, 4,28 sigmas de ruido) [observado] [F:15ae840577]
- vpd_kpa sube en la muestra 61 0,2 kPa (jump, 4,65 sigmas de ruido) [observado] [F:2ab9779788]
- vpd_kpa baja en la muestra 82 0,254 kPa (jump, 5,93 sigmas de ruido) [observado] [F:62885cae94]
- vpd_kpa sube en la muestra 88 0,211 kPa (jump, 4,92 sigmas de ruido) [observado] [F:69b5a08bff]
- vpd_kpa sube en la muestra 133 1,2 kPa, coincidiendo con el evento HEAT_WAVE; una coincidencia, no una causa [asociado] [F:8d39e2a19d]
- vpd_kpa baja en la muestra 139 0,307 kPa (jump, 7,16 sigmas de ruido) [observado] [F:3e46208c79]
- vpd_kpa baja en la muestra 146 0,32 kPa (jump, 7,45 sigmas de ruido) [observado] [F:4bfb16510f]
- vpd_kpa baja en la muestra 154 0,668 kPa (jump, 15,6 sigmas de ruido) [observado] [F:e6a001615d]
- vpd_kpa sube en la muestra 160 0,143 kPa (jump, 3,34 sigmas de ruido) [observado] [F:2252ca2b06]

## Previsión
- lagged-ridge/l1-2-3-24 prevé temperature_c entre 11,3 y 30,8 degC desde la muestra 120 hasta la 167, terminando en 16 degC [estimado por el modelo] [F:9eff4038d4]
- temperature_c: el intervalo nominal del 80 % del modelo va de 9,54 a 33,5 degC; no calibrado [estimado por el modelo] [F:f3f1b75431]

## Qué pasaría si
- El modelo estima que the heat wave cambia temperature_c hasta 10,6 degC; sin comprobación del simulador [estimado por el modelo] [F:52ee27404f]

## Calidad del dato
- 15 series son constantes en la ventana: biomass_fruit_g_m2, co2_ppm, cold_stress, crop_stage, frost_damage, greenhouse_cooling_kw, greenhouse_shading_fraction, heat_stress, irrigation_mm, outdoor_rain_rate_mm_h, precipitation_mm, radiation_stress, root_zone_water_mm, soil_water_vwc_m3_m3, water_stress [observado] [F:95f7c0c958]
