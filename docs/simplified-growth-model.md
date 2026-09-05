# Simplified Integrated Mathematical Model

The integrated model intentionally combines lightweight submodels rather than
attempting biochemical photosynthesis, CFD, mechanistic soil chemistry, or
exact event-date prediction.

Radiation uses interval PAR conversion and Beer-Lambert interception:

`PAR = 0.48 * shortwave_W_m2 * dt_s / 1e6`

`PAR_intercepted = PAR * (1 - exp(-k * LAI))`

`growth_potential = PAR_intercepted * RUE`

Actual growth is limited by independent factors:

`growth_actual = growth_potential * temperature * radiation * water * VPD * nutrient * CO2`

The water model is a root-zone bucket with rainfall, passive irrigation,
evaporation, LAI-scaled transpiration, and drainage. Nutrients use one
reduced nitrogen availability pool. Climate stress tracks continuous ramps,
exposure duration, recoverable damage, and irreversible damage. Greenhouse
microclimate uses a lumped thermal relaxation with solar transmission,
ventilation, thermal mass, losses, shading, and HVAC.

No component creates an internal real-time loop. Large `dt` values are
calculated directly; scheduler-level smaller steps remain available when a
scenario needs higher temporal resolution.