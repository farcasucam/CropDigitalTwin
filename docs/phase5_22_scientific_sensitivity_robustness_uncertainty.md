# Phase 5.22 — Scientific Sensitivity, Robustness & Uncertainty Analysis

## 1. Objetivo y Alcance

La **Fase 5.22** implementa una capa rigurosa y determinista de análisis de:
- **Sensibilidad de parámetros y entradas** (One-At-A-Time y multivariable);
- **Robustez numérica y física** frente a condiciones de estrés extremo;
- **Propagación explícita de incertidumbre** (límites deterministas y Monte Carlo reproducible).

### Estado Científico
```text
SOFTWARE READY
SYNTHETIC DATA AVAILABLE
SYNTHETIC SENSITIVITY QUALIFIED
REAL AGRONOMIC DATA NOT VERIFIED
CALIBRATION NOT PERFORMED
EXPERIMENTAL VALIDATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

Esta fase responde estrictamente a la pregunta:
> "¿Qué parámetros y entradas dominan el comportamiento del modelo y qué tan robustas son sus salidas frente a incertidumbre razonable?"

No intenta responder ni inferir:
> "¿Qué valores son los correctos para el cultivo real?"

---

## 2. Distinción Científica Fundamental

| Concepto | Definición en Phase 5.22 | Estado en el Gemelo Digital |
| :--- | :--- | :--- |
| **Sensibilidad** | Cuánto varía una salida simulada ante una perturbación controlada de un parámetro o entrada. | **Implementada y cualificada sobre datos sintéticos.** |
| **Robustez** | Capacidad del modelo para mantener outputs finitos, comportamiento físicamente coherente y convergencia numérica en extremos. | **Verificada en 12 casos de estrés físico.** |
| **Incertidumbre** | Rango de dispersión en salidas producido por rangos explícitamente documentados de parámetros o entradas. | **Propagada determinísticamente; UNKNOWN cuando no está documentada.** |
| **Identificabilidad** | Capacidad teórica de estimar un parámetro de forma única a partir de un conjunto de observaciones sin confusión. | **Analizada en Phase 5.14; Sensibilidad ≠ Identificabilidad.** |
| **Calibración** | Ajuste o inferencia de parámetros a partir de datos observacionales locales verificados. | **NO REALIZADA (Bloqueada por ausencia de datos reales).** |
| **Validación** | Evaluación contra observaciones experimentales independientes no vistas durante calibración. | **NO AFIRMADA (Bloqueada hasta disponer de datos reales).** |

---

## 3. Arquitectura Reutilizada y Nuevos Contratos

No se duplicó ningún sistema existente:
- **`ParameterRegistry`** (`agri_twin.domain.parameter_audit`): Única autoridad sobre los 534 parámetros auditados del repositorio.
- **`SimulationClock`** (`agri_twin.application.clock`): Única autoridad temporal. Cero llamadas a relojes del sistema.
- **`SyntheticAgronomicDatasetProvider`** (`agri_twin.application.synthetic_real_data`): Proveedor del sustituto sintético (`SIMULATED_REAL_DATA_SUBSTITUTE`).
- **`CropGrowthEngine`**, **`ClimateStressEngine`**, **`PhenologyEngine`**, **`RadiationGrowthEngine`**, **`WaterBalanceEngine`**: Motores mecanísticos evaluados directamente mediante copias inmutables de perfiles.
- **`SimplifiedGreenhouseModel`** y **`CropGreenhouseFeedbackLoop`**: Evaluación física acoplada cultivo-invernadero.

### Nuevos Contratos (`src/agri_twin/application/sensitivity.py`)
- `ParameterSensitivityAnalyzer`: Motor central de análisis OAT, multivariable, robustez y propagación de incertidumbre.
- `SensitivityPerturbation`: Contrato inmutable que define valor nominal, valor perturbado, dirección, magnitud y origen del rango.
- `SensitivityCase`: Contexto completo de ejecución (cultivo, variedad, parcela, ciclo, ambiente, estado fenológico, observable).
- `SensitivityResult` / `ParameterSensitivityResult`: Resultado detallado con deltas absolutos y relativos, sensibilidad normalizada y absoluta, clasificación y grupos de confusión.
- `SensitivitySummary`: Agregación de casos clasificados por umbrales analíticos.
- `RobustnessResult`: Diagnóstico de estabilidad numérica, convergencia del feedback, límites físicos y monotonicidad.
- `UncertaintyPropagationResult`: Dispersión de salidas nominal/low/high y cuantiles Monte Carlo reproducibles (p10, p50, p90, mean, std).
- `SensitivityReport`: Reporte completo serializable determinísticamente a JSON con configuration hash.

---

## 4. Metodología de Sensibilidad

### One-At-A-Time (OAT)
Para cada parámetro elegible:
1. Se ejecuta el paso baseline con la configuración nominal inmutable.
2. Se ejecuta la perturbación negativa ($-\Delta P$) con clon aislado.
3. Se ejecuta la perturbación positiva ($+\Delta P$) con clon aislado.
4. Se calculan deltas y scores.
5. El estado original queda 100% inalterado (cero mutación de `ParameterRegistry` o `TwinState`).

### Score de Sensibilidad Normalizado y Absoluto
Cuando los denominadores son no nulos:
$$S_{\text{norm}} = \frac{(Y_{\text{pert}} - Y_{\text{base}}) / Y_{\text{base}}}{(P_{\text{pert}} - P_{\text{base}}) / P_{\text{base}}}$$

Si la salida baseline o el parámetro baseline son nulos o cercanos a cero ($< 10^{-12}$), se utiliza la sensibilidad absoluta:
$$S_{\text{abs}} = \frac{Y_{\text{pert}} - Y_{\text{base}}}{P_{\text{pert}} - P_{\text{base}}}$$
registrando explícitamente la razón `ZERO_BASELINE` o `ZERO_PARAMETER_BASELINE`.

### Umbrales Analíticos de Clasificación
- **`HIGH`**: $|S_{\text{norm}}| \ge 1.0$ (respuesta proporcional o superlineal).
- **`MEDIUM`**: $0.1 \le |S_{\text{norm}}| < 1.0$ (respuesta moderada).
- **`LOW`**: $0.0 \le |S_{\text{norm}}| < 0.1$ (respuesta amortiguada o despreciable).
- **`UNDEFINED`**: Salida no finita o error de evaluación.

*Nota científica: Estos límites son umbrales analíticos de ingeniería configurables; no constituyen constantes científicas universales.*

---

## 5. Grupos de Confusión (Confounder Groups)

El análisis integra los grupos identificados en la Fase 5.14:
1. `growth_scaling`: RUE, SLA, leaf area, biomass.
2. `radiation_interception`: extinction coefficient, radiation, LAI.
3. `phenology`: base temperature, upper temperature, GDD, maturity, thermal time.
4. `water_stress`: soil water, VWC, root depth, irrigation.
5. `vpd`: VPD thresholds, air humidity, temperature.
6. `co2`: CO2 baseline, ventilation, cover transmission, carbon fraction.
7. `senescence_damage`: senescence rate, frost damage, heat stress.
8. `fruit_development`: fruit weight, source-sink balance, maturity.

> [!WARNING]
> **Sensibilidad no implica Identifiabilidad**: Un parámetro con alta sensibilidad (ej. `radiation.rue`) puede estar fuertemente confundido con otro parámetro (ej. `radiation.sla` o `radiation.extinction_coefficient`). Las observaciones agronómicas convencionales no pueden desacoplar estos efectos sin experimentos diseñados específicamente.

---

## 6. Análisis Multivariable

Evalúa pares de parámetros pertenecientes a un mismo grupo de confusión evaluando las combinaciones:
- `(base, base)`
- `(high, base)`, `(low, base)`
- `(base, high)`, `(base, low)`
- `(high, high)`, `(low, low)`

Calcula el delta de acoplamiento no aditivo:
$$\Delta_{\text{interacción}} = \Delta Y(p_1, p_2) - (\Delta Y(p_1) + \Delta Y(p_2))$$

---

## 7. Análisis de Robustez (12 Casos de Estrés)

Se evalúan 12 escenarios de perturbación y límites físicos:
1. `extreme_heat_55c`: Ola de calor extrema (55°C) -> estrés térmico saturado, outputs finitos.
2. `extreme_frost_minus10c`: Helada severa (-10°C) -> acumulación de daño por helada, biomasa finita.
3. `zero_solar_night`: Radiación 0 W/m² -> APAR nulo, crecimiento potencial nulo, microclima estable.
4. `extreme_solar_1500w`: Radiación solar extrema (1500 W/m²) -> fotoinhibición activa, convergencia del feedback.
5. `arid_high_vpd`: 40°C y 10% HR -> estrés por VPD elevado, transpiración acotada.
6. `saturated_rh_100pct`: HR al 100% -> humedad relativa no excede el 100%, VPD ~ 0.
7. `wilting_point_soil`: Agua en punto de marchitez permanente (VWC 0.10) -> estrés hídrico máximo.
8. `extreme_ventilation_30ach`: Ventilación máxima (30 ACH) -> acoplamiento estrecho con el exterior.
9. `high_co2_1200ppm`: Enriquecimiento de CO2 a 1200 ppm -> concentración estable, sin divergencia.
10. `heavy_shading_80pct`: Malla de sombreo al 80% -> atenuación proporcional de radiación interior.
11. `monotonicity_radiation`: Monotonicidad de radiación (100 -> 500 -> 900 W/m²) -> crecimiento potencial monótonamente no decreciente.
12. `monotonicity_extinction`: Monotonicidad de extinción ($k=0.3 \to 0.6 \to 0.9$) -> APAR monótonamente no decreciente.

---

## 8. Propagación de Incertidumbre

Distingue rigurosamente la procedencia del rango de incertidumbre:
- `SCIENTIFIC_RANGE`: Derivado de literatura agronómica (`crop_phenology.csv`).
- `PROJECT_RANGE`: Derivado de contratos explícitos del proyecto (`reasonable_range`).
- `ENGINEERING_RANGE`: Rango técnico de diseño o ingeniería (ej. fracciones en $[0, 1]$).
- `OBSERVATIONAL_UNCERTAINTY`: Incertidumbre de medición explícita en dataset sintético (ej. 5%).
- `UNKNOWN`: Sin incertidumbre documentada -> reportado como `UNCERTAINTY_NOT_SPECIFIED`.

### Propagación Determinista y Monte Carlo Reproducible
- **Determinista**: Evalúa `nominal`, `low` y `high`, reportando dispersión absoluta y porcentual.
- **Monte Carlo**: Opcional, con semilla pseudoaleatoria explícita (`seed=42`) y generador local (`random.Random(seed)`), garantizando que no se muta el estado global de aleatoriedad. Calcula cuantiles $p_{10}$, $p_{50}$, $p_{90}$, media y desviación estándar.

---

## 9. Cobertura de Cultivos y Ambientes

- **7 Cultivos del proyecto**:
  - Anuales: `tomato`, `lettuce`, `pepper`.
  - Perennes: `grape`, `peach`, `plum`, `apple`.
- **Variedades**:
  - `tomato` / `RAF`
  - `pepper` / `Lamuyo`
  - `grape` / `Monastrell`
  - `plum` / `Suplum 26`
  - Variedades sin parámetros específicos reportan explícitamente:
    `VARIETY_SPECIFIC_DATA_NOT_AVAILABLE`.
- **Ambientes**:
  - `GREENHOUSE`: Evaluación acoplada mediante `SimplifiedGreenhouseModel` y `CropGreenhouseFeedbackLoop`.
  - `OUTDOOR`: Evaluación directa con meteorología exterior y fenología.
  - `EnergyPlus`: Backend opcional; su ausencia no bloquea el análisis de sensibilidad.

---

## 10. Benchmark Computacional y Materialización

El análisis completo sobre los 7 cultivos (10 parámetros $\times$ 7 cultivos $\times$ 2 direcciones OAT + análisis multivariable + 12 casos de robustez + propagación de incertidumbre) ejecuta **417 simulaciones** en **~0.42 segundos** (> 950 simulaciones/segundo).

Reporte materializado generado:
- `data/sensitivity/synthetic_sensitivity_report.json`

---

## 11. Limitaciones Explícitas

1. **Datos Reales**: No se ha verificado ningún dataset agronómico real. Toda la cualificación es sobre datos sintéticos.
2. **Calibración Bloqueada**: La sensibilidad sobre datos sintéticos no valida ningún parámetro para uso de campo.
3. **Incertidumbres Desconocidas**: Parámetros sin rango documentado permanecen como `UNCERTAINTY_NOT_SPECIFIED`.
4. **Confusión de Parámetros**: Parámetros altamente sensibles pueden ser no identificables simultáneamente sin nuevos tipos de sensores.
