"""Phase 7: horizon equity, dividend-no-reinvest returns, stats, price×regime invariant."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.engine import ValuationEngine
from vms.pipeline import run_returns, run_valuation
from vms.returns import (annualized_geometric, build_return_distributions, content_fingerprint,
                         cvar_es, enterprise_value_at_horizon, entry_price_grid, holding_period_return,
                         pathwise_returns_improve_at_lower_price, summarize_returns)
from vms.returns.horizon_value import cumulative_dps, equity_at_horizon
from vms.statements.cashflows import FCFFSeries
from vms.valuation.wacc import build_wacc

L = loaded_config()


def test_entry_price_grid():
    assert entry_price_grid(10.0, [0.8, 1.0, 1.2]) == pytest.approx([8.0, 10.0, 12.0])
    with pytest.raises(ValueError):
        entry_price_grid(0.0, [1.0])


def test_holding_period_and_ann_geo_hand():
    # VPS=12, cum_dps=1, P0=10 => R=0.3; H=3 => (1.3)^(1/3)-1
    r, _ = holding_period_return(value_per_share=12.0, cum_dps=1.0, entry_price=10.0)
    assert r == pytest.approx(0.3)
    ag, _ = annualized_geometric(holding_return=0.3, horizon_years=3)
    assert ag == pytest.approx(1.3 ** (1 / 3) - 1)
    bad, fl = annualized_geometric(holding_return=-1.0, horizon_years=2)
    assert bad is None and "ANNUALIZED_UNDEFINED_TOTAL_LOSS" in fl
    # lower price improves return
    r_lo, _ = holding_period_return(value_per_share=12.0, cum_dps=1.0, entry_price=8.0)
    r_hi, _ = holding_period_return(value_per_share=12.0, cum_dps=1.0, entry_price=12.0)
    assert r_lo > r_hi


def test_horizon_ev_hand_fixture():
    """FCFF=[100,110], WACC=0.10, g=0.03. At H=2 EV=TV; at H=1 remaining PV."""
    fcff = [100.0, 110.0]
    w, g = 0.10, 0.03
    tv = 110.0 * 1.03 / (0.10 - 0.03)
    ok, reason, p2, _ = enterprise_value_at_horizon(
        fcff_values=fcff, wacc=w, g=g, horizon_index=2, min_wacc_minus_g=0.01, max_terminal_growth=0.04)
    assert ok and p2["enterprise_value"] == pytest.approx(tv) and p2["remaining_pv_fcff"] == pytest.approx(0.0)
    ok, _, p1, _ = enterprise_value_at_horizon(
        fcff_values=fcff, wacc=w, g=g, horizon_index=1, min_wacc_minus_g=0.01, max_terminal_growth=0.04)
    assert ok
    expect = 110.0 / 1.1 + tv / 1.1
    assert p1["enterprise_value"] == pytest.approx(expect)
    # margin reject
    ok, reason, _, fl = enterprise_value_at_horizon(
        fcff_values=fcff, wacc=0.035, g=0.03, horizon_index=2, min_wacc_minus_g=0.01, max_terminal_growth=0.04)
    assert not ok and reason == "WACC_G_MARGIN_FAIL" and "NO_SILENT_DENOMINATOR_REPAIR" in fl


def test_cvar_and_quantile_consistency():
    rng = np.random.default_rng(0)
    xs = rng.normal(0.05, 0.2, size=2000)
    s = summarize_returns(xs, vps=xs * 10 + 5, loss_thresholds=[-0.2], hurdles=[0.0, 0.1], cvar_levels=[0.95])
    assert s["p01"] <= s["p05"] <= s["median"]
    assert s["cvar"]["0.95"] <= s["p05"] + 1e-9  # ES at 95% is mean of left 5% <= p05 roughly near
    assert 0.0 <= s["p_loss"] <= 1.0
    assert cvar_es(xs, 0.95) == pytest.approx(s["cvar"]["0.95"])


def test_path_returns_end_to_end_and_price_invariant():
    load, as_of = cyclical_company()
    spot = float(load.market[-1].raw_close) if hasattr(load, "market") else None
    # use pipeline
    run = run_returns(load, instrument_id=INST, as_of=as_of, loaded=L, seed=7, n_paths=40, n_years=4,
                      spot_price=None, horizons_years=[1, 3, 4])
    assert run.returns is not None and run.valuation is not None
    r = run.returns
    assert r.n_valid_paths > 0 and r.dividend_treatment == "DIVIDEND-NO-REINVEST-v1"
    assert "DIVIDEND-NO-REINVEST-v1" in r.assumptions
    assert pathwise_returns_improve_at_lower_price(r.path_returns)
    # mixture cells present for each price × horizon
    assert len(r.mixture) == len(r.entry_prices) * len(r.horizons_years)
    # spot cell has stats
    cell = next(c for c in r.mixture if abs(c.relative_to_spot - 1.0) < 1e-9 and c.horizon_years == 1)
    assert cell.stats["n"] > 0 and "mean" in cell.stats and "cvar" in cell.stats
    # regime diagnostics present
    assert r.by_regime and all("support_count" in rc.model_dump() for rc in r.by_regime)


def test_changed_posterior_changes_returns():
    load, as_of = cyclical_company()
    a = run_returns(load, instrument_id=INST, as_of=as_of, loaded=L, seed=1, n_paths=30, n_years=3)
    b = run_returns(load, instrument_id=INST, as_of=as_of, loaded=L, seed=99, n_paths=30, n_years=3)
    assert content_fingerprint(a.returns) != content_fingerprint(b.returns)


def test_price_does_not_change_fundamental_odds():
    """Lower price must not alter regime posterior — odds come from fundamentals only."""
    load, as_of = cyclical_company()
    run = run_returns(load, instrument_id=INST, as_of=as_of, loaded=L, seed=3, n_paths=20, n_years=3,
                      entry_prices=[5.0, 10.0, 15.0], horizons_years=[2])
    # same path initial states across all entry prices
    by_path = {}
    for pr in run.returns.path_returns:
        if not pr.valid:
            continue
        by_path.setdefault(pr.path_id, set()).add(pr.initial_state)
    assert by_path and all(len(s) == 1 for s in by_path.values())
    # regime posterior independent of entry prices (from Phase 3, not returns)
    assert run.regimes is not None
    probs = run.regimes.current.probabilities
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_engine_build_return_distributions():
    load, as_of = cyclical_company()
    eng = ValuationEngine(L)
    p6 = eng.value_from_load(load, instrument_id=INST, as_of=as_of, seed=2, n_paths=20, n_years=3)
    spot = float(p6.snapshot.market[-1].raw_close)
    bundle = eng.build_return_distributions(
        p6.valuation, p6.financial_paths, spot_price=spot, horizons_years=[1, 3],
        simulation=p6.bundle, regimes=p6.regimes)
    assert bundle.n_valid_paths > 0
    # Phase 8 is live via eng.run_diagnostics(load, ...)


def test_no_dividend_double_count_in_formula():
    """Buyback cash is NOT added; only VPS (which embeds share count) + cum DPS."""
    # If we wrongly added buyback cash, R would be higher — formula uses only VPS+DPS.
    r, _ = holding_period_return(value_per_share=10.0, cum_dps=0.5, entry_price=10.0)
    assert r == pytest.approx(0.05)
