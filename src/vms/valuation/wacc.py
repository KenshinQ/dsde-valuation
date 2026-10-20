"""WACC construction (WACC-CONSTRUCTION-v1, WACC-RF-CONFIG-v1, WACC-BETA-SHRINK-v1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.schemas.config import ValuationConfig
from vms.statements.cashflows import CostOfEquity, WACC


class WACCInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    risk_free_rate: float
    erp: float
    beta_raw: float | None
    beta: float
    beta_prior: float
    beta_n_eff: float
    beta_shrink_strength: float
    cost_of_equity: float
    cost_of_debt: float
    tax_rate: float
    weight_debt: float
    weight_equity: float
    wacc: float
    provenance: dict[str, str]
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)


def shrink_beta(beta_raw: float, *, n_eff: float, prior: float, k: float) -> float:
    """beta = (n_eff * beta_raw + k * prior) / (n_eff + k)."""
    if n_eff + k <= 0:
        return prior
    return (n_eff * beta_raw + k * prior) / (n_eff + k)


def build_wacc(cfg: ValuationConfig, *, cost_of_debt: float, tax_rate: float,
               weight_debt: float, weight_equity: float,
               beta_raw: float | None = None) -> WACCInputs:
    """Assemble WACC from explicit config + path/snapshot-derived kd, tc, weights."""
    flags: list[str] = []
    prov: dict[str, str] = {
        "risk_free_rate": "config:valuation.risk_free_rate (WACC-RF-CONFIG-v1; not a live PIT adapter)",
        "erp": "config:valuation.erp",
    }
    raw = cfg.beta if beta_raw is None else beta_raw
    if raw is None:
        raw = cfg.beta_prior
        flags.append("BETA_PRIOR_ONLY")
        prov["beta"] = "config:valuation.beta_prior (no raw beta)"
        n_eff = 0.0
    else:
        n_eff = cfg.beta_n_eff
        prov["beta"] = ("config:valuation.beta" if beta_raw is None
                        else "provided beta series / raw")
    beta = shrink_beta(raw, n_eff=n_eff, prior=cfg.beta_prior, k=cfg.beta_shrink_strength)
    if cfg.cost_of_equity is not None:
        ke = cfg.cost_of_equity
        prov["cost_of_equity"] = "config:valuation.cost_of_equity (override)"
        flags.append("COST_OF_EQUITY_OVERRIDE")
    else:
        ke = cfg.risk_free_rate + beta * cfg.erp
        prov["cost_of_equity"] = "rf + beta * erp"
    kd = cost_of_debt
    prov["cost_of_debt"] = "path/driver or config"
    if cfg.cost_of_debt is not None:
        kd = cfg.cost_of_debt
        prov["cost_of_debt"] = "config:valuation.cost_of_debt"
    tc = tax_rate
    if cfg.tax_rate is not None:
        tc = cfg.tax_rate
        prov["tax_rate"] = "config:valuation.tax_rate"
    else:
        prov["tax_rate"] = "path/driver effective_tax_rate"
    wd, we = weight_debt, weight_equity
    if abs(wd + we - 1.0) > 1e-9:
        raise ValueError(f"weights must sum to 1; got wd={wd}, we={we}")
    prov["weights"] = "config target or snapshot market structure"
    wacc = we * ke + wd * kd * (1.0 - tc)
    return WACCInputs(
        risk_free_rate=cfg.risk_free_rate, erp=cfg.erp, beta_raw=raw, beta=beta,
        beta_prior=cfg.beta_prior, beta_n_eff=n_eff, beta_shrink_strength=cfg.beta_shrink_strength,
        cost_of_equity=ke, cost_of_debt=kd, tax_rate=tc, weight_debt=wd, weight_equity=we, wacc=wacc,
        provenance=prov, assumptions=cite("WACC-INPUTS-v1", "WACC-RF-CONFIG-v1", "WACC-BETA-SHRINK-v1",
                                          "WACC-CONSTRUCTION-v1"), flags=sorted(set(flags)))


def as_wacc(inp: WACCInputs) -> WACC:
    return WACC(rate=inp.wacc)


def as_cost_of_equity(inp: WACCInputs) -> CostOfEquity:
    return CostOfEquity(rate=inp.cost_of_equity)
