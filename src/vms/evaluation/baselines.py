"""Side-by-side valuation / forecast baselines at a PIT origin (SPEC §15.3)."""

from __future__ import annotations

import math
from typing import Any

from vms.assumptions import cite
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
                         mode="exploratory", override_reason="phase9_baseline_origin")
    out: dict[str, Any] = {
        "origin_as_of": as_of.isoformat(),
        "spot_price": spot,
        "profile": run.resolution.status.value,
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

    # 2) Historical driver mean/median — FCFF year-1 from projection already uses median drivers;
    #    also report hist median year-1 growth from driver estimates
    hist = {"label": "historical_driver_median", "revenue_growth_median": None, "ebit_margin_median": None}
    if run.drivers is not None:
        for name in ("revenue_growth", "ebit_margin"):
            est = run.drivers.estimates.get(name)
            if est is not None:
                hist[f"{name}_median"] = est.value
    # point CF forecast = first-year FCFF under median drivers
    hist["fcff_y1"] = None if fcff is None or not fcff.values else fcff.values[0]
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

    # Forecasts to persist (before outcomes)
    fcff_y1 = None if fcff is None or not fcff.values else fcff.values[0]
    vps = central.get("vps")
    # market-price forecast: use VPS as model fair price (NOT a claim that price must converge)
    price_forecast = vps
    # return point forecast at horizon H under DIVIDEND-NO-REINVEST using book DPS proxy = 0 for point baseline
    # cum DPS from projection dividends / shares over H years
    cum_dps = 0.0
    for y in proj.years[:horizon_years]:
        div = _item(proj, "dividends", y)
        sh = _item(proj, "diluted_shares", y)
        if div is not None and sh is not None and sh > 0:
            cum_dps += div / sh
    ret_point = None
    if vps is not None and spot > 0:
        ret_point = (vps + cum_dps - spot) / spot
    # At horizon H, equity value from remaining PV would be better; for Phase 9 point forecast use VPS at as_of
    # as terminal per-share value forecast (documented limitation)
    out["forecasts"] = {
        "operating_cash_flow": {
            "metric": "fcff_year1",
            "point": fcff_y1,
            "quantiles": None,  # filled when distributional path available
            "unit": "CNY",
            "note": "FCFF year-1 from deterministic central projection",
        },
        "intrinsic_value": {
            "metric": "vps_dcf_central",
            "point": vps,
            "method": "central_dcf",
            "note": "Intrinsic under stated WACC/g assumptions — not scored solely against market price",
        },
        "market_price": {
            "metric": "model_fair_price_proxy",
            "point": price_forecast,
            "note": "Uses intrinsic VPS as a price-level forecast proxy; distinct from intrinsic evaluation",
        },
        "total_shareholder_return": {
            "metric": "holding_period_return_point",
            "horizon_years": horizon_years,
            "point": ret_point,
            "cum_dps": cum_dps,
            "entry_price": spot,
            "terminal_vps_proxy": vps,
            "dividend_treatment": "DIVIDEND-NO-REINVEST-v1",
            "note": "Point forecast from central VPS + path DPS; distributional forecasts optional",
        },
    }
    out["flags"] = flags
    return out
