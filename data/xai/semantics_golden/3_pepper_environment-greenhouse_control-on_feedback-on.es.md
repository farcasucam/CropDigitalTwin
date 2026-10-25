# pepper greenhouse on on

## Contexto
- El estado del sistema no se conoce en esta ventana; no se aplican umbrales por etapa [observado] [F:835d47d1e5]

## Estado actual
- temperature_c es estable en 9 tramos (en total 207 muestras) entre las muestras 0 y 239 [observado] [F:a88ca3b80b]
- temperature_c baja entre las muestras 91 y 96 un neto de 0,713 degC (-0,119 degC/h) [observado] [F:6bb0d09964]
- temperature_c sube entre las muestras 104 y 114 un neto de 0,631 degC (0,0574 degC/h) [observado] [F:97839affa6]
- temperature_c baja entre las muestras 121 y 130 un neto de 0,522 degC (-0,0522 degC/h) [observado] [F:9296c2bc67]
- temperature_c sube entre las muestras 188 y 193 un neto de 0,474 degC (0,0791 degC/h) [observado] [F:1208b56e4b]
- vpd_kpa es estable en 8 tramos (en total 228 muestras) entre las muestras 0 y 239 [observado] [F:4bd6de6bd1]
- vpd_kpa sube entre las muestras 55 y 60 un neto de 0,197 kPa (0,0329 kPa/h) [observado] [F:afffe76a6f]
- vpd_kpa baja entre las muestras 103 y 108 un neto de 0,206 kPa (-0,0344 kPa/h) [observado] [F:c2f9fb4ab6]
- soil_water_vwc_m3_m3: el paquete de dominio no define umbral, no se supone ninguno [observado] [F:590cb66f99]
- temperature_c: el paquete de dominio no define umbral, no se supone ninguno [observado] [F:c8c8a7d98c]
- vpd_kpa: el paquete de dominio no define umbral, no se supone ninguno [observado] [F:1de0a46bc6]

## Cambios detectados
- temperature_c sube en la muestra 43 0,539 degC (jump, 3,78 sigmas de ruido) [observado] [F:140186b430]
- temperature_c tiene 5 cambios pequeños más entre las muestras 50 y 216, el mayor de 0,407 degC; no se listan uno a uno [observado] [F:eaf4b15fb3]
- temperature_c baja en la muestra 91 0,836 degC (jump, 5,85 sigmas de ruido) [observado] [F:4898cefe8a]
- temperature_c sube en la muestra 97 0,832 degC (jump, 5,83 sigmas de ruido) [observado] [F:089c106fd5]
- temperature_c baja en la muestra 115 0,863 degC (jump, 6,05 sigmas de ruido) [observado] [F:75a5423d19]
- temperature_c sube en la muestra 121 1,05 degC (jump, 7,38 sigmas de ruido) [observado] [F:cb3690f8eb]
- temperature_c baja en la muestra 188 0,516 degC (jump, 3,62 sigmas de ruido) [observado] [F:2939a4ba3c]
- temperature_c sube en la muestra 194 0,781 degC (jump, 5,47 sigmas de ruido) [observado] [F:d353c22ac8]
- vpd_kpa tiene 8 cambios pequeños más entre las muestras 13 y 218, el mayor de 0,0653 kPa; no se listan uno a uno [observado] [F:c2f6e3e187]
- vpd_kpa sube en la muestra 109 0,0898 kPa (jump, 3,44 sigmas de ruido) [observado] [F:ee4eac5810]
- greenhouse_cooling_kw entre las muestras 0 y 239: 0 encendidos, 0 h encendido, integral 0 kWh (ON por encima de 19,4, device rating, provisional 5 percent convention of xai_variable_roles.json) [observado] [F:f985262ac0]
- greenhouse_heating_kw entre las muestras 0 y 239: 10 encendidos, 57 h encendido, integral 1389 kWh (ON por encima de 6,48, device rating, provisional 5 percent convention of xai_variable_roles.json) [observado] [F:f3c32cd6bb]
- greenhouse_heating_kw se enciende en la muestra 3 (por encima de 6,48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observado] [F:7d909c760a]
- greenhouse_heating_kw se enciende en la muestra 26 (por encima de 6,48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observado] [F:2fd7ccbd96]
- greenhouse_heating_kw se enciende en la muestra 51 (por encima de 6,48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observado] [F:38ea7ba06e]
- greenhouse_heating_kw se enciende en la muestra 74 (por encima de 6,48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observado] [F:8207d913ee]
- greenhouse_heating_kw se enciende en la muestra 97 (por encima de 6,48 kW, device rating, provisional 5 percent convention of xai_variable_roles.json) [observado] [F:735603b56e]

## Previsión
- lagged-ridge/l1-2-3-24 prevé temperature_c entre 13,2 y 23,9 degC desde la muestra 120 hasta la 167, terminando en 16,2 degC [estimado por el modelo] [F:295b5e288e]
- temperature_c: el intervalo nominal del 80 % del modelo va de 12,1 a 26,1 degC; no calibrado [estimado por el modelo] [F:5f4487642a]

## Qué pasaría si
- nada que informar

## Calidad del dato
- 16 series son constantes en la ventana: accumulated_stress, biomass_fruit_g_m2, cold_stress, crop_stage, frost_damage, greenhouse_cooling_kw, greenhouse_shading_fraction, heat_stress, irrigation_mm, outdoor_rain_rate_mm_h, precipitation_mm, radiation_stress, root_zone_water_mm, soil_water_vwc_m3_m3, vpd_stress, water_stress [observado] [F:4911b62c83]
