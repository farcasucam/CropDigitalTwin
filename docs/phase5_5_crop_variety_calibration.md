# Phase 5.5 Calibration by Crop and Variety

## Scientific status

This phase establishes a reproducible protocol, not scientific calibration.
The repository currently contains four configured plots and four known
variety/plot combinations: tomato/RAF, pepper/Lamuyo, grape/Monastrell and
plum/Suplum 26. Lettuce, peach and apple remain generic crop catalog entries.

The data audit finds no local agronomic observations. The weather CSV is
forcing data, not LAI, biomass, phenology, VWC, irrigation, stress, damage or
yield observations. `crop_phenology.csv` contains external literature evidence
and remains a prior/evidence source, not local calibration data.

Consequently every current crop/variety protocol is explicitly
`INSUFFICIENT_DATA`. No variety-specific values are invented and no protocol
is marked `CALIBRATED` or `VALIDATED`.

## Hierarchical protocol

`CropCalibrationProtocol` is built from the Phase 5.1 `ParameterRegistry` and
keeps species, variety, plot and environment scope separate. A generic tomato
prior is not silently relabelled as RAF; Monastrell and Suplum 26 do not
receive direct values merely because their names exist in farm configuration.
Outdoor and greenhouse protocols are distinct.

The calibrability matrix records parameter ID, prior/range/unit/source,
evidence/confidence, scope, calibration permission/status, required
observations, calibration priority, reason, confounders and identifiability
risk. Priorities are phenology, growth, water, stress and production. The
intended order is sequential, not simultaneous fitting.

## Data requirements and identifiability

Phenology requires timestamped event observations such as flowering, fruit set,
maturity and harvest. Growth requires LAI/biomass trajectories. Water requires
VWC, rainfall, irrigation and suitable environmental forcing. Stress requires
severity/duration/damage observations. Yield and fruit parameters require
production observations.

RUE can be confounded with LAI and partitioning; Tupper with heat/VPD stress;
root depth with drainage and soil properties. These are recorded as risks, not
resolved by optimizer output. Future reports should flag parameters at search
bounds (`BOUNDARY_SOLUTION`) and compare calibration against an independent
time-separated validation period. A good synthetic or training score is not
validation.

## Reuse of existing frameworks

The protocol creates `ParameterSet` only from registry records with explicit
ranges and calibration permission, then delegates fitting to the existing
Phase 5.2 deterministic `GridSearchCalibrator`. Phase 5.3 validation and
Phase 5.4 scenarios remain the downstream evaluation/experiment layers. No
second calibration engine or new physiological model is introduced.

`synthetic_calibration_report()` exists only for framework demonstrations.
Synthetic results are labelled as such and never become crop evidence.

## Reports and future datasets

The delivery audit is `manual_phase5_5_crop_variety_calibration_test.py`.
For each crop/variety/plot it prints scientific status, observed count and
candidate count. When data arrive, add a timestamped observation dataset,
split calibration and validation by season/plot where possible, record source
and environment type, run the protocol, and retain the complete report.
Do not random-split time series or transfer greenhouse calibration to outdoor
conditions automatically.

## Limitations

`LITERATURE PRIOR -> CALIBRATION CANDIDATE -> CALIBRATED -> INDEPENDENT
VALIDATION -> VALIDATED` is the required progression. The current repository
stops at literature/engineering priors plus framework readiness. This phase is
not a scientific claim about any of the seven crops or known varieties.