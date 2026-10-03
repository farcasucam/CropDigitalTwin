"""Published chilling-model formulations (pure, deterministic, hourly).

Only model definitions live here: the Utah weight table and the Dynamic Model
equations with their published constants. No species or cultivar requirement is
defined here; requirements come from the phenology profile (chill hours) or from an
explicit canonical configuration. Nothing here is calibration.

Utah Model
    Richardson, E.A., Seeley, S.D., Walker, D.R. (1974). A model for estimating the
    completion of rest for 'Redhaven' and 'Elberta' peach trees. HortScience 9(4),
    331-332. Weight table as reproduced in Zhang, J., Taylor, C. (2011), HortScience
    46(3), 420-425, Table 1, and in Luedeling, E., Brown, P.H. (2010), Int. J.
    Biometeorol. 55, 411-421, doi:10.1007/s00484-010-0352-y.

Dynamic Model
    Fishman, S., Erez, A., Couvillon, G.A. (1987a, 1987b). J. Theor. Biol. 126,
    309-321 and 124, 473-483. Erez, A., Fishman, S., Linsley-Noakes, G.C., Allan, P.
    (1990). The dynamic model for rest completion in peach buds. Acta Hortic. 276,
    165-174. Hourly equations and constants as given by Luedeling & Brown (2010),
    Zhang & Taylor (2011) and the chillR reference implementation (Luedeling,
    Dynamic_Model; Kelvin conversion T + 273).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

HOUR_SECONDS = 3600.0


class ChillingModelError(ValueError):
    """Raised when a published chilling formulation is applied outside its definition."""


def _hourly(model: str, temperature_c: float, dt_seconds: float) -> None:
    if not math.isfinite(temperature_c):
        raise ChillingModelError(f"{model}: temperature_c must be finite, got {temperature_c!r}")
    if dt_seconds != HOUR_SECONDS:
        raise ChillingModelError(f"MODEL_NOT_APPLICABLE: {model} is defined on hourly temperatures; dt_seconds must be 3600, got {dt_seconds!r}")


# ---------------------------------------------------------------------------
# Utah Model
# ---------------------------------------------------------------------------

# Published table (0.1 C resolution): <=1.4 -> 0; 1.5-2.4 -> 0.5; 2.5-9.1 -> 1;
# 9.2-12.4 -> 0.5; 12.5-15.9 -> 0; 16-18 -> -0.5; >18 -> -1 chill units per hour.
# Boundary convention for readings between published rows (for example 2.45 C):
# bands are lower-exclusive / upper-inclusive, so every published 0.1 C row maps to
# its tabulated weight. This convention is an ENGINEERING_CONVENTION, not a parameter.
UTAH_BANDS: tuple[tuple[float, float], ...] = (
    (1.4, 0.0),
    (2.4, 0.5),
    (9.1, 1.0),
    (12.4, 0.5),
    (15.9, 0.0),
    (18.0, -0.5),
    (math.inf, -1.0),
)
UTAH_PUBLISHED_ROWS: tuple[tuple[float, float, float], ...] = (
    # (lowest tabulated C, highest tabulated C, chill units per hour); None-free table rows
    (-math.inf, 1.4, 0.0),
    (1.5, 2.4, 0.5),
    (2.5, 9.1, 1.0),
    (9.2, 12.4, 0.5),
    (12.5, 15.9, 0.0),
    (16.0, 18.0, -0.5),
    (18.1, math.inf, -1.0),
)


def utah_weight(temperature_c: float) -> float:
    """Utah chill units contributed by one hour at ``temperature_c``."""
    if not math.isfinite(temperature_c):
        raise ChillingModelError(f"UTAH: temperature_c must be finite, got {temperature_c!r}")
    for upper, weight in UTAH_BANDS:
        if temperature_c <= upper:
            return weight
    raise ChillingModelError("UTAH: unreachable band")  # pragma: no cover


def utah_step(accumulated: float, temperature_c: float, dt_seconds: float) -> float:
    """One hourly Utah update; the running sum can be negative (warm-hour negation)."""
    _hourly("UTAH", temperature_c, dt_seconds)
    return accumulated + utah_weight(temperature_c)


# ---------------------------------------------------------------------------
# Dynamic Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DynamicModelParameters:
    """Published Dynamic Model constants (Erez et al. 1990); not tunable here."""

    e0: float = 4153.5
    e1: float = 12888.8
    a0: float = 139500.0
    a1: float = 2.567e18
    slope: float = 1.6
    tf: float = 277.0
    kelvin_offset: float = 273.0  # reference implementation conversion (chillR: T + 273)


DYNAMIC_PARAMETERS = DynamicModelParameters()


@dataclass(frozen=True, slots=True)
class DynamicStep:
    intermediate: float  # interE after this hour
    transfer_fraction: float  # xi of this hour
    portion: float  # chill portion completed in this hour (delt)


def dynamic_step(intermediate: float, previous_transfer_fraction: float, temperature_c: float, dt_seconds: float,
                 parameters: DynamicModelParameters = DYNAMIC_PARAMETERS) -> DynamicStep:
    """One hourly Dynamic Model update.

    TK = T + 273; xi = e^f / (1 + e^f), f = slope * Tf * (TK - Tf) / TK;
    xs = (A0 / A1) e^((E1 - E0) / TK); k1 = A1 e^(-E1 / TK);
    S = interE(t-1) if interE(t-1) < 1 else interE(t-1) (1 - xi(t-1));
    interE(t) = xs - (xs - S) e^(-k1); portion(t) = xi(t) interE(t) if interE(t) >= 1 else 0.
    """
    _hourly("DYNAMIC", temperature_c, dt_seconds)
    if not (math.isfinite(intermediate) and intermediate >= 0.0 and math.isfinite(previous_transfer_fraction) and 0.0 <= previous_transfer_fraction <= 1.0):
        raise ChillingModelError("DYNAMIC: state must hold a finite non-negative intermediate and a transfer fraction in [0, 1]")
    p = parameters
    tk = temperature_c + p.kelvin_offset
    if tk <= 0.0:
        raise ChillingModelError(f"DYNAMIC: temperature_c={temperature_c!r} is at or below absolute zero in the model's Kelvin conversion")
    aa = p.a0 / p.a1
    ee = p.e1 - p.e0
    try:
        ftmprt = p.slope * p.tf * (tk - p.tf) / tk
        sr = math.exp(ftmprt)
        xi = sr / (1.0 + sr)
        xs = aa * math.exp(ee / tk)
        ak1 = p.a1 * math.exp(-p.e1 / tk)
    except OverflowError:
        raise ChillingModelError(f"DYNAMIC: temperature_c={temperature_c!r} is outside the numerical domain of the model") from None
    start = intermediate if intermediate < 1.0 else intermediate - intermediate * previous_transfer_fraction
    inter_e = xs - (xs - start) * math.exp(-ak1)
    portion = inter_e * xi if inter_e >= 1.0 else 0.0
    return DynamicStep(inter_e, xi, portion)


__all__ = [
    "DYNAMIC_PARAMETERS",
    "HOUR_SECONDS",
    "UTAH_BANDS",
    "UTAH_PUBLISHED_ROWS",
    "ChillingModelError",
    "DynamicModelParameters",
    "DynamicStep",
    "dynamic_step",
    "utah_step",
    "utah_weight",
]
