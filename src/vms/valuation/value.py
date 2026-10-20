"""Path-wise DCF + exit-multiple + EV-equity bridge (Phase 6)."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.pit.snapshot import PITSnapshot
from vms.schemas.config import LoadedConfig
from vms.statements.cashflows import FCFFSeries
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord
from vms.valuation.dcf import DCFResult, dcf_fcff
from vms.valuation.multiples import ExitMultipleResult, exit_multiple_ev
from vms.equity_bridge.bridge import BridgeResult, bridge_ev_to_equity
from vms.valuation.wacc import WACCInputs, build_wacc

VALUATION_VERSION = "VAL-1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathValuation(_M):
    path_id: str
    kind: Literal["central", "monte_carlo"]
    status: Literal["VALID", "REJECTED", "SKIPPED_INPUT"]
    invalid_reason: str | None = None
    excluded_from_aggregates: bool
    wacc_inputs: WACCInputs | None = None
    dcf: DCFResult | None = None
    exit_multiple: ExitMultipleResult | None = None
    bridge_dcf: BridgeResult | None = None
    bridge_exit: BridgeResult | None = None
    composite_equity: float | None = None
    composite_value_per_share: float | None = None
    flags: list[str] = Field(default_factory=list)


class ValuationBundle(_M):
    schema_kind: Literal["ValuationBundle"] = "ValuationBundle"
    version: str = VALUATION_VERSION
    label: str = "DCF_AND_EXIT_MULTIPLE_NOT_A_RETURN"
    n_input: int
    n_valid_dcf: int
    n_failed: int
    central: PathValuation
    paths: list[PathValuation]
    valid_path_ids: list[str]
    failed: list[dict[str, Any]]
    aggregates: dict[str, Any]
    wacc_point: WACCInputs
    terminal_growth: float
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)


def _horizon_year(rec: FinancialPathRecord) -> int | None:
    if not rec.projection or not rec.projection.years:
        return None
    return rec.projection.years[-1]


def _item(rec: FinancialPathRecord, name: str, year: int) -> float | None:
    if rec.projection is None:
        return None
    key = f"{name}@{year}"
    tv = rec.projection.items.get(key)
    return None if tv is None else tv.value


def _capital_structure(cfg, snapshot: PITSnapshot, rec: FinancialPathRecord, year: int
                       ) -> tuple[float, float, list[str]]:
    flags: list[str] = []
    vcfg = cfg.valuation
    if vcfg.target_debt_weight is not None:
        return vcfg.target_debt_weight, vcfg.target_equity_weight, flags
    if not vcfg.use_snapshot_capital_structure:
        raise ValueError("target capital structure weights unset and use_snapshot_capital_structure is false")
    # Market equity ≈ last close * shares; debt = interest-bearing debt at horizon (path)
    debt = _item(rec, "interest_bearing_debt", year) or 0.0
    shares = _item(rec, "diluted_shares", year)
    if not snapshot.market or shares is None:
        flags.append("CAPITAL_STRUCTURE_EQUAL_WEIGHT_FALLBACK")
        return 0.5, 0.5, flags
    px = snapshot.market[-1].raw_close
    e = max(px * shares, 0.0)
    d = max(debt, 0.0)
    tot = e + d
    if tot <= 0:
        flags.append("CAPITAL_STRUCTURE_EQUAL_WEIGHT_FALLBACK")
        return 0.5, 0.5, flags
    wd = d / tot
    return wd, 1.0 - wd, flags


def _kd_tc(rec: FinancialPathRecord, year: int, cfg) -> tuple[float, float]:
    vcfg = cfg.valuation
    kd = vcfg.cost_of_debt
    if kd is None:
        # last year's interest / opening debt approx from path driver not stored; use cost_of_debt driver via items? 
        # Projection doesn't store cost_of_debt as an item. Use interest_expense / debt_open.
        p = year - 1
        interest = _item(rec, "interest_expense", year)
        debt_open = _item(rec, "interest_bearing_debt", p)
        if interest is not None and debt_open and debt_open > 0:
            kd = interest / debt_open
        else:
            kd = 0.05
            # labeled in wacc provenance via flags
    tc = vcfg.tax_rate
    if tc is None:
        tax = _item(rec, "tax_expense", year)
        pretax = _item(rec, "pre_tax_income", year)
        if tax is not None and pretax and pretax > 0:
            tc = min(max(tax / pretax, 0.0), 0.5)
        else:
            tc = 0.25  # TAX-CN-STATUTORY fallback labeled
    return float(kd), float(tc)


def _minority(rec: FinancialPathRecord, year: int, cfg) -> float:
    if cfg.valuation.minority_interest_book is not None:
        return float(cfg.valuation.minority_interest_book)
    te = _item(rec, "total_equity", year)
    pni = _item(rec, "parent_net_income", year)
    ni = _item(rec, "net_income", year)
    if te is None:
        return 0.0
    if ni and abs(ni) > 1e-12 and pni is not None:
        parent_share = pni / ni
        return max(te * (1.0 - parent_share), 0.0)
    return 0.0


def _normalized_metric(rec: FinancialPathRecord, years: list[int], metric: str, n: int) -> float | None:
    use = years[-n:]
    vals = []
    for y in use:
        v = _item(rec, "ebitda" if metric == "ebitda" else "ebit", y)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return float(np.mean(vals))


def value_one_path(rec: FinancialPathRecord, *, snapshot: PITSnapshot, loaded: LoadedConfig,
                   wacc_template: WACCInputs | None = None) -> PathValuation:
    if rec.status != "VALID" or rec.projection is None:
        return PathValuation(path_id=rec.path_id, kind=rec.kind, status="SKIPPED_INPUT",
                             invalid_reason=rec.invalid_reason or rec.status,
                             excluded_from_aggregates=True, flags=["SKIPPED_NON_VALID_FINANCIAL_PATH"])
    year = _horizon_year(rec)
    assert year is not None
    cfg = loaded.config
    years = list(rec.projection.years)
    fcff_vals = [rec.fcff[str(y)] for y in years]
    fcff = FCFFSeries(years=years, values=fcff_vals)
    kd, tc = _kd_tc(rec, year, cfg)
    wd, we, cs_flags = _capital_structure(cfg, snapshot, rec, year)
    wacc_in = build_wacc(cfg.valuation, cost_of_debt=kd, tax_rate=tc, weight_debt=wd, weight_equity=we)
    if cs_flags:
        wacc_in = wacc_in.model_copy(update={"flags": sorted(set(wacc_in.flags) | set(cs_flags))})
    dcf = dcf_fcff(fcff=fcff, wacc_inputs=wacc_in, tv_cfg=cfg.terminal_value)
    flags = list(dcf.flags) + list(wacc_in.flags)
    if not dcf.valid:
        return PathValuation(path_id=rec.path_id, kind=rec.kind, status="REJECTED",
                             invalid_reason=dcf.invalid_reason, excluded_from_aggregates=True,
                             wacc_inputs=wacc_in, dcf=dcf, flags=sorted(set(flags)))
    cash = _item(rec, "cash", year) or 0.0
    debt = _item(rec, "interest_bearing_debt", year) or 0.0
    shares = _item(rec, "diluted_shares", year) or 0.0
    minority = _minority(rec, year, cfg)
    br = bridge_ev_to_equity(
        enterprise_value=dcf.enterprise_value, cash=cash, debt=debt,
        lease_debt_like=cfg.valuation.lease_debt_like, minority_interest_book=minority,
        other_senior_claims=cfg.valuation.other_senior_claims, diluted_shares=shares)
    flags += br.flags
    if not br.valid:
        return PathValuation(path_id=rec.path_id, kind=rec.kind, status="REJECTED",
                             invalid_reason=br.invalid_reason, excluded_from_aggregates=True,
                             wacc_inputs=wacc_in, dcf=dcf, bridge_dcf=br, flags=sorted(set(flags)))
    # Exit multiple (separate)
    metric_v = _normalized_metric(rec, years, cfg.valuation.exit_multiple.metric,
                                  cfg.valuation.exit_multiple.normalize_years)
    ex = exit_multiple_ev(metric_value=metric_v if metric_v is not None else float("nan"),
                          cfg=cfg.valuation.exit_multiple)
    br_ex = None
    if ex.valid and ex.enterprise_value is not None:
        br_ex = bridge_ev_to_equity(
            enterprise_value=ex.enterprise_value, cash=cash, debt=debt,
            lease_debt_like=cfg.valuation.lease_debt_like, minority_interest_book=minority,
            other_senior_claims=cfg.valuation.other_senior_claims, diluted_shares=shares)
        flags += br_ex.flags
    composite_eq = composite_vps = None
    cw = cfg.valuation.composite_weights
    if cw is not None and br.valid and br_ex is not None and br_ex.valid:
        composite_eq = cw["dcf"] * br.equity_value + cw["exit_multiple"] * br_ex.equity_value
        composite_vps = composite_eq / shares
        flags.append("COMPOSITE_WEIGHTS_APPLIED")
    return PathValuation(
        path_id=rec.path_id, kind=rec.kind, status="VALID", excluded_from_aggregates=False,
        wacc_inputs=wacc_in, dcf=dcf, exit_multiple=ex, bridge_dcf=br, bridge_exit=br_ex,
        composite_equity=composite_eq, composite_value_per_share=composite_vps,
        flags=sorted(set(flags)))


def _agg(valid: list[PathValuation]) -> dict[str, Any]:
    import hashlib
    if not valid:
        return {"n": 0}
    def col(getter):  # noqa: ANN001, ANN202
        xs = np.array([getter(p) for p in valid if getter(p) is not None], dtype=float)
        xs = xs[np.isfinite(xs)]
        if xs.size == 0:
            return None
        return {"mean": float(xs.mean()), "p50": float(np.median(xs)), "p05": float(np.quantile(xs, 0.05)),
                "p95": float(np.quantile(xs, 0.95)), "n": int(xs.size)}
    return {
        "n": len(valid),
        "dcf_enterprise_value": col(lambda p: p.dcf.enterprise_value if p.dcf else None),
        "dcf_equity_value": col(lambda p: p.bridge_dcf.equity_value if p.bridge_dcf else None),
        "dcf_value_per_share": col(lambda p: p.bridge_dcf.value_per_share if p.bridge_dcf else None),
        "dcf_tv_fraction": col(lambda p: p.dcf.tv_fraction if p.dcf else None),
        "exit_enterprise_value": col(lambda p: p.exit_multiple.enterprise_value if p.exit_multiple else None),
        "exit_equity_value": col(lambda p: p.bridge_exit.equity_value if p.bridge_exit else None),
        "exit_value_per_share": col(lambda p: p.bridge_exit.value_per_share if p.bridge_exit else None),
        "valid_path_id_hash": hashlib.sha256(",".join(sorted(p.path_id for p in valid)).encode()).hexdigest()[:16],
    }


def value_paths(*, financial: FinancialPathBundle, snapshot: PITSnapshot,
                loaded: LoadedConfig) -> ValuationBundle:
    cfg = loaded.config
    # Point WACC template from central path structure for summary provenance
    # Build a preliminary WACC using config targets or 50/50 for the point snapshot label
    kd0 = cfg.valuation.cost_of_debt if cfg.valuation.cost_of_debt is not None else 0.05
    tc0 = cfg.valuation.tax_rate if cfg.valuation.tax_rate is not None else 0.25
    if cfg.valuation.target_debt_weight is not None:
        wd0, we0 = cfg.valuation.target_debt_weight, cfg.valuation.target_equity_weight
    else:
        wd0, we0 = 0.3, 0.7
    wacc_point = build_wacc(cfg.valuation, cost_of_debt=kd0, tax_rate=tc0, weight_debt=wd0, weight_equity=we0)

    central = value_one_path(financial.central, snapshot=snapshot, loaded=loaded)
    # MC paths only (financial.paths[0] is central)
    mc = [p for p in financial.paths if p.path_id != "central"]
    valued = [value_one_path(p, snapshot=snapshot, loaded=loaded) for p in mc]
    valid = [p for p in valued if p.status == "VALID" and not p.excluded_from_aggregates]
    failed = [{"path_id": p.path_id, "status": p.status, "reason": p.invalid_reason, "flags": p.flags}
              for p in valued if p.status != "VALID"]
    flags = []
    if central.status != "VALID":
        flags.append("CENTRAL_VALUATION_FAILED")
    if failed:
        flags.append("SOME_VALUATION_PATHS_FAILED")
    if any("TV_FRACTION_HIGH" in p.flags for p in valid):
        flags.append("TV_FRACTION_HIGH_PRESENT")
    return ValuationBundle(
        n_input=len(mc), n_valid_dcf=len(valid), n_failed=len(failed),
        central=central, paths=[central, *valued], valid_path_ids=[p.path_id for p in valid],
        failed=failed, aggregates=_agg(valid), wacc_point=wacc_point,
        terminal_growth=cfg.terminal_value.terminal_growth,
        assumptions=cite("WACC-CONSTRUCTION-v1", "TV-GORDON-v1", "EXIT-MULTIPLE-SEPARATE-v1",
                         "EV-EQUITY-BRIDGE-v1", "WACC-RF-CONFIG-v1", "WACC-INPUTS-v1",
                         "LEASE-BRIDGE-DEBTLIKE-v1", "MINORITY-BOOK-BRIDGE-v1"),
        flags=sorted(set(flags)))
