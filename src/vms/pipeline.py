"""Phase-2 pipeline: PIT snapshot → quality gate → profile resolution → drivers → deterministic statements.

Partial implementation of the SPEC §16.1 facade (build_pit_snapshot / estimate_driver_distributions
(central values only) / project_financials). Distributions, simulation and valuation are later phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from vms.capital_allocation.policies import make_policy
from vms.data.io import LoadResult
from vms.drivers.estimate import DriverModel, estimate_drivers
from vms.drivers.history import AnnualHistory, extract_annual
from vms.drivers.profiles import ProfileResolution, ProfileStatus, get_profile, resolve_profile
from vms.pit.snapshot import PITSnapshot
from vms.quality.report import DataQualityReport, assess, gate
from vms.schemas.config import LoadedConfig
from vms.statements.projection import ProjectionResult, _empty


@dataclass(frozen=True)
class Phase2Run:
    snapshot: PITSnapshot
    report: DataQualityReport
    resolution: ProfileResolution
    history: AnnualHistory
    drivers: DriverModel | None
    projection: ProjectionResult


def run_projection(load: LoadResult, *, instrument_id: str, as_of: datetime, loaded: LoadedConfig,
                   policy_id: str | None = None, years: int | None = None,
                   mode: Literal["production", "exploratory"] = "production",
                   override_reason: str | None = None) -> Phase2Run:
    cfg = loaded.config
    snap, report = assess(load, instrument_id=instrument_id, as_of=as_of, cfg=cfg.quality, mode=mode,
                          override_reason=override_reason)
    gate(report)  # raises GateError in production when BLOCKED
    resolution = resolve_profile(snap.classification, cfg.industry)
    history = extract_annual(snap)
    if resolution.status is ProfileStatus.UNSUPPORTED_PROFILE:
        return Phase2Run(snap, report, resolution, history, None,
                         _empty("UNSUPPORTED_PROFILE", snap, resolution, flags=resolution.flags))
    profile = get_profile(resolution.profile_id)
    profile.validate_driver_profile(loaded.profile)
    drivers = estimate_drivers(history, loaded.profile, cfg.projection)
    policy = make_policy(policy_id or cfg.capital_allocation.default_policy, cfg.capital_allocation,
                         {k: e.value for k, e in drivers.estimates.items()})
    proj = profile.project(snapshot=snap, history=history, drivers=drivers, policy=policy, resolution=resolution,
                           years=years or cfg.projection.default_years, cfg=cfg.projection)
    return Phase2Run(snap, report, resolution, history, drivers, proj)
