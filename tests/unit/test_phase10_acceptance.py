"""VMS-0.2 Phase 10 acceptance (SPEC §20 Phase 10 / §15 / §21 / §24)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tests.company import company, loaded_config
from tests.factories import INST
from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.adapters.dsde import (
    DSDE_CONTRACT_VERSION,
    consumer_view_from_track_b,
    dsde_availability,
    export_return_distribution,
    try_notify_dsde,
)
from vms.market_pricing import estimate_market_pricing_state, generate_exit_prices
from vms.pipeline import run_path_projection
from vms.returns.formula import holding_period_return, return_components
from vms.returns.horizon_value import cumulative_dps
from vms.returns.recompute import recompute_returns_after_market_posterior_change
from vms.returns.track_b import content_fingerprint_track_b
from vms.returns.stats import cvar_es, summarize_returns
from vms.returns.track_b import (
    build_return_distributions_from_exit_prices,
    merge_entry_prices,
    pathwise_returns_improve_at_lower_price_track_b,
)

L = loaded_config()


@pytest.fixture(scope="module")
def path_and_exit():
    load, as_of = company(years=tuple(range(2016, 2025)), growth=0.06)
    run = run_path_projection(
        load,
        instrument_id=INST,
        as_of=as_of,
        loaded=L,
        seed=42,
        n_paths=24,
        n_years=3,
        policy_id="historical_continuation",
    )
    assert run.financial_paths is not None
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    exits = generate_exit_prices(
        run.financial_paths,
        market_posterior=post,
        horizons_years=[1, 3],
        metric_id="ev_ebitda",
        seed=7,
    )
    return run.financial_paths, exits, post, load


# ---- AC1: Hand-worked return fixtures (dividends, splits, buybacks/issuance) ----
def test_ac1_hand_worked_dividend_fixture():
    # Terminal=12, cum_dps=1, P0=10 => R=0.3
    r, _ = holding_period_return(value_per_share=12.0, cum_dps=1.0, entry_price=10.0)
    assert r == pytest.approx(0.3)
    comps = return_components(terminal_price=12.0, shareholder_distributions=1.0, entry_price=10.0)
    assert comps["price_component"] == pytest.approx(0.2)
    assert comps["distribution_component"] == pytest.approx(0.1)
    assert comps["total"] == pytest.approx(0.3)


def test_ac1_hand_worked_split_and_buyback_no_double_count(path_and_exit):
    """Splits/buybacks affect share path only; cash DPS is the sole distribution add-on."""
    financial, exits, _, _ = path_and_exit
    # Pick a valid financial path and compute cumulative DPS at H=1
    rec = next(r for r in financial.paths if r.status == "VALID" and r.path_id != "central")
    dps = cumulative_dps(rec, 1)
    assert dps is not None and math.isfinite(dps)
    # Explicit override: distributions fixed; buybacks must not be added on top
    ep = next(p for p in exits.paths if p.valid and p.horizon_years == 1)
    bundle = build_return_distributions_from_exit_prices(
        exit_prices=exits,
        spot_price=10.0,
        loaded=L,
        financial=financial,
        entry_prices=[10.0],
        horizons_years=[1],
        explicit_distributions={(ep.path_id, 1): 2.5},
    )
    rows = [pr for pr in bundle.path_returns if pr.valid and pr.path_id == ep.path_id and pr.horizon_years == 1]
    assert rows and rows[0].shareholder_distributions == pytest.approx(2.5)
    assert "EXPLICIT_DISTRIBUTIONS_OVERRIDE" in rows[0].flags
    # Convention labels present
    assert bundle.buyback_treatment == "SHARE_COUNT_ONLY_NO_CASH_ADDON"
    assert bundle.issuance_treatment == "SHARE_COUNT_AND_CASH_IN_METRICS_ONLY"
    assert bundle.split_treatment == "REFLECTED_IN_SHARE_PATH"
    assert "NO-DOUBLE-COUNT-CA-v1" in bundle.assumptions
    assert "SHAREHOLDER-DIST-CASH-DPS-ONLY-v1" in bundle.assumptions


def test_ac1_track_b_uses_exit_not_intrinsic(path_and_exit):
    financial, exits, _, _ = path_and_exit
    assert exits.default_forbids_intrinsic_copy is True
    assert all(
        (not p.intrinsic_value_used) or p.scenario_kind == "CONVERGENCE_TO_INTRINSIC"
        for p in exits.paths
        if p.valid
    )
    bundle = build_return_distributions_from_exit_prices(
        exit_prices=exits, spot_price=10.0, loaded=L, financial=financial, horizons_years=[1, 3]
    )
    assert bundle.exit_ref["default_forbids_intrinsic_copy"] is True
    assert "TRACK-B-EXIT-RETURN-v1" in bundle.assumptions
    assert bundle.investment_value == "INVESTMENT_VALUE_NOT_ESTABLISHED"


# ---- AC2: higher entry price cannot improve pathwise return ----
def test_ac2_higher_entry_cannot_improve_pathwise(path_and_exit):
    financial, exits, _, _ = path_and_exit
    prices, _ = merge_entry_prices(10.0, relative_to_spot=[0.7, 1.0, 1.3], user_prices=[9.5])
    bundle = build_return_distributions_from_exit_prices(
        exit_prices=exits,
        spot_price=10.0,
        loaded=L,
        financial=financial,
        entry_prices=prices,
        horizons_years=[1, 3],
    )
    assert pathwise_returns_improve_at_lower_price_track_b(bundle.path_returns)
    # Also: for each path with X>0, mean return falls as P0 rises
    for h in bundle.horizons_years:
        cells = sorted(
            [c for c in bundle.mixture if c.horizon_years == h and c.stats.get("n", 0) > 0],
            key=lambda c: c.entry_price,
        )
        means = [c.stats["mean"] for c in cells]
        assert all(means[i] >= means[i + 1] - 1e-9 for i in range(len(means) - 1))


# ---- AC3: posterior change triggers recompute ----
def test_ac3_market_posterior_change_recomputs(path_and_exit):
    financial, exits, post, _ = path_and_exit
    base = build_return_distributions_from_exit_prices(
        exit_prices=exits, spot_price=10.0, loaded=L, financial=financial, horizons_years=[1, 3]
    )
    alt = estimate_market_pricing_state(
        current_multiple=14.0,
        historical_multiples=[8, 9, 10, 11, 9.5, 8.5, 10.5, 9, 8.8, 10.2, 9.1, 9.7, 10.0, 11.0],
        config=L.config.market_pricing.model_copy(update={"min_history_obs_for_estimation": 8}),
        use_fallback_when_unavailable=True,
    )
    _e2, r2, meta = recompute_returns_after_market_posterior_change(
        financial_paths=financial,
        market_posterior=alt,
        spot_price=10.0,
        loaded=L,
        prior_fingerprint=base.content_fingerprint,
        horizons_years=[1, 3],
        seed=99,
        metric_id="ev_ebitda",
    )
    assert meta["recomputed"] is True
    assert meta["assumption"] == "RETURN-RECOMPUTE-ON-POSTERIOR-CHANGE-v1"
    # Different posterior / seed stream should change return fingerprint in this fixture
    assert meta["return_fingerprint"] != base.content_fingerprint
    assert meta["changed_vs_prior"] is True
    assert r2.content_fingerprint == meta["return_fingerprint"]


# ---- AC4: quantiles, loss probs, ES internally consistent ----
def test_ac4_quantile_loss_es_consistency():
    rng = np.random.default_rng(0)
    xs = rng.normal(0.05, 0.25, size=3000)
    s = summarize_returns(
        xs,
        vps=xs * 10 + 20,
        loss_thresholds=[-0.2, -0.4],
        hurdles=[0.0, 0.1],
        cvar_levels=[0.95, 0.99],
        shareholder_distributions=np.full_like(xs, 1.0),
        entry_price=10.0,
    )
    assert s["p01"] <= s["p05"] <= s["median"]
    assert 0.0 <= s["p_loss"] <= 1.0
    assert abs(s["p_loss"] - float(np.mean(xs < 0.0))) < 1e-12
    for lv in (0.95, 0.99):
        es = s["cvar"][str(lv)]
        q = float(np.quantile(xs, 1.0 - lv))
        assert es is not None and es <= q + 1e-9
        assert cvar_es(xs, lv) == pytest.approx(es)
    assert "components" in s
    assert "flags" not in s or "QUANTILE_ORDER_INCONSISTENT" not in s.get("flags", [])


def test_ac4_bundle_cells_consistent(path_and_exit):
    financial, exits, _, _ = path_and_exit
    bundle = build_return_distributions_from_exit_prices(
        exit_prices=exits, spot_price=10.0, loaded=L, financial=financial, horizons_years=[1]
    )
    for c in bundle.mixture:
        if c.stats.get("n", 0) < 10:
            continue
        assert c.stats["p01"] <= c.stats["p05"] + 1e-12
        assert c.stats["p05"] <= c.stats["median"] + 1e-12
        for lv, es in c.stats["cvar"].items():
            if es is None:
                continue
            # ES at level L <= p_{1-L} approximately; for 0.95 compare to p05
            if lv == "0.95":
                assert es <= c.stats["p05"] + 1e-6


# ---- AC5: VMS runs without DSDE; public versioned contracts only ----
def test_ac5_core_without_dsde_and_public_contract(path_and_exit):
    financial, exits, _, _ = path_and_exit
    avail = dsde_availability()
    assert avail["dsde_present"] is False
    assert avail["required_for_core"] is False
    bundle = build_return_distributions_from_exit_prices(
        exit_prices=exits, spot_price=10.0, loaded=L, financial=financial, horizons_years=[1]
    )
    export = export_return_distribution(bundle)
    assert export.contract_version == DSDE_CONTRACT_VERSION
    assert export.schema_version == SCHEMA_VERSION
    assert export.investment_value == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    view = consumer_view_from_track_b(
        run_id="t",
        instrument_id=INST,
        as_of="2025-06-30",
        bundle=bundle,
    )
    st = try_notify_dsde(view)
    assert st["status"] == "DSDE_ABSENT_NOOP"
    assert st["delivered"] is False
    # No dsde import required to build returns
    assert "PHASE10-DSDE-PUBLIC-CONTRACT-v1" in bundle.assumptions


def test_schema_version_phase10_contract():
    assert SCHEMA_VERSION == "vms-0.2.phase10"
    assert IMPLEMENTED_PHASE == "PHASE_10"
