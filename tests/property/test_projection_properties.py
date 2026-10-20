"""All valid deterministic paths pass invariants across policies/driver perturbations (Phase 2 acceptance)."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.company import company, loaded_config
from tests.factories import INST
from vms.pipeline import run_projection

CFG = loaded_config()


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(growth=st.floats(-0.3, 0.5), ebit=st.floats(-300, 300), capex=st.floats(0, 400), ar=st.floats(0, 900),
       cash=st.floats(0, 600), policy=st.sampled_from(["conservative_baseline", "historical_continuation",
                                                         "fixed_payout", "target_leverage",
                                                         "min_cash_excess_distribution"]))
def test_projection_valid_and_invariants_hold(growth, ebit, capex, ar, cash, policy):
    over = {(2024, "ebit"): ebit, (2024, "capex"): capex, (2024, "accounts_receivable"): ar, (2024, "cash"): cash}
    load, as_of = company(growth=growth, overrides=over)
    p = run_projection(load, instrument_id=INST, as_of=as_of, loaded=CFG, policy_id=policy, years=6).projection
    assert p.status == "VALID", [v.code for v in p.violations]
    for y in p.years:
        assert p.items[f"tax_expense@{y}"].value >= 0 and p.items[f"operating_tax@{y}"].value >= 0
        assert p.items[f"shares_outstanding@{y}"].value > 0
        assert p.items[f"interest_bearing_debt@{y}"].value >= -1e-6
