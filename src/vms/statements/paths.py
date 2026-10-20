"""Path-wise statement projection (SPEC §9–10, Phase 5). PATH-STATEMENTS-v1 / FAILED-PATHS-EXCLUDED-v1."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.capital_allocation.policies import make_policy
from vms.drivers.estimate import DriverModel
from vms.drivers.history import AnnualHistory
from vms.drivers.profiles import ProfileResolution, get_profile
from vms.pit.snapshot import PITSnapshot
from vms.sampling.schemas import PathRecord, SimulationBundle
from vms.schemas.config import CapitalAllocationConfig, DriverProfile, ProjectionConfig
from vms.statements.projection import PATH_LABEL, ProjectionResult

PATH_BUNDLE_VERSION = "FIN-PATH-1"


class CentralPathError(RuntimeError):
    """Central path failed invariants / insufficient data (CENTRAL-PATH-GATE-v1)."""



class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FinancialPathRecord(_M):
    path_id: str
    kind: Literal["central", "monte_carlo"]
    status: Literal["VALID", "REJECTED", "INSUFFICIENT_DATA"]
    excluded_from_aggregates: bool
    invalid_reason: str | None = None
    violation_codes: list[str] = Field(default_factory=list)
    projection: ProjectionResult | None
    # slim share / FCF series for aggregates without re-reading full ledger
    shares: dict[str, float] = Field(default_factory=dict)          # year -> diluted_shares
    fcff: dict[str, float] = Field(default_factory=dict)
    fcfe: dict[str, float] = Field(default_factory=dict)
    fcff_per_share: dict[str, float] = Field(default_factory=dict)
    book_equity_per_share: dict[str, float] = Field(default_factory=dict)
    dividends: dict[str, float] = Field(default_factory=dict)
    share_repurchases: dict[str, float] = Field(default_factory=dict)
    share_issuance_proceeds: dict[str, float] = Field(default_factory=dict)
    net_borrowing: dict[str, float] = Field(default_factory=dict)
    cash: dict[str, float] = Field(default_factory=dict)
    debt: dict[str, float] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)


class FinancialPathBundle(_M):
    schema_kind: Literal["FinancialPathBundle"] = "FinancialPathBundle"
    version: str = PATH_BUNDLE_VERSION
    label: str = PATH_LABEL
    policy: dict
    base_year: int
    years: list[int]
    n_input_paths: int
    n_valid: int
    n_failed: int
    central: FinancialPathRecord
    paths: list[FinancialPathRecord]          # all attempted (valid + failed)
    valid_path_ids: list[str]
    failed: list[dict[str, Any]]
    aggregates: dict[str, Any]                # ONLY over valid_path_ids
    sampler_ref: dict[str, Any]
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)


def _series(proj: ProjectionResult, name: str) -> dict[str, float]:
    out = {}
    for y in proj.years:
        key = f"{name}@{y}"
        if key in proj.items:
            out[str(y)] = proj.items[key].value
    return out


def _record_from_projection(path: PathRecord, proj: ProjectionResult) -> FinancialPathRecord:
    failed = proj.status != "VALID"
    codes = [v.code for v in proj.violations]
    reason = None
    if proj.status == "INSUFFICIENT_DATA":
        reason = "INSUFFICIENT_DATA:" + ",".join(proj.missing_inputs[:5])
    elif codes:
        reason = "REJECTED:" + ",".join(sorted(set(codes))[:8])
    return FinancialPathRecord(
        path_id=path.path_id, kind=path.kind, status=proj.status,  # type: ignore[arg-type]
        excluded_from_aggregates=failed, invalid_reason=reason, violation_codes=sorted(set(codes)),
        projection=proj if not failed else proj,   # keep full for diagnostics; aggregates ignore failed
        shares=_series(proj, "diluted_shares"), fcff=_series(proj, "fcff"), fcfe=_series(proj, "fcfe"),
        fcff_per_share=_series(proj, "fcff_per_share"), book_equity_per_share=_series(proj, "book_equity_per_share"),
        dividends=_series(proj, "dividends"), share_repurchases=_series(proj, "share_repurchases"),
        share_issuance_proceeds=_series(proj, "share_issuance_proceeds"),
        net_borrowing=_series(proj, "net_borrowing"), cash=_series(proj, "cash"),
        debt=_series(proj, "interest_bearing_debt"),
        flags=sorted(set(proj.flags) | ({"EXCLUDED_FROM_AGGREGATES"} if failed else set())),
    )


def _year_drivers(path: PathRecord, base_year: int) -> dict[int, dict[str, float]]:
    return {base_year + yd.year_index: dict(yd.drivers) for yd in path.years}


def _aggregates(valid: list[FinancialPathRecord], years: list[int]) -> dict[str, Any]:
    if not valid:
        return {"n": 0, "note": "no valid paths; aggregates empty (FAILED-PATHS-EXCLUDED-v1)"}
    out: dict[str, Any] = {"n": len(valid), "by_year": {}}
    for y in years:
        ys = str(y)
        block: dict[str, Any] = {}
        for field in ("fcff", "fcfe", "shares", "fcff_per_share", "book_equity_per_share",
                      "dividends", "cash", "debt"):
            xs = np.array([getattr(r, field).get(ys) for r in valid if ys in getattr(r, field)], dtype=float)
            xs = xs[np.isfinite(xs)]
            if xs.size == 0:
                continue
            block[field] = {"mean": float(xs.mean()), "p50": float(np.median(xs)),
                            "p05": float(np.quantile(xs, 0.05)), "p95": float(np.quantile(xs, 0.95)),
                            "std": float(xs.std(ddof=1)) if xs.size > 1 else 0.0, "n": int(xs.size)}
        out["by_year"][ys] = block
    import hashlib
    out["valid_path_id_hash"] = hashlib.sha256(",".join(sorted(r.path_id for r in valid)).encode()).hexdigest()[:16]
    return out


def project_financial_paths(*, bundle: SimulationBundle, snapshot: PITSnapshot, history: AnnualHistory,
                            drivers: DriverModel, resolution: ProfileResolution, profile: DriverProfile,
                            proj_cfg: ProjectionConfig, ca_cfg: CapitalAllocationConfig,
                            policy_id: str | None = None,
                            mode: str = "production", override_reason: str | None = None) -> FinancialPathBundle:
    """Project every SimulationBundle path (central + MC). Failed paths are recorded and excluded from aggregates."""
    if resolution.profile_id != "operating_company":
        raise ValueError(f"path projection only for operating_company; got {resolution.profile_id}")
    sector = get_profile(resolution.profile_id)
    sector.validate_driver_profile(profile)
    pid = policy_id or ca_cfg.default_policy
    # seed policy with central / DriverModel values; overwritten per year inside project()
    policy = make_policy(pid, ca_cfg, {k: e.value for k, e in drivers.estimates.items()})
    base_year = bundle.base_year
    years = list(bundle.years)
    n_years = len(years)

    def one(path: PathRecord) -> FinancialPathRecord:
        yd = _year_drivers(path, base_year)
        # fresh policy instance so concurrent mutation of .d is safe if we ever parallelise
        pol = make_policy(pid, ca_cfg, {k: e.value for k, e in drivers.estimates.items()})
        proj = sector.project(snapshot=snapshot, history=history, drivers=drivers, policy=pol,
                              resolution=resolution, years=n_years, cfg=proj_cfg, year_drivers=yd)
        return _record_from_projection(path, proj)

    central = one(bundle.central)
    records = [one(p) for p in bundle.paths]
    valid = [r for r in records if not r.excluded_from_aggregates]
    failed = [{"path_id": r.path_id, "status": r.status, "reason": r.invalid_reason,
               "violation_codes": r.violation_codes} for r in records if r.excluded_from_aggregates]
    flags = []
    if central.excluded_from_aggregates or central.status != "VALID":
        flags.append("CENTRAL_PATH_FAILED")
        failed = [{"path_id": central.path_id, "status": central.status, "reason": central.invalid_reason,
                   "violation_codes": central.violation_codes}, *failed]
        if mode == "production":
            raise CentralPathError(
                f"central path {central.status}: {central.invalid_reason or central.violation_codes} "
                f"(CENTRAL-PATH-GATE-v1). Fix the model/data, or rerun with --mode exploratory "
                f"--override-reason '...'")
        if not (override_reason or "").strip():
            raise CentralPathError(
                "central path failed: exploratory mode requires --override-reason")
        flags.append("CENTRAL_PATH_FAILURE_OVERRIDDEN")
    if any(r.excluded_from_aggregates for r in records):
        flags.append("SOME_PATHS_FAILED_EXCLUDED")
    return FinancialPathBundle(
        policy=policy.describe(), base_year=base_year, years=years,
        n_input_paths=len(bundle.paths), n_valid=len(valid), n_failed=len(failed),
        central=central, paths=[central, *records], valid_path_ids=[r.path_id for r in valid],
        failed=failed, aggregates=_aggregates(valid, years),
        sampler_ref={"sampler_version": bundle.sampler_version, "seed": bundle.seed,
                     "n_paths": bundle.n_paths, "dependence_hash": bundle.parameter_snapshot.get("dependence_hash")},
        assumptions=cite("PATH-STATEMENTS-v1", "FAILED-PATHS-EXCLUDED-v1", "CENTRAL-PATH-GATE-v1",
                         "PATH-LEDGER-PARQUET-v1", "BUYBACK-PRICE-LAST-CLOSE-v1",
                         "DIVIDEND-T-PLUS-1-v1", "DILUTED-SHARES-BASIC-v1", "REVOLVER-MIN-CASH-v1",
                         "BUYBACK-PRICE-v1"),
        flags=sorted(set(flags)))
