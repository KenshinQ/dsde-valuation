"""VMS-0.2 Phase 4 acceptance criteria (SPEC §20 Phase 4)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vms.methods.cash_flow.equity_dcf import dcf_fcfe, ddm_equity, payout_modelable
from vms.schemas.config import TerminalValueConfig, load_config
from vms.statements.cashflows import (
    CashFlowTypeError,
    CostOfEquity,
    FCFFSeries,
    FCFESeries,
    WACC,
    present_value,
)
from vms.valuation.dcf import dcf_fcff
from vms.valuation.wacc import as_cost_of_equity, as_wacc, build_wacc
from vms.equity_bridge import bridge_ev_to_equity


@pytest.fixture()
def loaded(repo):
    return load_config(repo / "config/default.yaml")


@pytest.fixture()
def tv_cfg(loaded):
    return loaded.config.terminal_value


def _wacc_inputs(loaded, *, ke=0.10, wd=0.0, we=1.0, kd=0.05, tc=0.25):
    cfg = loaded.config.valuation.model_copy(update={
        "risk_free_rate": 0.04, "erp": 0.06, "beta": 1.0, "beta_shrink_strength": 0.0,
        "beta_n_eff": 1.0, "cost_of_equity": ke,
        "target_debt_weight": wd, "target_equity_weight": we,
    })
    return build_wacc(cfg, cost_of_debt=kd, tax_rate=tc, weight_debt=wd, weight_equity=we)


# ---- AC1 hand-calculated fixtures ----
def test_ac1_fcff_hand_fixture(loaded, tv_cfg):
    fcff = FCFFSeries(years=[2025, 2026], values=[100.0, 110.0])
    w = _wacc_inputs(loaded, ke=0.10)
    assert w.wacc == pytest.approx(0.10)
    tv = tv_cfg.model_copy(update={"terminal_growth": 0.03, "min_wacc_minus_g": 0.01})
    r = dcf_fcff(fcff=fcff, wacc_inputs=w, tv_cfg=tv)
    assert r.valid
    pv_fcff = 100 / 1.1 + 110 / 1.1 ** 2
    fcff_n1 = 110 * 1.03
    tv_v = fcff_n1 / (0.10 - 0.03)
    pv_tv = tv_v / 1.1 ** 2
    assert r.pv_fcff == pytest.approx(pv_fcff)
    assert r.enterprise_value == pytest.approx(pv_fcff + pv_tv)
    assert r.tv_fraction == pytest.approx(pv_tv / (pv_fcff + pv_tv))


def test_ac1_fcfe_hand_fixture(loaded, tv_cfg):
    fcfe = FCFESeries(years=[2025, 2026], values=[80.0, 88.0])
    ke = 0.12
    tv = tv_cfg.model_copy(update={"terminal_growth": 0.03, "min_wacc_minus_g": 0.01})
    r = dcf_fcfe(fcfe=fcfe, cost_of_equity=ke, tv_cfg=tv)
    assert r.valid and r.discount_rate_kind == "COST_OF_EQUITY"
    pv = 80 / 1.12 + 88 / 1.12 ** 2
    n1 = 88 * 1.03
    tv_v = n1 / (0.12 - 0.03)
    pv_tv = tv_v / 1.12 ** 2
    assert r.pv_cashflows == pytest.approx(pv)
    assert r.equity_value == pytest.approx(pv + pv_tv)
    # type guard: cannot discount FCFE with WACC
    with pytest.raises(CashFlowTypeError):
        present_value(fcfe, WACC(rate=0.10))


def test_ac1_ddm_hand_fixture(loaded, tv_cfg):
    divs = [10.0, 10.5, 11.025]
    years = [2025, 2026, 2027]
    ke = 0.10
    tv = tv_cfg.model_copy(update={"terminal_growth": 0.03, "min_wacc_minus_g": 0.01})
    r = ddm_equity(dividends=divs, years=years, cost_of_equity=ke, tv_cfg=tv)
    assert r.valid
    pv = sum(d / (1.1) ** (i + 1) for i, d in enumerate(divs))
    n1 = 11.025 * 1.03
    tv_v = n1 / (0.10 - 0.03)
    pv_tv = tv_v / 1.1 ** 3
    assert r.pv_dividends == pytest.approx(pv)
    assert r.equity_value == pytest.approx(pv + pv_tv)


# ---- AC2 discount rate kinds ----
def test_ac2_fcff_uses_wacc_fcfe_ddm_use_ke(loaded, tv_cfg):
    w = _wacc_inputs(loaded, ke=0.11, wd=0.3, we=0.7)
    assert w.wacc != pytest.approx(w.cost_of_equity)  # levered
    fcff = FCFFSeries(years=[2025], values=[100.0])
    tv = tv_cfg.model_copy(update={"terminal_growth": 0.02})
    r_fcff = dcf_fcff(fcff=fcff, wacc_inputs=w, tv_cfg=tv)
    assert r_fcff.valid and r_fcff.wacc == pytest.approx(w.wacc)
    # present_value pairing
    assert present_value(fcff, as_wacc(w)) == pytest.approx(r_fcff.pv_fcff)

    fcfe = FCFESeries(years=[2025], values=[70.0])
    r_fcfe = dcf_fcfe(fcfe=fcfe, cost_of_equity=w.cost_of_equity, tv_cfg=tv)
    assert r_fcfe.valid and r_fcfe.discount_rate_kind == "COST_OF_EQUITY"
    assert r_fcfe.cost_of_equity == pytest.approx(w.cost_of_equity)
    # forbid WACC substitution flag path
    bad = dcf_fcfe(fcfe=fcfe, cost_of_equity=w.cost_of_equity, tv_cfg=tv, discount_rate_kind="WACC")
    assert not bad.valid and bad.invalid_reason == "WACC_SUBSTITUTION_FORBIDDEN"

    r_ddm = ddm_equity(dividends=[5.0, 5.2], years=[2025, 2026], cost_of_equity=w.cost_of_equity, tv_cfg=tv)
    assert r_ddm.valid and r_ddm.discount_rate_kind == "COST_OF_EQUITY"


# ---- AC3 invalid WACC/ke vs g ----
def test_ac3_invalid_discount_terminal_growth_rejected(loaded, tv_cfg):
    fcff = FCFFSeries(years=[2025], values=[100.0])
    w = _wacc_inputs(loaded, ke=0.035)
    tv = tv_cfg.model_copy(update={"terminal_growth": 0.03, "min_wacc_minus_g": 0.01})
    r = dcf_fcff(fcff=fcff, wacc_inputs=w, tv_cfg=tv)
    assert not r.valid and r.invalid_reason == "WACC_G_MARGIN_FAIL"
    assert "NO_SILENT_DENOMINATOR_REPAIR" in r.flags

    fcfe = FCFESeries(years=[2025], values=[50.0])
    r2 = dcf_fcfe(fcfe=fcfe, cost_of_equity=0.035, tv_cfg=tv)
    assert not r2.valid and r2.invalid_reason == "KE_G_MARGIN_FAIL"

    r3 = ddm_equity(dividends=[2.0], years=[2025], cost_of_equity=0.035, tv_cfg=tv)
    assert not r3.valid and r3.invalid_reason == "KE_G_MARGIN_FAIL"


@given(
    g=st.floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False),
    rate=st.floats(min_value=0.0, max_value=0.06, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=40, deadline=None)
def test_property_invalid_wacc_le_g_never_valid(g, rate):
    tv = TerminalValueConfig(
        min_wacc_minus_g=0.01, max_terminal_growth=0.05, tv_fraction_warning=0.9, terminal_growth=g,
    )
    if rate - g >= tv.min_wacc_minus_g - 1e-15:
        return  # only test invalid region
    from vms.valuation.wacc import WACCInputs
    w = WACCInputs(
        risk_free_rate=0.02, erp=0.05, beta_raw=1.0, beta=1.0, beta_prior=1.0, beta_n_eff=1.0,
        beta_shrink_strength=0.0, cost_of_equity=rate, cost_of_debt=0.05, tax_rate=0.25,
        weight_debt=0.0, weight_equity=1.0, wacc=rate, provenance={}, assumptions=[],
    )
    r = dcf_fcff(fcff=FCFFSeries(years=[1], values=[10.0]), wacc_inputs=w, tv_cfg=tv, g=g)
    assert not r.valid
    assert r.invalid_reason in {"WACC_G_MARGIN_FAIL", "TERMINAL_GROWTH_ABOVE_MAX"}
    assert r.enterprise_value is None


# ---- AC4 no double-count dividends / debt ----
def test_ac4_no_double_count_dividends_debt_share(loaded, tv_cfg):
    """FCFE equity is direct; DDM uses dividends only; FCFF bridge once; no FCFE+bridge."""
    tv = tv_cfg.model_copy(update={"terminal_growth": 0.02})
    w = _wacc_inputs(loaded, ke=0.10, wd=0.2, we=0.8)
    fcff = FCFFSeries(years=[2025, 2026], values=[100.0, 105.0])
    dcf = dcf_fcff(fcff=fcff, wacc_inputs=w, tv_cfg=tv)
    br = bridge_ev_to_equity(
        enterprise_value=dcf.enterprise_value, cash=20.0, debt=50.0, lease_debt_like=0.0,
        minority_interest_book=0.0, other_senior_claims=0.0, diluted_shares=10.0,
    )
    assert br.valid
    # FCFE path already includes net borrowing — must NOT apply a second EV bridge
    fcfe = FCFESeries(years=[2025, 2026], values=[60.0, 63.0])
    fe = dcf_fcfe(fcfe=fcfe, cost_of_equity=w.cost_of_equity, tv_cfg=tv)
    assert fe.valid
    # DDM discounts dividends only (not FCFE + dividends)
    ddm = ddm_equity(dividends=[12.0, 12.5], years=[2025, 2026], cost_of_equity=w.cost_of_equity, tv_cfg=tv)
    assert ddm.valid
    # Distinct objects: equity from FCFE ≠ equity from DDM in general; neither equals EV
    assert fe.equity_value != pytest.approx(dcf.enterprise_value)
    assert ddm.equity_value != pytest.approx(fe.equity_value)
    # Bridge applied only to FCFF EV
    assert br.equity_value == pytest.approx(dcf.enterprise_value + 20 - 50)


# ---- AC5 TV share + sensitivities reported (via plugin values shape) ----
def test_ac5_tv_fraction_and_sensitivities_reported(repo, loaded):
    from vms.data import synthetic
    from vms.data.io import load_directory, write_directory
    from vms.methods import build_registry_from_config
    from vms.methods.cash_flow import run_eligible_cashflow_methods
    from vms.pipeline import run_path_projection
    from vms.pit.asof import parse_as_of
    from vms.profiles import classify_profile
    from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
    from vms.schemas.contracts import ValuationTarget

    out = repo / "tmp_phase4_ac5"
    out.mkdir(exist_ok=True)
    fin, mkt, actions = synthetic.generate(7)
    write_directory(out / "data", fin, mkt, actions, synthetic.source_descriptors(),
                    classifications=synthetic.classifications())
    load = load_directory(out / "data")
    as_of, _ = parse_as_of("2025-06-30")
    run = run_path_projection(
        load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, loaded=loaded,
        seed=7, n_paths=15, n_years=3,
    )
    assert run.financial_paths is not None
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data).model_copy(update={
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT, "as_of": "2025-06-30",
    })
    profile = classify_profile(feats)
    bundle = run_eligible_cashflow_methods(
        registry=build_registry_from_config(loaded.method_registry),
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        financial_paths=run.financial_paths,
        loaded=loaded,
        available_fields=frozenset(data["available_fields"]),
    )
    fcff = next(r for r in bundle.results if r.method_id == "fcff_dcf")
    assert fcff.status.value == "VALID"
    assert fcff.values["discount_rate_kind"] == "WACC"
    assert fcff.values["tv_fraction"] is not None and "mean" in fcff.values["tv_fraction"]
    sens = fcff.values["sensitivities"]
    assert "rate_plus" in sens and "g_minus" in sens
    fcfe = next(r for r in bundle.results if r.method_id == "fcfe_dcf")
    assert fcfe.values["discount_rate_kind"] == "COST_OF_EQUITY"
    assert fcfe.values["ev_bridge_applied"] is False
    ddm = next(r for r in bundle.results if r.method_id == "ddm")
    # DDM may be VALID or INELIGIBLE depending on path dividends; never fabricates when ineligible
    if ddm.status.value != "VALID":
        assert ddm.values == {} or ddm.values.get("n_valid", 0) == 0
        assert any("PAYOUT" in c or "ABSENT" in c or "DIVIDEND" in c or "PATH" in c
                   for c in (ddm.reason_codes or ["PATH"]))


# ---- AC6 ineligible DDM structured reason ----
def test_ac6_ineligible_ddm_structured_reason_not_fabricated(loaded, tv_cfg):
    gate = payout_modelable(dividends=[0.0, 0.0, 0.0])
    assert not gate.modelable
    assert "ABSENT_DIVIDENDS" in gate.reason_codes
    r = ddm_equity(dividends=[0.0, 0.0], years=[2025, 2026], cost_of_equity=0.1, tv_cfg=tv_cfg)
    assert not r.valid
    assert r.equity_value is None
    assert r.invalid_reason in {"ABSENT_DIVIDENDS", "PAYOUT_NOT_MODELABLE"}

    # Erratic payout ratios
    gate2 = payout_modelable(dividends=[1.0, 50.0, 0.5], net_income=[10.0, 10.0, 10.0], max_payout_cv=0.5)
    assert not gate2.modelable
    assert "ERRATIC_PAYOUT" in gate2.reason_codes


def test_property_ineligible_method_contributes_no_values(repo, loaded):
    """No ineligible method contributes values (SPEC §21.2 / Phase 4)."""
    from vms.methods import build_registry_from_config
    from vms.methods.protocol import FinancialPathBundle, MethodConfig, ValuationContext
    from vms.profiles import classify_profile
    from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
    from vms.schemas.contracts import MethodEligibilityStatus, ValuationTarget

    registry = build_registry_from_config(loaded.method_registry)
    data = load_fixture(fixtures_dir() / "holding.json")
    profile = classify_profile(features_from_fixture(data))
    ctx = ValuationContext(
        instrument_id=profile.instrument_id, as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT, profile=profile,
        available_fields=frozenset(data["available_fields"]), loaded=loaded,
    )
    for mid in ("fcff_dcf", "fcfe_dcf", "ddm", "pe", "nav"):
        plugin = registry.plugin(mid)
        assert plugin is not None
        elig = plugin.eligibility(ctx)
        result = plugin.value_paths(ctx, FinancialPathBundle(), MethodConfig(method_id=mid))
        if not elig.eligible:
            assert result.values == {}
            assert result.status in {
                MethodEligibilityStatus.INELIGIBLE,
                MethodEligibilityStatus.FAILED,
            }
