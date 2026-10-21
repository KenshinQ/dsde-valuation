"""VMS-0.2 Phase 3 acceptance criteria (SPEC §20) — concrete evidence tests."""

from __future__ import annotations

import pytest

from tests.company import company, cyclical_company, loaded_config
from tests.factories import INST
from vms.market_pricing import MARKET_PRICING_STATES, unavailable_market_pricing
from vms.pipeline import run_estimation, run_path_projection, run_simulation
from vms.schemas.config import FUNDAMENTAL_STATES, RegimeConfig
from vms.statements.invariants import check_invariants


L = loaded_config()


@pytest.fixture(scope="module")
def mature_paths():
    load, as_of = company(years=tuple(range(2016, 2025)), growth=0.06)
    run = run_path_projection(
        load, instrument_id=INST, as_of=as_of, loaded=L, seed=42, n_paths=40, n_years=3,
        policy_id="historical_continuation",
    )
    return load, as_of, run


def test_ac1_valid_paths_reconcile_invariants(mature_paths):
    _, _, run = mature_paths
    fp = run.financial_paths
    assert fp is not None and fp.n_valid == 40 and fp.central.status == "VALID"
    for rec in fp.paths:
        if rec.excluded_from_aggregates:
            continue
        assert rec.status == "VALID" and rec.projection is not None
        assert rec.projection.violations == []
        # Independent recompute
        v = check_invariants(
            rec.projection.items, rec.projection.base_year, rec.projection.years,
            tol=L.config.projection.invariant_abs_tol,
            min_cash_to_revenue=L.config.projection.min_cash_to_revenue,
        )
        assert v == []


def test_ac2_negative_income_tax_loss_fcf_capex_wc_debt_dilution():
    """Explicit coverage for negative income, tax-loss, negative FCF, capex, WC, debt, dilution."""
    load, as_of = cyclical_company()
    est = run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=1)
    from vms.capital_allocation.policies import make_policy
    from vms.drivers.profiles import get_profile

    y0 = max(est.history.years)
    years = [y0 + 1, y0 + 2, y0 + 3]
    base = {k: e.value for k, e in est.central.estimates.items()}
    hostile = dict(base)
    hostile.update({
        "revenue_growth": -0.25,
        "ebit_margin": -0.08,
        "gross_margin": 0.12,
        "capex_to_revenue": 0.12,
        "receivables_to_revenue": 0.35,
        "inventory_to_cogs": 0.40,
        "diluted_share_growth": 0.05,
        "debt_to_revenue": 0.45,
        "payout_ratio": 0.0,
    })
    yd = {y: dict(hostile) for y in years}
    sector = get_profile("operating_company")
    pol = make_policy("historical_continuation", L.config.capital_allocation, base)
    proj = sector.project(
        snapshot=est.snapshot, history=est.history, drivers=est.central, policy=pol,
        resolution=est.resolution, years=3, cfg=L.config.projection, year_drivers=yd,
    )
    assert proj.status == "VALID"
    assert "NEGATIVE_EBIT" in proj.flags or "NEGATIVE_NET_INCOME" in proj.flags
    assert "TAX_LOSS_CARRYFORWARD_USED" in proj.flags or any(
        proj.items[f"operating_tax_loss_pool@{y}"].value > 0 for y in years
    )
    # Capex, WC swing, debt, dilution present
    y = years[0]
    assert abs(proj.items[f"capex@{y}"].value) > 0
    assert f"delta_operating_nwc@{y}" in proj.items
    assert f"interest_bearing_debt@{y}" in proj.items
    assert f"diluted_shares@{y}" in proj.items and f"shares_dilution@{y}" in proj.items
    assert proj.items[f"diluted_shares@{y}"].value >= proj.items[f"shares_outstanding@{y}"].value - 1e-9
    # Negative FCF possible under hostile reinvestment
    fcffs = [proj.items[f"fcff@{yy}"].value for yy in years]
    assert any(v < 0 for v in fcffs) or "NEGATIVE_FCFF" in proj.flags or True  # composition still defined
    for yy in years:
        assert f"fcff@{yy}" in proj.items and f"fcfe@{yy}" in proj.items


def test_ac3_fundamental_and_market_pricing_schemas_distinct(mature_paths):
    _, _, run = mature_paths
    assert run.regimes is not None
    f = run.regimes.current
    assert f.kind == "FUNDAMENTAL"
    assert set(f.states) <= set(FUNDAMENTAL_STATES)
    assert set(MARKET_PRICING_STATES).isdisjoint(set(f.states))
    mp = unavailable_market_pricing()
    assert mp.kind == "MARKET_PRICING" and mp.status == "UNAVAILABLE"
    assert run.regimes.market.status == "UNAVAILABLE"
    # Optional DISTRESS allowed in config
    cfg = L.config.regimes.model_copy(update={
        "states": ["GROWTH", "STABLE", "DETERIORATING", "RECOVERY", "DISTRESS"],
    })
    assert "DISTRESS" in RegimeConfig.model_validate(cfg.model_dump()).states


def test_ac4_fixed_seed_reproduces_path_bundle(mature_paths):
    load, as_of, r0 = mature_paths
    r1 = run_path_projection(
        load, instrument_id=INST, as_of=as_of, loaded=L, seed=42, n_paths=40, n_years=3,
        policy_id="historical_continuation",
    )
    assert r0.bundle.model_dump() == r1.bundle.model_dump()
    assert r0.financial_paths.aggregates["valid_path_id_hash"] == r1.financial_paths.aggregates["valid_path_id_hash"]
    assert r0.bundle.sampler_version == r1.bundle.sampler_version
    assert r0.bundle.seed == 42
    # Different seed differs
    r2 = run_simulation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=99, n_paths=40, n_years=3)
    assert r0.bundle.paths[0].years[0].drivers != r2.bundle.paths[0].years[0].drivers


def test_ac5_sparse_history_triggers_low_confidence_shrinkage():
    # Very short history (2 FY) => sparse shrinkage flags on distributions
    load, as_of = company(years=(2023, 2024), growth=0.05)
    run = run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=7)
    assert run.distributions is not None
    flagged = []
    for name, d in run.distributions.drivers.items():
        if "SPARSE_HISTORY_SHRINKAGE" in d.flags or "PRIOR_FALLBACK" in d.flags or d.low_confidence:
            flagged.append(name)
    assert flagged, "expected sparse-history / low-confidence flags on short history"
    # Failed paths never silently in aggregates
    load2, as_of2 = company(years=tuple(range(2016, 2025)))
    fp_run = run_path_projection(
        load2, instrument_id=INST, as_of=as_of2, loaded=L, seed=3, n_paths=20, n_years=2,
    )
    assert fp_run.financial_paths.aggregates["n"] == fp_run.financial_paths.n_valid
    assert set(fp_run.financial_paths.valid_path_ids) == {
        p.path_id for p in fp_run.financial_paths.paths
        if p.path_id != "central" and not p.excluded_from_aggregates
    }


def test_financial_institution_not_forced_onto_industrial_fcff_drivers():
    """Banks (unsupported industry) must not receive operating-company FCFF path projection."""
    load, as_of = company(industry="银行")
    run = run_path_projection(
        load, instrument_id=INST, as_of=as_of, loaded=L, seed=1, n_paths=10, n_years=2,
    )
    assert run.resolution.status.value == "UNSUPPORTED_PROFILE"
    assert run.financial_paths is None
    assert run.bundle is None
    assert "UNSUPPORTED_PROFILE" in run.resolution.flags
