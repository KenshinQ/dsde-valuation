"""Phase 6: WACC, Gordon TV, exit-multiple, EV-equity bridge, hand fixtures, path valuation."""

from __future__ import annotations

import math

import pytest

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.engine import ValuationEngine
from vms.equity_bridge import bridge_ev_to_equity
from vms.pipeline import run_valuation
from vms.schemas.config import ExitMultipleConfig, TerminalValueConfig, ValuationConfig, load_config
from vms.statements.cashflows import FCFFSeries, WACC, present_value, CashFlowTypeError, CostOfEquity
from vms.valuation import build_wacc, dcf_fcff, exit_multiple_ev, shrink_beta, value_paths
from vms.valuation.wacc import as_wacc

L = loaded_config()
TV = L.config.terminal_value


def test_shrink_beta_formula():
    assert shrink_beta(1.5, n_eff=4, prior=1.0, k=2) == pytest.approx((4 * 1.5 + 2 * 1.0) / 6)


def test_wacc_hand_fixture():
    """rf=0.03, erp=0.06, beta=1.2, kd=0.05, tc=0.25, wd=0.3, we=0.7."""
    cfg = L.config.valuation.model_copy(update={
        "risk_free_rate": 0.03, "erp": 0.06, "beta": 1.2, "beta_n_eff": 0.0,
        "cost_of_equity": None, "cost_of_debt": None, "tax_rate": None,
        "target_debt_weight": 0.3, "target_equity_weight": 0.7,
    })
    # beta_n_eff=0 => beta = prior blend: (0*1.2 + 2*1)/(0+2)=1.0 when raw provided with n_eff=0
    # For hand fixture we want exact beta=1.2: set shrink strength 0
    cfg = cfg.model_copy(update={"beta_shrink_strength": 0.0, "beta_n_eff": 10.0})
    w = build_wacc(cfg, cost_of_debt=0.05, tax_rate=0.25, weight_debt=0.3, weight_equity=0.7)
    ke = 0.03 + 1.2 * 0.06
    assert w.beta == pytest.approx(1.2) and w.cost_of_equity == pytest.approx(ke)
    assert w.wacc == pytest.approx(0.7 * ke + 0.3 * 0.05 * (1 - 0.25))
    assert "WACC-RF-CONFIG-v1" in w.assumptions


def test_dcf_hand_fixture_matches_present_value():
    """FCFF = [100, 110], WACC=0.10, g=0.03 → hand PV + TV."""
    fcff = FCFFSeries(years=[2025, 2026], values=[100.0, 110.0])
    cfg = L.config.valuation.model_copy(update={
        "risk_free_rate": 0.04, "erp": 0.06, "beta": 1.0, "beta_shrink_strength": 0.0, "beta_n_eff": 1.0,
        "cost_of_equity": 0.10,  # force ke=0.10
        "target_debt_weight": 0.0, "target_equity_weight": 1.0,  # WACC = ke
    })
    w = build_wacc(cfg, cost_of_debt=0.05, tax_rate=0.25, weight_debt=0.0, weight_equity=1.0)
    assert w.wacc == pytest.approx(0.10)
    tv_cfg = TV.model_copy(update={"terminal_growth": 0.03, "min_wacc_minus_g": 0.01, "max_terminal_growth": 0.04})
    r = dcf_fcff(fcff=fcff, wacc_inputs=w, tv_cfg=tv_cfg)
    assert r.valid
    pv_fcff = 100 / 1.1 + 110 / 1.1 ** 2
    fcff_n1 = 110 * 1.03
    tv = fcff_n1 / (0.10 - 0.03)
    pv_tv = tv / 1.1 ** 2
    assert r.pv_fcff == pytest.approx(pv_fcff)
    assert r.tv == pytest.approx(tv) and r.pv_tv == pytest.approx(pv_tv)
    assert r.enterprise_value == pytest.approx(pv_fcff + pv_tv)
    assert r.tv_fraction == pytest.approx(pv_tv / (pv_fcff + pv_tv))
    # type guard still holds
    assert present_value(fcff, as_wacc(w)) == pytest.approx(pv_fcff)
    with pytest.raises(CashFlowTypeError):
        present_value(fcff, CostOfEquity(rate=0.10))


