"""Side-by-side valuation / forecast baselines at a PIT origin (SPEC §17.3)."""

from __future__ import annotations

import math
import statistics
from typing import Any

from vms.assumptions import cite
from vms.drivers.history import AnnualHistory
from vms.equity_bridge.bridge import bridge_ev_to_equity
from vms.pipeline import run_projection
from vms.schemas.config import LoadedConfig
from vms.statements.cashflows import FCFFSeries
from vms.valuation.dcf import dcf_fcff
from vms.valuation.multiples import exit_multiple_ev
from vms.valuation.wacc import build_wacc

def _item(proj, name: str, year: int, default: float | None = None) -> float | None:
    tv = proj.items.get(f"{name}@{year}")
    if tv is None:
        return default
    return float(tv.value)


def _last_fcff_proxy(proj) -> float | None:
    if proj.fcff is None or not proj.fcff.values:
        # try items
        if not proj.years:
            return None
        y = proj.years[0] - 1  # base year sometimes stored
        key = f"fcff@{proj.years[0]}"
        if key in proj.items:
            return proj.items[key].value
        return None
    return float(proj.fcff.values[0]) if proj.fcff.values else None


def _series_fcff(proj) -> FCFFSeries | None:
    if proj is None or proj.status != "VALID" or not proj.years:
        return None
    vals = []
    for y in proj.years:
        tv = proj.items.get(f"fcff@{y}")
        if tv is None:
            return None
        vals.append(tv.value)
    return FCFFSeries(years=list(proj.years), values=vals)


def _historical_realized_fcff_samples(history: AnnualHistory | None) -> list[float]:
    """As-of-visible FY FCFF proxies: CFO − capex − acquisitions_net (same as outcomes).

    Uses only AnnualHistory already extracted from the PIT snapshot at origin — no
    future FY may appear here. Empty when no CFO observations exist.
    """
    if history is None:
        return []
    out: list[float] = []
    for y in history.years:
        cfo = history.value(y, "cash_flow_from_operations")
        if cfo is None or not math.isfinite(cfo):
            continue
        capex = history.value(y, "capex")
        acq = history.value(y, "acquisitions_net")
        capex_v = 0.0 if capex is None else float(capex)
        acq_v = 0.0 if acq is None else float(acq)
        out.append(float(cfo) - capex_v - acq_v)
    return out


def _bridge_vps(ev: float, proj, loaded: LoadedConfig, year: int) -> float | None:
    cash = _item(proj, "cash", year, 0.0) or 0.0
    debt = _item(proj, "interest_bearing_debt", year, 0.0) or 0.0
    shares = _item(proj, "diluted_shares", year, 0.0) or 0.0
    br = bridge_ev_to_equity(
        enterprise_value=ev, cash=cash or 0.0, debt=debt or 0.0,
        lease_debt_like=loaded.config.valuation.lease_debt_like,
        minority_interest_book=loaded.config.valuation.minority_interest_book or 0.0,
        other_senior_claims=loaded.config.valuation.other_senior_claims,
        diluted_shares=shares or 0.0)
    return br.value_per_share if br.valid else None


