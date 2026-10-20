"""Owner decisions after Phase 2 review: unclassified BLOCK, t+1 dividends, announced-dividend base
deduction, revolver/cash interest, base balance-sheet residual warning."""

from __future__ import annotations

import pytest

from tests.company import company, loaded_config
from tests.factories import INST, ca
from vms.drivers.definitions import DEFINITIONS
from vms.drivers.history import extract_annual
from vms.pipeline import run_projection
from vms.pit.snapshot import build_snapshot
from vms.quality.report import GateError, QualityState
from vms.statements.invariants import check_invariants
from vms.statements.ledger import TracedValue

CFG = loaded_config()


def run(cfg=CFG, policy=None, mode="production", override=None, **kw):
    load, as_of = company(**kw)
    return run_projection(load, instrument_id=INST, as_of=as_of, loaded=cfg, policy_id=policy, mode=mode,
                          override_reason=override)


def v(r, k):
    return r.projection.items[k].value


def cfg_with(**proj):
    c = CFG.config.model_copy(update={"projection": CFG.config.projection.model_copy(update=proj)})
    return CFG.model_copy(update={"config": c})


# ---------------------------------------------------------------- 2. unclassified => BLOCK in production
def test_unclassified_blocked_in_production():
    with pytest.raises(GateError, match="INDUSTRY_UNCLASSIFIED"):
        run(industry=None)


def test_unclassified_exploratory_override_uses_generic_profile():
    r = run(industry=None, mode="exploratory", override="research run, classification pending")
    assert r.report.status is QualityState.BLOCKED and not r.report.usable_for_production
    assert "INDUSTRY_UNCLASSIFIED" in r.report.override.overridden_critical_codes
    assert r.projection.status == "VALID" and "INDUSTRY_UNCLASSIFIED" in r.projection.flags
    assert "INDUSTRY-UNCLASSIFIED-v2" in r.projection.assumptions


def test_classification_requirement_configurable():
    q = CFG.config.quality.model_copy(update={"require_industry_classification": False})
    cfg = CFG.model_copy(update={"config": CFG.config.model_copy(update={"quality": q})})
    assert run(cfg=cfg, industry=None).projection.status == "VALID"


# ---------------------------------------------------------------- 3. dividends: FY t paid in t+1
def test_payout_driver_uses_next_year_payment():
    load, as_of = company()
    snap, _, _ = build_snapshot(instrument_id=INST, as_of=as_of, financial=load.financial, market=load.market,
                                corporate_actions=load.corporate_actions, sources=load.sources)
    h = extract_annual(snap)
    assert DEFINITIONS["payout_ratio"].fn(h, 2022)[0] == pytest.approx(21.6 * 1.05 ** 2 / (72 * 1.05))
    assert DEFINITIONS["payout_ratio"].fn(h, 2024)[0] is None   # FY2024 dividend not yet paid in history


@pytest.mark.parametrize("policy", ["conservative_baseline", "fixed_payout", "min_cash_excess_distribution"])
def test_dividends_paid_year_after_declaration(policy):
    r = run(policy=policy)
    p = r.projection
    assert p.status == "VALID"
    assert v(r, "dividends_declared@2024") > 0      # FY-base declaration from policy (none announced)
    for y in p.years:
        assert v(r, f"dividends@{y}") == pytest.approx(v(r, f"dividends_declared@{y - 1}"))
    if policy != "min_cash_excess_distribution":
        payout = (CFG.config.capital_allocation.policies.fixed_payout.payout_ratio if policy == "fixed_payout"
                  else r.drivers.estimates["payout_ratio"].value)
        assert v(r, "dividends_declared@2026") == pytest.approx(payout * v(r, "parent_net_income@2026"))


