# Physical Model

## Responsabilidad

Calcular consecuencias físicas a partir de ambiente, estado y actuadores.

## MVP actual

`OpenFieldPhysicalModel` implementa la primera capacidad ejecutable de esta
fase: calcula presión de vapor de saturación, presión real, VPD, carga térmica,
transpiración estimada y un proxy de evapotranspiración. También actualiza
`SoilState` con lluvia, riego, evaporación y transpiración durante el timestep.
Es un modelo determinista y desacoplado de red. `WeatherEngine` y los providers
siguen siendo responsables de producir `WeatherState`; el modelo físico solo
consume ese estado. Los modelos de invernadero, ventilación, humedad/CO2,
actuadores y un modelo agronómico avanzado siguen pendientes.

## Submodelos

### RadiationModel

```text
indoor_radiation =
outdoor_radiation
* greenhouse_transmission
* shade_factor
```

El toldo cerrado reduce radiación.

### ThermalModel

Debe combinar:
- temperatura exterior;
- radiación;
- masa/inercia térmica;
- ventilación;
- HVAC;
- timestep.

No establecer directamente `temperature = target`.

### VentilationModel

La apertura de ventanas aumenta el intercambio con exterior y modifica:
- temperatura;
- humedad;
- CO2.

### HumidityModel

Considerar:
- humedad exterior;
- ventilación;
- temperatura;
- lluvia indirectamente;
- transpiración;
- riego.

### SoilWaterModel

Modelo simplificado:

```text
VWC_next =
    VWC
    + irrigation
    + rain_contribution
    - drainage
    - evaporation
    - transpiration
```

Debe permitir diferenciar suelos por configuración y reproducir el patrón tipo diente de sierra descrito en la documentación.

## Open field vs greenhouse

No asumir que todo es invernadero.

Definir una interfaz `PhysicalEnvironmentModel` y permitir:
- `GreenhousePhysicalModel`
- `OpenFieldPhysicalModel`

El MVP puede implementar primero el invernadero y un modelo exterior sencillo, pero las interfaces deben ser comunes.
