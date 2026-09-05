# Scientific Limitations

This Phase 4.7 implementation is a traceable approximation, not a validated
crop forecast. Main limitations are:

- crop-level RUE, SLA, stage thresholds, and stress profiles are not
  cultivar-calibrated;
- the phenology values are approximate and do not establish exact harvest
  dates;
- PAR share, ET approximation, root-zone bucket, and greenhouse thermal
  balance omit measured site parameters;
- nutrient availability is a single reduced N pool, not N-P-K chemistry;
- climate damage is phenomenological, not a mechanistic tissue or energy
  balance model;
- harvest readiness is an explicit maturity/stage rule, not a quality or
  market-readiness prediction.

These limitations are represented as configuration status and are not hidden
behind false precision.