def test_announced_unpaid_dividend_deducted_at_base():
    acts = [ca("B", "bonus_share", "2025-04-25", "2025-06-01", ratio=1.3),
            ca("D", "cash_dividend", "2025-04-25", "2025-06-20", cash=0.02)]
    r = run(actions=acts)
    d = 0.02 * 1000 * 1.3                       # shares before ex_date include the earlier pending bonus
    assert v(r, "announced_unpaid_dividends@2024") == pytest.approx(d)
    for k in ("cash", "total_equity", "total_assets"):
        assert v(r, f"{k}@2024") == pytest.approx(v(r, f"{k}_reported@2024") - d)
    assert v(r, "dividends_declared@2024") == 0 and v(r, "dividends@2025") == 0     # not paid twice
    assert "ANNOUNCED_DIVIDEND_DEDUCTED_AT_BASE" in r.projection.flags and r.projection.status == "VALID"
    refs = r.projection.items["announced_unpaid_dividends@2024"].inputs
    assert "corporate_action:D#r0" in refs and "corporate_action:B#r0" in refs


def test_dividend_before_fy_end_not_deducted():
    r = run(actions=[ca("D", "cash_dividend", "2024-04-25", "2024-06-20", cash=0.02)])
    assert v(r, "announced_unpaid_dividends@2024") == 0 and v(r, "dividends_declared@2024") > 0


# ---------------------------------------------------------------- 4. revolver rate, cash interest
REVOLVER = {(2024, "cash"): 0.0, (2024, "total_assets"): 1000 * 1.05 ** 3 - 200 * 1.05 ** 3}


def test_revolver_rate_is_cost_of_debt_plus_spread():
    base = run(overrides=REVOLVER)
    sp = run(cfg=cfg_with(revolver_spread=0.02), overrides=REVOLVER)
    assert v(base, "revolver_balance@2025") > 0
    kd = base.drivers.estimates["cost_of_debt"].value
    for r, s in ((base, 0.0), (sp, 0.02)):
        rv = v(r, "revolver_balance@2025")
        assert v(r, "interest_expense@2026") == pytest.approx(
            kd * (v(r, "interest_bearing_debt@2025") - rv) + (kd + s) * rv)
        assert r.projection.status == "VALID"
    assert v(sp, "interest_expense@2026") > v(base, "interest_expense@2026")


def test_cash_interest_default_zero_and_configurable():
    r0 = run()
    assert all(v(r0, f"interest_income@{y}") == 0 for y in r0.projection.years)
    r = run(cfg=cfg_with(cash_interest_rate=0.02))
    assert r.projection.status == "VALID"
    assert v(r, "interest_income@2025") == pytest.approx(0.02 * v(r, "cash@2024"))
    assert v(r, "pre_tax_income@2025") == pytest.approx(
        v(r, "ebit@2025") - v(r, "interest_expense@2025") + v(r, "interest_income@2025"))
    assert v(r, "fcff@2025") == pytest.approx(v(r0, "fcff@2025"))     # interest income is not operating


# ---------------------------------------------------------------- 7. base residual warning
def test_large_base_residual_warns_not_blocks():
    small = run()
    assert "BASE_BS_RESIDUAL_LARGE" not in small.projection.flags and small.projection.warnings == []
    # assets +10% without matching liabilities/equity => residual 10% of TA (> 5%)
    big = run(overrides={(2024, "total_assets"): 1.1 * 1000 * 1.05 ** 3})
    assert big.projection.status == "VALID" and "BASE_BS_RESIDUAL_LARGE" in big.projection.flags
    assert big.projection.warnings and v(big, "balance_sheet_residual@2024") == pytest.approx(100 * 1.05 ** 3)
    lax = run(cfg=cfg_with(bs_residual_warn_ratio=0.2), overrides={(2024, "total_assets"): 1.1 * 1000 * 1.05 ** 3})
    assert "BASE_BS_RESIDUAL_LARGE" not in lax.projection.flags


# ---------------------------------------------------------------- new invariants
@pytest.mark.parametrize("key,delta,code", [("dividends_declared@2025", 5.0, "DIVIDEND_TIMING_FAIL"),
                                            ("revolver_balance@2026", 1e9, "REVOLVER_EXCEEDS_DEBT"),
                                            ("interest_income@2026", 5.0, "INCOME_LINK_FAIL")])
def test_new_invariants_detect_tampering(key, delta, code):
    p = run(overrides=REVOLVER).projection
    items = dict(p.items)
    tv = items[key]
    items[key] = TracedValue(value=tv.value + delta, formula=tv.formula, inputs=tv.inputs)
    codes = {x.code for x in check_invariants(items, p.base_year, p.years, tol=1.0, min_cash_to_revenue=0.05)}
    assert code in codes
