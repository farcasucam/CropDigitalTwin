# tomato outdoor off

## Contexto
- Estado del sistema: establishment (según crop_config.json) [observado] [F:ad07c33aef]

## Estado actual
- temperature_c es estable en 11 tramos (en total 213 muestras) entre las muestras 0 y 239 [observado] [F:6c1cc6957e]
- temperature_c baja entre las muestras 28 y 33 un neto de 1,13 degC (-0,188 degC/h) [observado] [F:c8115fb47b]
- temperature_c baja entre las muestras 34 y 39 un neto de 1,14 degC (-0,191 degC/h) [observado] [F:287bf48eca]
- temperature_c baja entre las muestras 40 y 45 un neto de 1,15 degC (-0,192 degC/h) [observado] [F:81ab568ad2]
- temperature_c sube entre las muestras 207 y 215 un neto de 0,763 degC (0,0848 degC/h) [observado] [F:7b6b2eec4d]
- vpd_kpa es estable en 11 tramos (en total 225 muestras) entre las muestras 0 y 239 [observado] [F:a17f4f255c]
- vpd_kpa baja entre las muestras 24 y 32 un neto de 0,0564 kPa (-0,00627 kPa/h) [observado] [F:ab84350556]
- vpd_kpa baja entre las muestras 42 y 47 un neto de 0,0692 kPa (-0,0115 kPa/h) [observado] [F:787c677681]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) en 11 tramos entre las muestras 0 y 239, 133 h en total, el más extremo 5,34 degC; solo se listan los más largos [observado] [F:ee5de46b2b]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) entre las muestras 45 y 58, mínimo 5,88 degC, 14 h [observado] [F:df2048225a]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) entre las muestras 93 y 107, mínimo 5,67 degC, 15 h [observado] [F:007ead50ed]
- temperature_c cae por debajo de 14 degC (crop_config.json tomato/establishment/stress_thresholds.min_temp_c) entre las muestras 117 y 130, mínimo 5,83 degC, 14 h [observado] [F:0ecd4dfb8a]

## Cambios detectados
- temperature_c sube en la muestra 22 2,45 degC (jump, 10,3 sigmas de ruido) [observado] [F:e49d3849bb]
- temperature_c baja en la muestra 28 0,877 degC (jump, 3,7 sigmas de ruido) [observado] [F:89ed250193]
- temperature_c baja en la muestra 34 1,15 degC (jump, 4,85 sigmas de ruido) [observado] [F:2718ebafc0]
- temperature_c baja en la muestra 40 1,14 degC (jump, 4,81 sigmas de ruido) [observado] [F:7fe99aacc7]
- temperature_c sube en la muestra 46 0,901 degC (jump, 3,8 sigmas de ruido) [observado] [F:8b1bfc57b9]
- temperature_c sube en la muestra 70 1,04 degC (jump, 4,39 sigmas de ruido) [observado] [F:e203732e0b]
- temperature_c tiene 6 cambios pequeños más entre las muestras 79 y 216, el mayor de 0,694 degC; no se listan uno a uno [observado] [F:7a13427410]
- temperature_c baja en la muestra 85 0,82 degC (jump, 3,46 sigmas de ruido) [observado] [F:95c9ca2c19]
- temperature_c sube en la muestra 207 0,744 degC (jump, 3,14 sigmas de ruido) [observado] [F:825a75a1d5]
- vpd_kpa sube en la muestra 24 0,0608 kPa (jump, 4,06 sigmas de ruido) [observado] [F:a2d8331d75]
- vpd_kpa baja en la muestra 33 0,0673 kPa (jump, 4,5 sigmas de ruido) [observado] [F:9ad955a306]
- vpd_kpa tiene 8 cambios pequeños más entre las muestras 42 y 216, el mayor de 0,0425 kPa; no se listan uno a uno [observado] [F:9728ae8aaf]
- vpd_kpa baja en la muestra 81 0,0474 kPa (jump, 3,17 sigmas de ruido) [observado] [F:d95649f9d6]
- vpd_kpa sube en la muestra 164 0,0579 kPa (jump, 3,87 sigmas de ruido) [observado] [F:3cff825843]

## Previsión
- lagged-ridge/l1-2-3-24 prevé temperature_c entre 7,34 y 17,2 degC desde la muestra 120 hasta la 167, terminando en 10,8 degC [estimado por el modelo] [F:02b8dd827e]
- temperature_c: el intervalo nominal del 80 % del modelo va de 6,91 a 18 degC; no calibrado [estimado por el modelo] [F:425fb8d4ce]

## Qué pasaría si
- nada que informar

## Calidad del dato
- 11 series son constantes en la ventana: biomass_fruit_g_m2, crop_stage, frost_damage, heat_stress, irrigation_mm, precipitation_mm, radiation_stress, root_zone_water_mm, soil_water_vwc_m3_m3, vpd_stress, water_stress [observado] [F:7029614251]
