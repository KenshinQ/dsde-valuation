"""Deterministic central driver values from snapshot history (DRIVER-CENTRAL-MEDIAN-v1).

Distributions, shrinkage and parameter uncertainty are Phase 3. Here, per driver:
median of the most recent ``driver_history_years`` non-null annual observations, clipped to
profile bounds (flag CLIPPED_TO_BOUND). With zero observations the profile prior is used (flag
PRIOR_FALLBACK + LOW_CONFIDENCE). Fewer than ``min_history_years`` observations => LOW_CONFIDENCE.
"""

from __future__ import annotations

import statistics
from typing import Literal

from pydantic import BaseModel, ConfigDict

from vms.assumptions import cite
from vms.drivers.definitions import DEFINITIONS
from vms.drivers.history import AnnualHistory
from vms.drivers.transforms import forward
from vms.schemas.config import DriverProfile, ProjectionConfig

ESTIMATOR_VERSION = "CENTRAL-MEDIAN-1"


class DriverObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    year: int
    value: float
    flags: list[str]


class DriverEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    family: str
    role: Literal["projection", "diagnostic"]
    value: float
    transformed_value: float
    transform: str
    method: Literal["historical_median", "prior_fallback"]
    n_obs: int
    observations: list[DriverObservation]
    lower: float
    upper: float
    clipped: bool
    low_confidence: bool
    formula: str
    flags: list[str]


class DriverModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    estimator_version: str = ESTIMATOR_VERSION
    profile_id: str
    profile_version: str
    bounds_status: str
    history_years: list[int]
    estimates: dict[str, DriverEstimate]
    assumptions: list[str]

    def __getitem__(self, name: str) -> float:
        return self.estimates[name].value


class DriverEstimationError(ValueError):
    pass


def estimate_drivers(history: AnnualHistory, profile: DriverProfile, cfg: ProjectionConfig) -> DriverModel:
    out: dict[str, DriverEstimate] = {}
    for spec in profile.drivers:
        d = DEFINITIONS.get(spec.name)
        if d is None:
            raise DriverEstimationError(f"profile '{profile.profile_id}' lists driver '{spec.name}' with no "
                                        f"definition; known: {sorted(DEFINITIONS)}")
        obs = []
        for y in history.years:
            v, fl = d.fn(history, y)
            if v is not None:
                obs.append(DriverObservation(year=y, value=v, flags=fl))
        obs = obs[-cfg.driver_history_years:]
        flags: set[str] = set()
        for o in obs:
            flags.update(o.flags)
            if not (spec.lower <= o.value <= spec.upper):
                flags.add("OBS_OUT_OF_BOUNDS")
        if obs:
            raw, method = statistics.median(o.value for o in obs), "historical_median"
        elif spec.prior is not None:
            raw, method = spec.prior, "prior_fallback"
            flags.add("PRIOR_FALLBACK")
        else:
            raise DriverEstimationError(f"driver '{spec.name}': no history and no prior in profile "
                                        f"'{profile.profile_id}'; add a labeled prior or provide data")
        value = min(max(raw, spec.lower), spec.upper)
        clipped = value != raw
        if clipped:
            flags.add("CLIPPED_TO_BOUND")
        low = len(obs) < cfg.min_history_years
        if low:
            flags.add("LOW_CONFIDENCE")
        out[spec.name] = DriverEstimate(
            name=spec.name, family=spec.family.value, role=spec.role, value=value,
            transformed_value=forward(spec.transform.value, value, spec.lower, spec.upper),
            transform=spec.transform.value, method=method, n_obs=len(obs), observations=obs,
            lower=spec.lower, upper=spec.upper, clipped=clipped, low_confidence=low, formula=d.formula,
            flags=sorted(flags))
    return DriverModel(profile_id=profile.profile_id, profile_version=profile.profile_version,
                       bounds_status=profile.bounds_status, history_years=history.years, estimates=out,
                       assumptions=cite("DRIVER-CENTRAL-MEDIAN-v1", "DRIVER-PRIORS-PLACEHOLDER-v1",
                                        "ANNUAL-BASE-v1", "DIVIDEND-T-PLUS-1-v1", "ONE-OFFS-v1"))
