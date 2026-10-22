"""Optional growth response to CO2 that lets enrichment raise growth (audit finding 6).

The historical response of ``CropGrowthEngine`` is ``min(1, CO2 / 420)``: depletion limits growth and enrichment gives nothing. This module holds the alternative, a logarithmic response
normalised to 1 at the reference concentration with a relative gain per doubling taken from a cited source (``src/co2_response.json``, status LITERATURE_GENERIC_C3_NOT_CROP_SPECIFIC).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class Co2ResponseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LogarithmicCo2Response:
    relative_gain_per_doubling: float
    reference_ppm: float = 420.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.relative_gain_per_doubling) or not 0.0 <= self.relative_gain_per_doubling <= 1.0:
            raise Co2ResponseError("the relative gain per doubling must be between 0 and 1")
        if not math.isfinite(self.reference_ppm) or self.reference_ppm <= 0.0:
            raise Co2ResponseError("the reference concentration must be positive")

    def __call__(self, co2_ppm: float) -> float:
        if not math.isfinite(co2_ppm) or co2_ppm < 0.0:
            raise Co2ResponseError("co2_ppm must be finite and non-negative")
        if co2_ppm == 0.0:
            return 0.0
        return max(0.0, 1.0 + self.relative_gain_per_doubling / math.log(2.0) * math.log(co2_ppm / self.reference_ppm))
