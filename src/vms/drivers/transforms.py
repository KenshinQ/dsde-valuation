"""Variable-appropriate transforms (SPEC §7.3). Bounded transforms map [lower, upper] to the real line.

Phase 2 central values are medians, which commute with these monotone transforms, so the
transforms are reported here (``transformed_value``) and are used for estimation from Phase 3 on.
"""

from __future__ import annotations

import math

_EPS = 1e-9


def forward(transform: str, x: float, lower: float, upper: float) -> float:
    if transform == "identity":
        return x
    if transform == "log1p":
        if x <= -1.0:
            raise ValueError(f"log1p undefined for x={x} <= -1")
        return math.log1p(x)
    if transform == "logit":
        p = (x - lower) / (upper - lower)
        p = min(max(p, _EPS), 1 - _EPS)
        return math.log(p / (1 - p))
    raise ValueError(f"unknown transform {transform!r}")


def inverse(transform: str, z: float, lower: float, upper: float) -> float:
    if transform == "identity":
        return z
    if transform == "log1p":
        return math.expm1(z)
    if transform == "logit":
        return lower + (upper - lower) / (1 + math.exp(-z))
    raise ValueError(f"unknown transform {transform!r}")