def test_wacc_g_margin_rejects_without_repair():
    fcff = FCFFSeries(years=[2025], values=[100.0])
    cfg = L.config.valuation.model_copy(update={
        "risk_free_rate": 0.02, "erp": 0.01, "beta": 1.0, "beta_shrink_strength": 0, "beta_n_eff": 1,
        "cost_of_equity": 0.035, "target_debt_weight": 0.0, "target_equity_weight": 1.0,
    })
    w = build_wacc(cfg, cost_of_debt=0.05, tax_rate=0.25, weight_debt=0.0, weight_equity=1.0)
    tv_cfg = TV.model_copy(update={"terminal_growth": 0.03, "min_wacc_minus_g": 0.01})  # 0.035-0.03 < 0.01
    r = dcf_fcff(fcff=fcff, wacc_inputs=w, tv_cfg=tv_cfg)
    assert not r.valid and r.invalid_reason == "WACC_G_MARGIN_FAIL"
    assert "NO_SILENT_DENOMINATOR_REPAIR" in r.flags


def test_bridge_hand_fixture_and_negative_equity_preserved():
    br = bridge_ev_to_equity(enterprise_value=1000, cash=50, debt=200, lease_debt_like=30,
                             minority_interest_book=20, other_senior_claims=10, diluted_shares=100)
    # 1000+50-200-30-20-10 = 790
    assert br.valid and br.equity_value == pytest.approx(790) and br.value_per_share == pytest.approx(7.9)
    assert br.components["interest_bearing_debt"] == -200
    neg = bridge_ev_to_equity(enterprise_value=100, cash=0, debt=500, lease_debt_like=0,
                              minority_interest_book=0, other_senior_claims=0, diluted_shares=10)
    assert neg.valid and neg.equity_value == pytest.approx(-400) and "NEGATIVE_EQUITY_PRESERVED" in neg.flags
    bad = bridge_ev_to_equity(enterprise_value=100, cash=0, debt=0, lease_debt_like=0,
                              minority_interest_book=0, other_senior_claims=0, diluted_shares=0)
    assert not bad.valid and bad.invalid_reason == "NONPOSITIVE_SHARES"


def test_exit_multiple_separate_and_shrink():
    cfg = ExitMultipleConfig(metric="ebitda", multiple=None, peers=[6.0, 8.0, 10.0], shrink_prior=8.0,
                             shrink_strength=3.0, normalize_years=1)
    # median 8, n=3, k=3 → (3*8+3*8)/6 = 8
    r = exit_multiple_ev(metric_value=50.0, cfg=cfg)
    assert r.valid and r.enterprise_value == pytest.approx(8.0 * 50)
    assert r.peer_n == 3 and "EXIT-MULTIPLE-SEPARATE-v1" in r.assumptions
    # scarcity
    cfg2 = cfg.model_copy(update={"peers": [7.0], "multiple": None})
    r2 = exit_multiple_ev(metric_value=50.0, cfg=cfg2)
    assert "PEER_SCARCITY" in r2.flags
    # default keep separate: composite_weights is None on default config
    assert L.config.valuation.composite_weights is None


def test_path_valuation_end_to_end():
    load, as_of = cyclical_company()
    r = run_valuation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=5, n_paths=30, n_years=4)
    v = r.valuation
    assert v.central.status == "VALID" and v.n_valid_dcf == 30
    assert v.central.dcf.enterprise_value > 0 and v.central.bridge_dcf.value_per_share is not None
    # DCF and exit multiple both present and separate
    assert v.central.exit_multiple is not None and v.central.composite_equity is None
    assert v.aggregates["dcf_value_per_share"]["n"] == 30
    eng = ValuationEngine(L)
    v2 = eng.value_paths(r.financial_paths, snapshot=r.snapshot)
    assert v2.n_valid_dcf == 30


def test_risk_free_required_in_config(tmp_path):
    import shutil, yaml
    cfg_dir = tmp_path / "cfg"
    shutil.copytree(L.config_path and __import__("pathlib").Path("config"), cfg_dir)
    # Actually L.config_path may be string
    from pathlib import Path
    src = Path("config")
    if cfg_dir.exists():
        shutil.rmtree(cfg_dir)
    shutil.copytree(src, cfg_dir)
    y = yaml.safe_load((cfg_dir / "default.yaml").read_text())
    del y["valuation"]["risk_free_rate"]
    (cfg_dir / "default.yaml").write_text(yaml.safe_dump(y, allow_unicode=True))
    with pytest.raises(Exception):
        load_config(cfg_dir / "default.yaml")
