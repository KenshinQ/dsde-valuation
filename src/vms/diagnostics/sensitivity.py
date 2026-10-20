"""Sensitivity & uncertainty attribution (SPEC §14, Phase 8)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.data.io import LoadResult
from vms.diagnostics.metrics import delta, return_metrics, valuation_metrics
from vms.diagnostics.perturb import (ablation_driver_to_central, boost_transition_stay, driver_means,
                                     shock_driver_bundle, tilt_posterior, with_valuation_shocks)
from vms.pipeline import Phase7Run, run_returns
from vms.returns import build_return_distributions
from vms.sampling import simulate_paths
from vms.schemas.config import LoadedConfig
from vms.statements.paths import project_financial_paths
from vms.valuation import value_paths

DIAG_VERSION = "SENS-1"
COMPARE_KEYS = ["mean_vps_dcf", "central_vps_dcf", "mean_tv_fraction", "mean_vps_exit",
                "dcf_minus_exit_central_vps"]
RET_KEYS = ["mean_return", "p_loss", "cvar_0.95", "p05_return"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SensitivityCase(_M):
    case_id: str
    kind: Literal["baseline", "oat", "joint", "ablation", "process_vs_param", "method", "policy"]
    dimension: str
    description: str
    intended_inputs: list[str]
    shock: dict[str, Any]
    isolation_check: dict[str, Any] | None = None
    valuation: dict[str, Any]
    returns: dict[str, Any]
    deltas_vs_baseline: dict[str, Any]


class SensitivityReport(_M):
    schema_kind: Literal["SensitivityReport"] = "SensitivityReport"
    version: str = DIAG_VERSION
    label: str = "SENSITIVITY_AND_UNCERTAINTY_ATTRIBUTION"
    baseline_run_ref: dict[str, Any]
    seed: int
    n_paths: int
    n_years: int
    cases: list[SensitivityCase]
    dominant_assumptions: list[dict[str, Any]]
    process_vs_parameter: dict[str, Any]
    dcf_vs_multiple: dict[str, Any]
    terminal_value_contribution: dict[str, Any]
    driver_attribution: list[dict[str, Any]]
    interval_labeling: dict[str, Any]
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    content_hash: str


@dataclass
class _Ctx:
    load: LoadResult
    instrument_id: str
    as_of: datetime
    loaded: LoadedConfig
    seed: int
    n_paths: int
    n_years: int
    spot: float
    mode: str
    override_reason: str | None
    baseline: Phase7Run


def _eval_from_bundle(ctx: _Ctx, bundle, *, loaded: LoadedConfig | None = None,
                      policy_id: str | None = None, regimes=None) -> tuple[dict, dict]:
    loaded = loaded or ctx.loaded
    base = ctx.baseline
    assert base.central is not None and base.resolution is not None and base.history is not None
    fp = project_financial_paths(
        bundle=bundle, snapshot=base.snapshot, history=base.history, drivers=base.central,
        resolution=base.resolution, profile=loaded.profile, proj_cfg=loaded.config.projection,
        ca_cfg=loaded.config.capital_allocation, policy_id=policy_id,
        mode="exploratory", override_reason=ctx.override_reason or "phase8_sensitivity")
    val = value_paths(financial=fp, snapshot=base.snapshot, loaded=loaded)
    rets = build_return_distributions(
        valuation=val, financial=fp, loaded=loaded, spot_price=ctx.spot,
        horizons_years=[min(ctx.n_years, max(loaded.config.horizons_years))],
        simulation=bundle, regimes=regimes if regimes is not None else base.regimes)
    return valuation_metrics(val), return_metrics(rets)


def _resimulate(ctx: _Ctx, *, regimes=None, parameter_mode: str = "resampled"):
    base = ctx.baseline
    assert base.regimes is not None and base.distributions is not None
    assert base.bundle is not None
    cfg = ctx.loaded.config
    return simulate_paths(
        regimes=regimes if regimes is not None else base.regimes,
        distributions=base.distributions, profile=ctx.loaded.profile,
        n_paths=ctx.n_paths, n_years=ctx.n_years, seed=ctx.seed,
        mc=cfg.monte_carlo, est=cfg.estimation, base_year=base.bundle.base_year,
        check_seed_stability=cfg.sensitivity.check_seed_stability,
        mode="exploratory", override_reason=ctx.override_reason or "phase8_sensitivity",
        parameter_mode=parameter_mode)


def _case(case_id, kind, dimension, description, intended, shock, v_m, r_m, base_v, base_r,
          isolation=None) -> SensitivityCase:
    d_v = delta(base_v, v_m, COMPARE_KEYS)
    d_r = delta(base_r, r_m, RET_KEYS)
    return SensitivityCase(
        case_id=case_id, kind=kind, dimension=dimension, description=description,
        intended_inputs=intended, shock=shock, isolation_check=isolation,
        valuation=v_m, returns=r_m,
        deltas_vs_baseline={"valuation": d_v, "returns": d_r})


def run_diagnostics(*, load: LoadResult, instrument_id: str, as_of: datetime, loaded: LoadedConfig,
                    seed: int, n_paths: int | None = None, n_years: int | None = None,
                    spot_price: float | None = None, baseline: Phase7Run | None = None,
                    mode: Literal["production", "exploratory"] = "exploratory",
                    override_reason: str | None = "phase8_sensitivity_diagnostics") -> SensitivityReport:
    """Build a reproducible SensitivityReport (same seed/config/data => same content_hash)."""
    cfg = loaded.config
    sc = cfg.sensitivity
    paths = n_paths if n_paths is not None else sc.n_paths
    years = n_years if n_years is not None else max(cfg.horizons_years)
    if baseline is None:
        baseline = run_returns(load, instrument_id=instrument_id, as_of=as_of, loaded=loaded, seed=seed,
                               n_paths=paths, n_years=years, mode=mode, override_reason=override_reason,
                               spot_price=spot_price)
    if baseline.valuation is None or baseline.bundle is None or baseline.returns is None:
        raise ValueError("baseline run missing valuation/bundle/returns (unsupported profile?)")
    spot = spot_price if spot_price is not None else (
        baseline.spot_price if baseline.spot_price is not None else float(baseline.snapshot.market[-1].raw_close))
    ctx = _Ctx(load=load, instrument_id=instrument_id, as_of=as_of, loaded=loaded, seed=seed,
               n_paths=paths, n_years=years, spot=spot, mode=mode, override_reason=override_reason,
               baseline=baseline)

    base_v = valuation_metrics(baseline.valuation)
    base_r = return_metrics(baseline.returns)
    base_means = driver_means(baseline.bundle)
    cases: list[SensitivityCase] = []
    cases.append(_case("baseline", "baseline", "none", "Unperturbed baseline", [], {}, base_v, base_r, base_v, base_r))

    # ---- OAT driver shocks (pathwise; isolation verified) ----
    for driver, shock in sc.oat_driver_shocks.items():
        shocked, meta = shock_driver_bundle(baseline.bundle, driver, shock)
        after = driver_means(shocked)
        isolation = {
            "method": "year1_driver_means_vs_baseline",
            "shocked_driver_mean_delta": after.get(driver, 0) - base_means.get(driver, 0),
            "other_driver_max_abs_delta": max(
                (abs(after.get(k, 0) - base_means.get(k, 0)) for k in base_means if k != driver), default=0.0),
            "pass": all(abs(after.get(k, 0) - base_means.get(k, 0)) < 1e-12 for k in base_means if k != driver),
        }
        v_m, r_m = _eval_from_bundle(ctx, shocked)
        cases.append(_case(f"oat:{driver}", "oat", driver,
                           f"OAT +{shock} on path driver {driver}", [driver], meta, v_m, r_m, base_v, base_r,
                           isolation))

    # ---- OAT valuation / TV / exit multiple ----
    for label, kw, keys in [
        ("cost_of_equity", {"cost_of_equity_delta": sc.wacc_shock}, ["cost_of_equity"]),
        ("terminal_growth", {"terminal_growth_delta": sc.terminal_growth_shock}, ["terminal_growth"]),
        ("exit_multiple", {"exit_multiple_delta": sc.exit_multiple_shock}, ["exit_multiple"]),
    ]:
        alt_loaded = with_valuation_shocks(loaded, **kw)
        v_m, r_m = _eval_from_bundle(ctx, baseline.bundle, loaded=alt_loaded)
        cases.append(_case(f"oat:{label}", "oat", label, f"OAT shock on {label}", keys, kw, v_m, r_m, base_v, base_r))

    # ---- policy ----
    alt_policy = sc.policy_alt
    if alt_policy != cfg.capital_allocation.default_policy:
        v_m, r_m = _eval_from_bundle(ctx, baseline.bundle, policy_id=alt_policy)
        cases.append(_case(f"oat:policy:{alt_policy}", "policy", "capital_allocation_policy",
                           f"Re-project with policy {alt_policy}", ["capital_allocation.policy"],
                           {"policy": alt_policy}, v_m, r_m, base_v, base_r))

    # ---- posterior tilt (re-simulate) ----
    if baseline.regimes is not None and sc.posterior_tilt_state in baseline.regimes.current.states:
        tilted = tilt_posterior(baseline.regimes, sc.posterior_tilt_state, sc.posterior_tilt)
        bun = _resimulate(ctx, regimes=tilted)
        v_m, r_m = _eval_from_bundle(ctx, bun, regimes=tilted)
        cases.append(_case("oat:posterior", "oat", "fundamental_state_posterior",
                           f"Tilt posterior toward {sc.posterior_tilt_state} by {sc.posterior_tilt}",
                           ["regimes.current.probabilities"], {"state": sc.posterior_tilt_state, "tilt": sc.posterior_tilt},
                           v_m, r_m, base_v, base_r))

    # ---- transition stay boost (re-simulate) ----
    if baseline.regimes is not None:
        boosted = boost_transition_stay(baseline.regimes, sc.transition_stay_boost)
        bun = _resimulate(ctx, regimes=boosted)
        v_m, r_m = _eval_from_bundle(ctx, bun, regimes=boosted)
        cases.append(_case("oat:transitions", "oat", "state_transition_probabilities",
                           f"Boost Dirichlet stay counts by {sc.transition_stay_boost}",
                           ["regimes.transitions.posterior_alpha"], {"stay_boost": sc.transition_stay_boost},
                           v_m, r_m, base_v, base_r))

    # ---- joint scenarios ----
    joint_specs = [
        ("joint:growth_margin", ["revenue_growth", "ebit_margin"],
         {k: sc.oat_driver_shocks[k] for k in ("revenue_growth", "ebit_margin") if k in sc.oat_driver_shocks}),
        ("joint:capex_wc", ["capex_to_revenue", "receivables_to_revenue"],
         {k: sc.oat_driver_shocks[k] for k in ("capex_to_revenue", "receivables_to_revenue") if k in sc.oat_driver_shocks}),
        ("joint:wacc_g", ["cost_of_equity", "terminal_growth"],
         {"cost_of_equity_delta": sc.wacc_shock, "terminal_growth_delta": sc.terminal_growth_shock}),
    ]
    for cid, dims, shocks in joint_specs:
        if not shocks:
            continue
        if "cost_of_equity_delta" in shocks:
            alt_loaded = with_valuation_shocks(loaded, **shocks)
            v_m, r_m = _eval_from_bundle(ctx, baseline.bundle, loaded=alt_loaded)
        else:
            bun = baseline.bundle
            for d, sh in shocks.items():
                bun, _ = shock_driver_bundle(bun, d, sh)
            v_m, r_m = _eval_from_bundle(ctx, bun)
        cases.append(_case(cid, "joint", "+".join(dims), f"Joint scenario on {dims}", dims, shocks,
                           v_m, r_m, base_v, base_r))

    # ---- driver attribution (pathwise ablation to central year-1 mean) ----
    attribution = []
    for driver in ("revenue_growth", "ebit_margin", "capex_to_revenue", "diluted_share_growth"):
        if driver not in base_means:
            continue
        abl = ablation_driver_to_central(baseline.bundle, driver, base_means[driver])
        # wait - ablating TO the mean of MC paths removes cross-path variation in that driver
        # better: ablate to CENTRAL path's year-1 value
        cval = baseline.bundle.central.years[0].drivers.get(driver, base_means[driver])
        abl = ablation_driver_to_central(baseline.bundle, driver, float(cval))
        v_m, r_m = _eval_from_bundle(ctx, abl)
        d_mean = (base_v.get("mean_vps_dcf") or 0) - (v_m.get("mean_vps_dcf") or 0)
        d_ploss = (base_r.get("p_loss") or 0) - (r_m.get("p_loss") or 0)
        attribution.append({
            "driver": driver,
            "method": "pathwise_ablation_to_central_year1",
            "central_value": cval,
            "delta_mean_vps_dcf_removed": d_mean,
            "delta_p_loss_removed": d_ploss,
            "note": "Contribution ≈ baseline − ablation; simple pathwise ablation, not Shapley.",
        })
        cases.append(_case(f"ablation:{driver}", "ablation", driver,
                           f"Ablate {driver} to central year-1 value", [driver],
                           {"ablation_value": cval}, v_m, r_m, base_v, base_r))

    # ---- process vs parameter ----
    bun_fixed = _resimulate(ctx, parameter_mode="fixed")
    v_fixed, r_fixed = _eval_from_bundle(ctx, bun_fixed)
    cases.append(_case("param_fixed", "process_vs_param", "parameter_uncertainty",
                       "Process uncertainty only (parameter draws fixed to point estimates)",
                       ["parameter_mode"], {"parameter_mode": "fixed"}, v_fixed, r_fixed, base_v, base_r))
    # baseline is resampled; also explicit resampled re-sim for symmetry
    bun_resamp = _resimulate(ctx, parameter_mode="resampled")
    v_res, r_res = _eval_from_bundle(ctx, bun_resamp)
    pvp = {
        "method": "compare_parameter_mode_fixed_vs_resampled_same_seed_process_draws",
        "fixed": {"valuation": v_fixed, "returns": r_fixed},
        "resampled": {"valuation": v_res, "returns": r_res},
        "delta_mean_vps_dcf": (v_res.get("mean_vps_dcf") or 0) - (v_fixed.get("mean_vps_dcf") or 0),
        "delta_p_loss": (r_res.get("p_loss") or 0) - (r_fixed.get("p_loss") or 0),
        "delta_cvar_0.95": (
            None if r_res.get("cvar_0.95") is None or r_fixed.get("cvar_0.95") is None
            else r_res["cvar_0.95"] - r_fixed["cvar_0.95"]
        ),
        "interpretation": "Difference approximates parameter-uncertainty contribution on top of process noise.",
    }

    # ---- DCF vs multiple / TV from baseline ----
    dcf_vs = {
        "central_vps_dcf": base_v.get("central_vps_dcf"),
        "central_vps_exit": base_v.get("central_vps_exit"),
        "dcf_minus_exit_central_vps": base_v.get("dcf_minus_exit_central_vps"),
        "mean_vps_dcf": base_v.get("mean_vps_dcf"),
        "mean_vps_exit": base_v.get("mean_vps_exit"),
        "note": "Methods kept separate (EXIT-MULTIPLE-SEPARATE-v1); comparison is descriptive, not a composite.",
    }
    tv_block = {
        "mean_tv_fraction": base_v.get("mean_tv_fraction"),
        "central_tv_fraction": base_v.get("central_tv_fraction"),
        "terminal_growth_shock_case": next((c.deltas_vs_baseline for c in cases if c.case_id == "oat:terminal_growth"), None),
        "note": "TV/EV fraction from Phase 6; g-shock OAT shows terminal-assumption sensitivity.",
    }

    # ---- dominant assumptions by |delta mean_vps| and |delta p_loss| ----
    ranked = []
    for c in cases:
        if c.kind == "baseline":
            continue
        dv = (c.deltas_vs_baseline.get("valuation") or {}).get("mean_vps_dcf") or {}
        dr = (c.deltas_vs_baseline.get("returns") or {}).get("p_loss") or {}
        ranked.append({
            "case_id": c.case_id,
            "dimension": c.dimension,
            "abs_delta_mean_vps_dcf": abs(dv.get("delta") or 0),
            "abs_delta_p_loss": abs(dr.get("delta") or 0),
            "delta_cvar_0.95": ((c.deltas_vs_baseline.get("returns") or {}).get("cvar_0.95") or {}).get("delta"),
        })
    ranked.sort(key=lambda x: x["abs_delta_mean_vps_dcf"], reverse=True)
    dominant = ranked[:8]

    interval_labeling = {
        "rule": "MC_PERCENTILE_NOT_CI",
        "statement": ("Monte Carlo p05/p95 bands are empirical percentile intervals across simulated paths. "
                      "They are NOT statistical confidence intervals for a fixed estimand unless a separate "
                      "construction (e.g. bootstrap CI for a parameter) is explicitly documented."),
        "fields_using_this_label": [
            "valuation.vps_dcf_mc_percentile_interval_05_95",
            "returns.return_mc_percentile_interval_05_95",
        ],
    }

    flags = []
    oat_fail = [c.case_id for c in cases if c.isolation_check and not c.isolation_check.get("pass", True)]
    if oat_fail:
        flags.append("OAT_ISOLATION_FAILED:" + ",".join(oat_fail))
    if any((c.returns or {}).get("cvar_0.95") is not None for c in cases):
        flags.append("TAIL_RISK_SENSITIVITY_INCLUDED")

    payload_for_hash = {
        "seed": seed, "n_paths": paths, "n_years": years, "spot": spot,
        "cases": [c.model_dump(mode="json") for c in cases],
        "pvp": pvp, "dominant": dominant,
    }
    content_hash = hashlib.sha256(
        json.dumps(payload_for_hash, sort_keys=True, allow_nan=False, default=str).encode()
    ).hexdigest()[:16]

    return SensitivityReport(
        baseline_run_ref={
            "instrument_id": instrument_id,
            "as_of": as_of.isoformat(),
            "seed": seed,
            "n_valid_dcf": baseline.valuation.n_valid_dcf,
            "valuation_path_hash": baseline.valuation.aggregates.get("valid_path_id_hash"),
        },
        seed=seed, n_paths=paths, n_years=years, cases=cases,
        dominant_assumptions=dominant, process_vs_parameter=pvp,
        dcf_vs_multiple=dcf_vs, terminal_value_contribution=tv_block,
        driver_attribution=attribution, interval_labeling=interval_labeling,
        assumptions=cite(
            "SENS-OAT-ISOLATION-v1", "SENS-MC-PERCENTILE-NOT-CI-v1", "SENS-PROCESS-VS-PARAM-v1",
            "SENS-DRIVER-ABLATION-v1", "EXIT-MULTIPLE-SEPARATE-v1", "TV-GORDON-v1",
            "PARAM-BOOTSTRAP-COUPLED-v1", "WACC-CONSTRUCTION-v1", "DIVIDEND-NO-REINVEST-v1",
        ),
        flags=sorted(set(flags)),
        notes=[
            "OAT driver shocks modify only the named driver on frozen baseline paths (isolation_check).",
            "Driver attribution uses simple pathwise ablation to central year-1 value (not Shapley).",
            "Process vs parameter: parameter_mode=fixed vs resampled at the same seed.",
            "All percentile bands are Monte Carlo percentile intervals, not confidence intervals.",
            "Reports are reproducible: same seed/config/data => same content_hash.",
        ],
        content_hash=content_hash,
    )
