"""Shared helpers for Phase-4 cash-flow method plugins."""

from __future__ import annotations

from typing import Any, Callable, Iterable

import numpy as np

from vms.methods.eligibility import EligibilityResult, GateReason, evaluate_hard_gates
from vms.methods.protocol import MethodResult, ValuationContext
from vms.schemas.config import LoadedConfig, TerminalValueConfig
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry, ProfileFlag
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord
from vms.valuation.wacc import WACCInputs, build_wacc  # build_wacc used by point_wacc


def is_statement_bundle(obj: Any) -> bool:
    return isinstance(obj, FinancialPathBundle)


def require_statement_bundle(obj: Any) -> FinancialPathBundle | MethodResult:
    if isinstance(obj, FinancialPathBundle):
        return obj
    return MethodResult(
        method_id="unknown",
        status=MethodEligibilityStatus.INELIGIBLE,
        reason_codes=["PATH_BUNDLE_REQUIRED"],
        detail="Phase 4 methods require statements.FinancialPathBundle; refusing empty/placeholder paths",
    )


def base_eligibility(entry: MethodRegistryEntry, context: ValuationContext) -> EligibilityResult:
    return evaluate_hard_gates(entry, context)


def append_gate(result: EligibilityResult, reason: GateReason) -> EligibilityResult:
    reasons = list(result.reasons) + [reason]
    hard_pass = result.eligible and reason.passed
    status = MethodEligibilityStatus.VALID if hard_pass else MethodEligibilityStatus.INELIGIBLE
    return result.model_copy(update={
        "reasons": reasons,
        "eligible": hard_pass,
        "status": status,
    })


def flag_exclusion(entry: MethodRegistryEntry, context: ValuationContext, elig: EligibilityResult) -> EligibilityResult:
    """Apply flag-based exclusion_conditions like flag:CURRENT_FCF_NEGATIVE."""
    primary_flags = {f.value for f in context.profile.flags}
    for cond in entry.exclusion_conditions:
        if cond.startswith("flag:"):
            flag = cond.split(":", 1)[1]
            hit = flag in primary_flags
            elig = append_gate(elig, GateReason(
                code="FLAG_EXCLUSION",
                detail=f"exclusion {cond}; present={hit}",
                passed=not hit,
            ))
    return elig


def point_wacc(loaded: LoadedConfig) -> WACCInputs:
    cfg = loaded.config.valuation
    kd = cfg.cost_of_debt if cfg.cost_of_debt is not None else 0.05
    tc = cfg.tax_rate if cfg.tax_rate is not None else 0.25
    if cfg.target_debt_weight is not None:
        wd, we = cfg.target_debt_weight, cfg.target_equity_weight
    else:
        wd, we = 0.3, 0.7
    return build_wacc(cfg, cost_of_debt=kd, tax_rate=tc, weight_debt=wd, weight_equity=we)


def ordered_years(rec: FinancialPathRecord) -> list[int]:
    if rec.projection and rec.projection.years:
        return list(rec.projection.years)
    keys = set(rec.fcff) | set(rec.fcfe) | set(rec.dividends)
    return sorted(int(k) for k in keys)


def series_for(rec: FinancialPathRecord, field: str, years: list[int]) -> list[float]:
    data = getattr(rec, field)
    return [float(data[str(y)]) for y in years]


def valid_records(bundle: FinancialPathBundle) -> list[FinancialPathRecord]:
    return [r for r in bundle.paths if r.status == "VALID" and not r.excluded_from_aggregates]


def agg_floats(xs: Iterable[float | None]) -> dict[str, Any] | None:
    arr = np.array([x for x in xs if x is not None and np.isfinite(x)], dtype=float)
    if arr.size == 0:
        return None
    return {
        "mean": float(arr.mean()),
        "p50": float(np.median(arr)),
        "p05": float(np.quantile(arr, 0.05)),
        "p95": float(np.quantile(arr, 0.95)),
        "n": int(arr.size),
    }


def rate_sensitivities(
    *,
    base_rate: float,
    g: float,
    tv_cfg: TerminalValueConfig,
    recompute: Callable[[float, float], float | None],
    rate_shock: float = 0.01,
    g_shock: float | None = None,
) -> dict[str, Any]:
    """Key WACC/ke and terminal-growth sensitivities (SPEC §16.1 / Phase 4 AC5)."""
    g_shock = tv_cfg.terminal_growth * 0 + (0.005 if g_shock is None else g_shock)
    # Use configured diagnostic shocks when available
    out: dict[str, Any] = {"base_rate": base_rate, "base_g": g, "rate_shock": rate_shock, "g_shock": g_shock}
    for label, rate, gg in (
        ("rate_plus", base_rate + rate_shock, g),
        ("rate_minus", max(base_rate - rate_shock, g + tv_cfg.min_wacc_minus_g + 1e-6), g),
        ("g_plus", base_rate, min(g + g_shock, tv_cfg.max_terminal_growth)),
        ("g_minus", base_rate, g - g_shock),
    ):
        val = recompute(rate, gg)
        out[label] = val
    return out


def horizon_bridge_inputs(rec: FinancialPathRecord, loaded: LoadedConfig) -> dict[str, float]:
    years = ordered_years(rec)
    year = years[-1]
    cash = rec.cash.get(str(year), 0.0)
    debt = rec.debt.get(str(year), 0.0)
    shares = rec.shares.get(str(year), 0.0)
    minority = loaded.config.valuation.minority_interest_book
    if minority is None:
        minority = 0.0
    return {
        "cash": float(cash or 0.0),
        "debt": float(debt or 0.0),
        "diluted_shares": float(shares or 0.0),
        "lease_debt_like": float(loaded.config.valuation.lease_debt_like),
        "minority_interest_book": float(minority),
        "other_senior_claims": float(loaded.config.valuation.other_senior_claims),
    }


def has_profile_flag(context: ValuationContext, flag: ProfileFlag | str) -> bool:
    name = flag.value if isinstance(flag, ProfileFlag) else flag
    return any(f.value == name for f in context.profile.flags)
