"""Pipelines.

Phase 2: PIT → gate → profile → drivers → deterministic statements.
Phase 3: PIT → gate → profile → regimes → walk-forward → driver distributions.
Phase 4: Phase 3 + correlated path sampler (SimulationBundle).

Partial SPEC §16.1 facade: see ``vms.engine.ValuationEngine``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from vms.capital_allocation.policies import make_policy
from vms.data.io import LoadResult
from vms.drivers.estimate import DriverModel, estimate_drivers
from vms.drivers.history import AnnualHistory, extract_annual
from vms.drivers.profiles import ProfileResolution, ProfileStatus, get_profile, resolve_profile
from vms.pit.snapshot import PITSnapshot
from vms.quality.report import DataQualityReport, assess, gate
from vms.schemas.config import LoadedConfig
from vms.statements.projection import ProjectionResult, _empty

if TYPE_CHECKING:
    from vms.drivers.distributions import DistributionModel
    from vms.drivers.walk_forward import WalkForwardReport
    from vms.regimes import RegimeResult


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


@dataclass(frozen=True)
class Phase3Run:
    snapshot: PITSnapshot
    report: DataQualityReport
    resolution: ProfileResolution
    history: AnnualHistory
    regimes: "RegimeResult | None"
    walk_forward: "WalkForwardReport | None"
    distributions: "DistributionModel | None"
    central: DriverModel | None


def run_estimation(load: LoadResult, *, instrument_id: str, as_of: datetime, loaded: LoadedConfig, seed: int,
                   mode: Literal["production", "exploratory"] = "production",
                   override_reason: str | None = None) -> Phase3Run:
    from vms.drivers.distributions import build_distribution_model
    from vms.drivers.walk_forward import walk_forward
    from vms.regimes import infer_regimes

    cfg = loaded.config
    snap, report = assess(load, instrument_id=instrument_id, as_of=as_of, cfg=cfg.quality, mode=mode,
                          override_reason=override_reason)
    gate(report)
    resolution = resolve_profile(snap.classification, cfg.industry)
    history = extract_annual(snap)
    if resolution.status is ProfileStatus.UNSUPPORTED_PROFILE:
        return Phase3Run(snap, report, resolution, history, None, None, None, None)
    get_profile(resolution.profile_id).validate_driver_profile(loaded.profile)
    regimes = infer_regimes(snap.financials, as_of=snap.as_of, cfg=cfg.regimes)
    wf = walk_forward(load, instrument_id=instrument_id, snap=snap, history=history, regimes=regimes,
                      profile=loaded.profile, est=cfg.estimation, reg_cfg=cfg.regimes)
    dist = build_distribution_model(history, loaded.profile, regimes=regimes, walk_forward_report=wf,
                                    cfg=cfg.estimation, seed=seed)
    central = _central_from_selected(dist, loaded.profile, history, cfg.projection)
    return Phase3Run(snap, report, resolution, history, regimes, wf, dist, central)


def _central_from_selected(dist, profile, history, proj_cfg):  # noqa: ANN001
    """CENTRAL-FROM-SELECTED-v1: DriverModel from selected-spec medians (Phase 2 projection still uses medians)."""
    from vms.assumptions import cite
    from vms.drivers.estimate import DriverModel, estimate_drivers
    from vms.drivers.transforms import inverse

    legacy = estimate_drivers(history, profile, proj_cfg)
    estimates = {}
    for name, est in legacy.estimates.items():
        dd = dist.drivers[name]
        fit = dd.specs[dd.selected_spec]
        raw = inverse(dd.transform, fit.loc, dd.lower, dd.upper)
        value = min(max(raw, dd.lower), dd.upper)
        estimates[name] = est.model_copy(update={
            "value": value, "transformed_value": fit.loc, "method": "selected_median",
            "clipped": value != raw, "low_confidence": dd.low_confidence,
            "flags": sorted({*est.flags, *dd.flags, "CENTRAL_FROM_SELECTED"}),
        })
    return DriverModel(
        profile_id=profile.profile_id, profile_version=profile.profile_version,
        bounds_status=profile.bounds_status, history_years=legacy.history_years, estimates=estimates,
        assumptions=cite("CENTRAL-FROM-SELECTED-v1", "MODEL-SELECTION-WF-v2", "DRIVER-TRANSFORMS-v1",
                         "ANNUAL-BASE-v1"))



@dataclass(frozen=True)
class Phase4Run:
    snapshot: "PITSnapshot"
    report: "DataQualityReport"
    resolution: "ProfileResolution"
    history: "AnnualHistory"
    regimes: "RegimeResult | None"
    walk_forward: "WalkForwardReport | None"
    distributions: "DistributionModel | None"
    central: "DriverModel | None"
    bundle: "SimulationBundle | None"


def run_simulation(load: LoadResult, *, instrument_id: str, as_of: datetime, loaded: LoadedConfig, seed: int,
                   n_paths: int | None = None, n_years: int | None = None,
                   mode: Literal["production", "exploratory"] = "production",
                   override_reason: str | None = None) -> Phase4Run:
    from vms.reporting.metadata import code_version, hash_models, sha256_of
    from vms.sampling import simulate_paths

    p3 = run_estimation(load, instrument_id=instrument_id, as_of=as_of, loaded=loaded, seed=seed, mode=mode,
                        override_reason=override_reason)
    if p3.distributions is None or p3.regimes is None:
        return Phase4Run(p3.snapshot, p3.report, p3.resolution, p3.history, None, None, None, None, None)
    cfg = loaded.config
    paths = cfg.monte_carlo.default_paths if n_paths is None else n_paths
    years = n_years or max(cfg.horizons_years)
    base_year = max(p3.history.years) if p3.history.years else as_of.year - 1
    data_hash = sha256_of({"records": hash_models([*load.financial, *load.market, *load.corporate_actions,
                                                    *load.classifications]),
                           "sources": sorted(load.sources)})
    prov = {
        "data_hash": data_hash,
        "config_hash": sha256_of({"c": cfg.model_dump(mode="json"), "p": loaded.profile.model_dump(mode="json")}),
        "code_version": code_version(),
        "seed_streams": ["param_bootstrap:<driver>", "path:<i>"],
        "estimation_seed": seed,
    }
    bundle = simulate_paths(regimes=p3.regimes, distributions=p3.distributions, profile=loaded.profile,
                            n_paths=paths, n_years=years, seed=seed, mc=cfg.monte_carlo, est=cfg.estimation,
                            base_year=base_year, provenance=prov, mode=mode, override_reason=override_reason)
    return Phase4Run(p3.snapshot, p3.report, p3.resolution, p3.history, p3.regimes, p3.walk_forward,
                     p3.distributions, p3.central, bundle)



@dataclass(frozen=True)
class Phase5Run:
    snapshot: "PITSnapshot"
    report: "DataQualityReport"
    resolution: "ProfileResolution"
    history: "AnnualHistory"
    regimes: "RegimeResult | None"
    walk_forward: "WalkForwardReport | None"
    distributions: "DistributionModel | None"
    central: "DriverModel | None"
    bundle: "SimulationBundle | None"
    financial_paths: "FinancialPathBundle | None"


def run_path_projection(load: LoadResult, *, instrument_id: str, as_of: datetime, loaded: LoadedConfig, seed: int,
                        n_paths: int | None = None, n_years: int | None = None, policy_id: str | None = None,
                        mode: Literal["production", "exploratory"] = "production",
                        override_reason: str | None = None) -> Phase5Run:
    from vms.statements.paths import project_financial_paths

    p4 = run_simulation(load, instrument_id=instrument_id, as_of=as_of, loaded=loaded, seed=seed, n_paths=n_paths,
                        n_years=n_years, mode=mode, override_reason=override_reason)
    if p4.bundle is None or p4.central is None:
        return Phase5Run(p4.snapshot, p4.report, p4.resolution, p4.history, None, None, None, None, None, None)
    fp = project_financial_paths(
        bundle=p4.bundle, snapshot=p4.snapshot, history=p4.history, drivers=p4.central, resolution=p4.resolution,
        profile=loaded.profile, proj_cfg=loaded.config.projection, ca_cfg=loaded.config.capital_allocation,
        policy_id=policy_id, mode=mode, override_reason=override_reason)
    return Phase5Run(p4.snapshot, p4.report, p4.resolution, p4.history, p4.regimes, p4.walk_forward,
                     p4.distributions, p4.central, p4.bundle, fp)


@dataclass(frozen=True)
class Phase6Run:
    snapshot: "PITSnapshot"
    report: "DataQualityReport"
    resolution: "ProfileResolution"
    history: "AnnualHistory"
    regimes: "RegimeResult | None"
    walk_forward: "WalkForwardReport | None"
    distributions: "DistributionModel | None"
    central: "DriverModel | None"
    bundle: "SimulationBundle | None"
    financial_paths: "FinancialPathBundle | None"
    valuation: "ValuationBundle | None"


def run_valuation(load: LoadResult, *, instrument_id: str, as_of: datetime, loaded: LoadedConfig, seed: int,
                  n_paths: int | None = None, n_years: int | None = None, policy_id: str | None = None,
                  mode: Literal["production", "exploratory"] = "production",
                  override_reason: str | None = None) -> Phase6Run:
    from vms.valuation import value_paths

    p5 = run_path_projection(load, instrument_id=instrument_id, as_of=as_of, loaded=loaded, seed=seed,
                             n_paths=n_paths, n_years=n_years, policy_id=policy_id, mode=mode,
                             override_reason=override_reason)
    if p5.financial_paths is None:
        return Phase6Run(p5.snapshot, p5.report, p5.resolution, p5.history, None, None, None, None, None, None, None)
    val = value_paths(financial=p5.financial_paths, snapshot=p5.snapshot, loaded=loaded)
    return Phase6Run(p5.snapshot, p5.report, p5.resolution, p5.history, p5.regimes, p5.walk_forward,
                     p5.distributions, p5.central, p5.bundle, p5.financial_paths, val)