def build_baselines(*, load, instrument_id, as_of, loaded: LoadedConfig, spot: float,
                    horizon_years: int = 1) -> dict[str, Any]:
    """Compute point baselines at origin. No future data may be read here."""
    flags: list[str] = []
    assumptions = cite("TV-GORDON-v1", "WACC-CONSTRUCTION-v1", "EXIT-MULTIPLE-SEPARATE-v1",
                       "EV-EQUITY-BRIDGE-v1", "DRIVER-CENTRAL-MEDIAN-v1")
    run = run_projection(load, instrument_id=instrument_id, as_of=as_of, loaded=loaded,
                         years=max(horizon_years, loaded.config.projection.default_years),
                         mode="exploratory", override_reason="phase11_baseline_origin")
    profile_id = None
    if getattr(loaded, "profile", None) is not None:
        profile_id = getattr(loaded.profile, "profile_id", None)
    out: dict[str, Any] = {
        "origin_as_of": as_of.isoformat(),
        "spot_price": spot,
        "profile": run.resolution.status.value,
        "profile_id": profile_id or "UNKNOWN",
        "fundamental_regime": None,  # filled by caller when regime posterior available
        "projection_status": run.projection.status,
        "baselines": {},
        "forecasts": {},
        "flags": flags,
        "assumptions": assumptions,
        "pit_complete": run.snapshot.pit_complete,
    }
    if run.projection.status != "VALID" or run.drivers is None:
        flags.append("BASELINE_PROJECTION_INVALID")
        out["flags"] = flags
        return out

    proj = run.projection
    fcff = _series_fcff(proj)
    cfg = loaded.config
    kd = cfg.valuation.cost_of_debt if cfg.valuation.cost_of_debt is not None else 0.05
    tc = cfg.valuation.tax_rate if cfg.valuation.tax_rate is not None else 0.25
    wd = cfg.valuation.target_debt_weight if cfg.valuation.target_debt_weight is not None else 0.3
    we = cfg.valuation.target_equity_weight if cfg.valuation.target_equity_weight is not None else 0.7
    wacc_in = build_wacc(cfg.valuation, cost_of_debt=kd, tax_rate=tc, weight_debt=wd, weight_equity=we)

    # 1) Deterministic central-case DCF
    central = {"label": "deterministic_central_dcf", "vps": None, "ev": None, "fcff_path": None, "tv_fraction": None}
    if fcff is not None:
        dcf = dcf_fcff(fcff=fcff, wacc_inputs=wacc_in, tv_cfg=cfg.terminal_value)
        if dcf.valid and dcf.enterprise_value is not None:
            yH = proj.years[min(horizon_years, len(proj.years)) - 1]
            vps = _bridge_vps(dcf.enterprise_value, proj, loaded, yH)
            central.update({"ev": dcf.enterprise_value, "vps": vps, "tv_fraction": dcf.tv_fraction,
                            "fcff_path": list(fcff.values), "wacc": wacc_in.wacc, "g": dcf.g})
    out["baselines"]["central_dcf"] = central

    # 2) Historical driver medians + independent realized-FCFF median baseline.
    #    fcff_y1 MUST NOT equal projected median-driver FCFF_y1 (that is the forecast OCF).
    hist = {
        "label": "historical_realized_fcff_median",
        "revenue_growth_median": None,
        "ebit_margin_median": None,
        "fcff_y1": None,
        "fcff_y1_n": 0,
        "fcff_y1_definition": (
            "Median of as-of-visible FY realized FCFF proxies "
            "(CFO − capex − acquisitions_net), matching outcomes.operating_cash_flow.fcff_proxy. "
            "Independent of the median-driver projection used for forecasts.operating_cash_flow."
        ),
    }
    if run.drivers is not None:
        for name in ("revenue_growth", "ebit_margin"):
            est = run.drivers.estimates.get(name)
            if est is not None:
                hist[f"{name}_median"] = est.value
    hist_fcff_samples = _historical_realized_fcff_samples(run.history)
    if hist_fcff_samples:
        hist["fcff_y1"] = float(statistics.median(hist_fcff_samples))
        hist["fcff_y1_n"] = len(hist_fcff_samples)
    else:
        flags.append("HISTORICAL_REALIZED_FCFF_EMPTY")
    out["baselines"]["historical_median"] = hist

    # 3) No-regime: Gordon on last observed FCFF proxy with pooled g = terminal_growth (no regime path)
    no_reg = {"label": "no_regime_constant_growth", "vps": None, "ev": None}
    # use year-1 projected FCFF as FCFF_1, then grow at g forever from there as simple model
    if fcff is not None and fcff.values:
        g = cfg.terminal_value.terminal_growth
        w = wacc_in.wacc
        if w - g >= cfg.terminal_value.min_wacc_minus_g:
            # EV_0 = FCFF_1/(WACC-g)  (single-stage, no multi-year path)
            ev = fcff.values[0] / (w - g)
            yH = proj.years[0]
            no_reg.update({"ev": ev, "vps": _bridge_vps(ev, proj, loaded, yH), "wacc": w, "g": g})
    out["baselines"]["no_regime"] = no_reg

    # 4) Simple constant-growth DCF (same formula, labeled separately; uses terminal_growth)
    out["baselines"]["constant_growth_dcf"] = {
        "label": "simple_constant_growth_dcf",
        **{k: no_reg.get(k) for k in ("ev", "vps", "wacc", "g")},
        "note": "EV=FCFF_y1/(WACC-g); identical mechanics to no_regime baseline in VMS-0.1 offline.",
    }

    # 5) DCF-only vs DCF+multiple (exit multiple on normalized metric)
    ebitda0 = _item(proj, "ebitda", proj.years[0])
    em = exit_multiple_ev(
        metric_value=float("nan") if ebitda0 is None else ebitda0,
        cfg=cfg.valuation.exit_multiple)
    y0 = proj.years[0]
    exit_vps = None if not (em.valid and em.enterprise_value is not None) else _bridge_vps(em.enterprise_value, proj, loaded, y0)
    out["baselines"]["exit_multiple"] = {
        "label": "sector_multiple_benchmark",
        "ev": em.enterprise_value if em.valid else None,
        "vps": exit_vps,
        "multiple": em.multiple_used if em.valid else None,
    }
    out["baselines"]["dcf_only"] = {"label": "dcf_only", "vps": central.get("vps"), "ev": central.get("ev")}
    # DCF + multiple descriptive composite only if weights set; else keep separate
    cw = cfg.valuation.composite_weights
    if cw is not None and central.get("vps") is not None and exit_vps is not None:
        comp = cw["dcf"] * central["vps"] + cw["exit_multiple"] * exit_vps
        out["baselines"]["dcf_plus_multiple"] = {"label": "dcf_plus_multiple_weighted", "vps": comp, "weights": cw}
    else:
        out["baselines"]["dcf_plus_multiple"] = {
            "label": "dcf_and_multiple_separate",
            "vps_dcf": central.get("vps"),
            "vps_exit": exit_vps,
            "note": "composite_weights null — methods kept separate (EXIT-MULTIPLE-SEPARATE-v1)",
        }

    # 6) Current-multiple persistence for exit pricing (SPEC §17.3)
    # As-of trading multiple = spot / (EBITDA_y0 / shares_y0); apply to horizon-year metric.
    # This is an EXIT-PRICE baseline, not an intrinsic-value claim.
    persist: dict[str, Any] = {
        "label": "current_multiple_persistence",
        "current_multiple": None,
        "metric": "price_to_ebitda_per_share",
        "exit_price_point": None,
        "note": (
            "Exit-price baseline: hold the as-of price / (EBITDA/shares) multiple constant "
            "and apply it to the horizon-year EBITDA/shares. Separate from intrinsic "
            "valuation (SPEC §17.3)."
        ),
    }
    y0 = proj.years[0]
    yH = proj.years[min(horizon_years, len(proj.years)) - 1]
    ebitda0 = _item(proj, "ebitda", y0)
    shares0 = _item(proj, "diluted_shares", y0)
    ebitdaH = _item(proj, "ebitda", yH)
    sharesH = _item(proj, "diluted_shares", yH)
    if (
        spot > 0 and ebitda0 is not None and shares0 and shares0 > 0 and ebitda0 > 0
        and ebitdaH is not None and sharesH and sharesH > 0 and ebitdaH > 0
    ):
        eps0 = ebitda0 / shares0
        cur_mult = spot / eps0
        persist["current_multiple"] = float(cur_mult)
        persist["exit_price_point"] = float(cur_mult * (ebitdaH / sharesH))
        persist["origin_ebitda_per_share"] = float(eps0)
        persist["horizon_ebitda_per_share"] = float(ebitdaH / sharesH)
    elif spot > 0:
        persist["current_multiple"] = 1.0
        persist["exit_price_point"] = float(spot)
        persist["metric"] = "raw_price_persistence"
        persist["flags"] = ["FALLBACK_PRICE_PERSISTENCE_NO_EBITDA"]
    out["baselines"]["current_multiple_persistence"] = persist

    # Forecasts to persist (before outcomes)
    fcff_y1 = None if fcff is None or not fcff.values else fcff.values[0]
    vps = central.get("vps")
    # Mature lean has no independent price model: point equals persistence when available.
    # Mark FORECAST_IS_BASELINE so metrics skip fake incremental comparisons.
    price_forecast = persist.get("exit_price_point")
    price_is_baseline = price_forecast is not None
    if price_forecast is None:
        price_forecast = vps
        price_is_baseline = False
    if price_is_baseline:
        flags.append("FORECAST_IS_BASELINE")
    # return point forecast at horizon H under DIVIDEND-NO-REINVEST
    # Terminal = exit-price persistence (NOT as-of central DCF VPS — negative VPS biased TSR).
    cum_dps = 0.0
    n_dps_computable = 0
    n_div_incomplete = 0  # div present but shares missing/non-positive
    for y in proj.years[:horizon_years]:
        div = _item(proj, "dividends", y)
        sh = _item(proj, "diluted_shares", y)
        if div is None:
            continue
        if sh is not None and sh > 0:
            n_dps_computable += 1
            cum_dps += div / sh
        else:
            n_div_incomplete += 1
    # SF1′: CUM_DPS_ZERO only when DPS was computable (div + valid shares) and sums to 0.
    # Div present but shares invalid → PATH_DPS_INCOMPLETE (not ZERO). All-missing → MISSING.
    if n_dps_computable > 0:
        if cum_dps == 0.0:
            flags.append("CUM_DPS_ZERO")
    elif n_div_incomplete > 0:
        flags.append("PATH_DPS_INCOMPLETE")
    else:
        flags.append("PATH_DIVIDENDS_MISSING")
    exit_px = persist.get("exit_price_point")
    ret_point = None
    if exit_px is not None and spot > 0:
        ret_point = (float(exit_px) + cum_dps - spot) / spot
    terminal_source = (
        "current_multiple_persistence" if exit_px is not None else None
    )
    out["forecasts"] = {
        "operating_cash_flow": {
            "metric": "fcff_year1",
            "point": fcff_y1,
            "quantiles": None,  # filled when distributional path available
            "unit": "CNY",
            "note": (
                "FCFF year-1 from deterministic median-driver projection. "
                "Not identical to baselines.historical_median.fcff_y1 "
                "(that baseline is the median of as-of-visible realized FCFF proxies)."
            ),
        },
        "intrinsic_value": {
            "metric": "vps_dcf_central",
            "point": vps,
            "method": "central_dcf",
            "note": "Intrinsic under stated WACC/g assumptions — not scored solely against market price",
        },
        "market_price": {
            "metric": (
                "current_multiple_persistence"
                if price_is_baseline
                else "vps_price_level_proxy_fallback"
            ),
            "point": price_forecast,
            "forecast_is_baseline": price_is_baseline,
            "baseline_source": (
                "current_multiple_persistence" if price_is_baseline else None
            ),
            "note": (
                "Mature lean: point equals current-multiple persistence exit-price baseline "
                "when available (FORECAST_IS_BASELINE). Fallback: intrinsic VPS as price-level "
                "proxy only. Not an independent alpha forecast; incremental vs persistence "
                "must not be claimed as information gain."
            ),
        },
        "total_shareholder_return": {
            "metric": "holding_period_return_point",
            "horizon_years": horizon_years,
            "point": ret_point,
            "cum_dps": cum_dps,
            "entry_price": spot,
            "terminal_exit_price_proxy": exit_px,
            "terminal_source": terminal_source,
            "terminal_vps_proxy": None,  # deprecated: as-of DCF VPS must not drive TSR point
            "dividend_treatment": "DIVIDEND-NO-REINVEST-v1",
            "note": (
                "Point forecast = (exit_price_persistence + path DPS − spot) / spot. "
                "Does not use as-of central DCF VPS as terminal (avoids negative-VPS TSR bias). "
                "terminal_source is current_multiple_persistence only when exit_price is available. "
                "CUM_DPS_ZERO when DPS computable (div + valid shares) and cumulative DPS is 0; "
                "PATH_DPS_INCOMPLETE when dividends present but shares missing/non-positive; "
                "PATH_DIVIDENDS_MISSING when no path dividend observation."
            ),
        },
    }
    out["flags"] = flags
    return out
