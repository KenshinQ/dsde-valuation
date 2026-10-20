"""Capital-allocation policies (§10) and accounting invariants with reason codes (§9.2)."""

from __future__ import annotations

import pytest

from tests.company import company, loaded_config
from tests.factories import INST
from vms.capital_allocation.policies import AllocationState, make_policy
from vms.pipeline import run_projection
from vms.statements.invariants import REASON_CODES, check_invariants
from vms.statements.ledger import TracedValue

CFG = loaded_config()
CA = CFG.config.capital_allocation
D = {"payout_ratio": 0.3, "acquisitions_to_revenue": 0.02, "repurchases_to_net_income": 0.1, "debt_to_revenue": 0.2}
S = AllocationState(year=2025, revenue=1000, parent_net_income=100, ebitda=150, cash_before_distributions=400,
                    debt_open=100)


def test_conservative_baseline():
    p = make_policy("conservative_baseline", CA, D)
    assert p.acquisitions(1000, 2025).value == 0 and p.repurchases(S).value == 0 and p.issuance_cash(S).value == 0
    assert p.dividends(S).value == pytest.approx(30) and p.debt_target(S).value == 100


def test_historical_continuation():
    p = make_policy("historical_continuation", CA, D)
    assert p.acquisitions(1000, 2025).value == pytest.approx(20)
    assert p.repurchases(S).value == pytest.approx(10) and p.debt_target(S).value == pytest.approx(200)


def test_fixed_payout_and_negative_income():
    p = make_policy("fixed_payout", CA, D)
    assert p.dividends(S).value == pytest.approx(CA.policies.fixed_payout.payout_ratio * 100)
    neg = AllocationState(**{**S.__dict__, "parent_net_income": -50})
    assert p.dividends(neg).value == 0


def test_target_leverage_clips_and_handles_negative_ebitda():
    p = make_policy("target_leverage", CA, D)
    lo, hi = CA.policies.target_leverage.debt_to_ebitda_min, CA.policies.target_leverage.debt_to_ebitda_max
    assert p.debt_target(AllocationState(**{**S.__dict__, "debt_open": 1000})).value == pytest.approx(hi * 150)
    assert p.debt_target(AllocationState(**{**S.__dict__, "debt_open": 0})).value == pytest.approx(lo * 150)
    d = p.debt_target(AllocationState(**{**S.__dict__, "ebitda": -10}))
    assert d.value == 100 and "EBITDA <= 0" in d.formula


def test_min_cash_excess_distribution():
    p = make_policy("min_cash_excess_distribution", CA, D)
    m, share = CA.policies.min_cash_excess_distribution.min_cash_to_revenue, CA.policies.min_cash_excess_distribution.dividend_share
    excess = 400 - m * 1000
    assert p.dividends(S).value == pytest.approx(excess * share)
    assert p.repurchases(S).value == pytest.approx(excess * (1 - share))


def test_policy_errors():
    with pytest.raises(ValueError, match="unknown capital-allocation policy"):
        make_policy("optimal_management", CA, D)


def test_policy_changes_outcomes_separately_for_equity_and_per_share():
    load, as_of = company()
    r = {pid: run_projection(load, instrument_id=INST, as_of=as_of, loaded=CFG, policy_id=pid).projection
         for pid in ("conservative_baseline", "min_cash_excess_distribution")}
    y = 2029
    eq = {k: p.items[f"total_equity@{y}"].value for k, p in r.items()}
    sh = {k: p.items[f"shares_outstanding@{y}"].value for k, p in r.items()}
    assert eq["min_cash_excess_distribution"] < eq["conservative_baseline"]     # cash paid out
    assert sh["min_cash_excess_distribution"] < sh["conservative_baseline"]     # buybacks shrink share count


# ---------------------------------------------------------------- invariants: tamper => reason code
@pytest.fixture(scope="module")
def valid():
    load, as_of = company()
    return run_projection(load, instrument_id=INST, as_of=as_of, loaded=CFG,
                          policy_id="min_cash_excess_distribution").projection


def _tamper(p, key, delta):
    items = dict(p.items)
    tv = items[key]
    items[key] = TracedValue(value=tv.value + delta, formula=tv.formula, inputs=tv.inputs)
    return check_invariants(items, p.base_year, p.years, tol=1.0, min_cash_to_revenue=0.05)


def test_valid_projection_has_no_violations(valid):
    assert valid.status == "VALID"
    assert check_invariants(valid.items, valid.base_year, valid.years, tol=1.0, min_cash_to_revenue=0.05) == []


@pytest.mark.parametrize("key,delta,code", [
    ("cash@2026", 50.0, "CASH_RECONCILIATION_FAIL"),
    ("interest_bearing_debt@2026", 50.0, "DEBT_ROLLFORWARD_FAIL"),
    ("total_equity@2026", 50.0, "EQUITY_ROLLFORWARD_FAIL"),
    ("distributions_to_shareholders@2026", 50.0, "DISTRIBUTION_DOUBLE_COUNT"),
    ("dividends@2026", 50.0, "DISTRIBUTION_DOUBLE_COUNT"),
    ("total_assets@2026", 50.0, "BALANCE_SHEET_FAIL"),
    ("operating_nwc@2026", 50.0, "NWC_LINK_FAIL"),
    ("net_income@2026", 50.0, "INCOME_LINK_FAIL"),
    ("fcff@2026", 50.0, "FCFF_COMPOSITION_FAIL"),
    ("fcfe@2026", 50.0, "FCFE_COMPOSITION_FAIL"),
    ("shares_repurchased@2026", 5.0, "REPURCHASE_INCONSISTENT"),
    ("shares_outstanding@2026", 5.0, "SHARES_ROLLFORWARD_FAIL"),
    ("tax_expense@2026", -1e6, "NEGATIVE_TAX"),
    ("cash@2026", float("nan"), "NON_FINITE"),
])
def test_tampered_projection_rejected_with_reason(valid, key, delta, code):
    codes = {v.code for v in _tamper(valid, key, delta)}
    assert code in codes, codes
    assert code in REASON_CODES


def test_repurchase_reduces_cash_and_shares_consistently(valid):
    y = 2026
    it = valid.items
    rep = it[f"share_repurchases@{y}"].value
    assert rep > 0
    assert it[f"shares_repurchased@{y}"].value * it[f"transaction_price@{y}"].value == pytest.approx(rep)
    assert "share_repurchases@2026" in it[f"cash@{y}"].inputs
