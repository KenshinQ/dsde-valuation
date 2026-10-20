"""Deterministic statement projection (Phase 2 acceptance)."""

from __future__ import annotations

import pytest

from tests.company import company, loaded_config
from tests.factories import INST, ca
from vms.assumptions import ASSUMPTIONS
from vms.pipeline import run_projection
from vms.schemas.config import ProjectionConfig
from vms.statements.cashflows import FCFESeries, FCFFSeries
from vms.statements.ledger import unresolved_refs

CFG = loaded_config()
POLICIES = ["conservative_baseline", "historical_continuation", "fixed_payout", "target_leverage",
            "min_cash_excess_distribution"]


def run(policy=None, years=5, cfg=CFG, **kw):
    load, as_of = company(**kw)
    return run_projection(load, instrument_id=INST, as_of=as_of, loaded=cfg, policy_id=policy, years=years)


def v(r, item, y):
    return r.projection.items[f"{item}@{y}"].value


@pytest.mark.parametrize("policy", POLICIES)
def test_valid_and_fully_traced_for_every_policy(policy):
    # non-zero acquisitions history so every FCFF/FCFE/cash term is exercised (historical_continuation)
    r = run(policy, overrides={(y, "acquisitions_net"): 30.0 for y in range(2021, 2025)})
    p = r.projection
    assert p.status == "VALID", p.violations
    assert p.years == [2025, 2026, 2027, 2028, 2029] and p.base_year == 2024
    assert p.policy["policy_id"] == policy and p.policy["version"] == "1"
    bad = unresolved_refs(p.items, drivers=set(r.drivers.estimates), policy=set(p.policy["params"]),
                          config=set(ProjectionConfig.model_fields), assumptions=set(ASSUMPTIONS))
    assert bad == []
    assert all(tv.formula for tv in p.items.values())
    assert all(a in ASSUMPTIONS for a in p.assumptions)


def test_base_items_trace_to_snapshot_records():
    r = run()
    refs = {i for tv in r.projection.items.values() for i in tv.inputs if i.startswith("snapshot:")}
    known = {f"snapshot:{f.source_id}:{f.statement_type}.{f.field_name}@{f.period_end}[{f.basis}]#{f.revision_id or '-'}"
             for f in r.snapshot.financials}
    known |= {f"snapshot:market:{m.source_id}@{m.timestamp.isoformat()}" for m in r.snapshot.market}
    assert refs and refs <= known


def test_spec_formulas_hand_check():
    r = run()
    d = r.drivers.estimates
    rev24 = 1000 * 1.05 ** 3
    assert v(r, "revenue", 2025) == pytest.approx(rev24 * (1 + d["revenue_growth"].value))
    assert v(r, "gross_profit", 2025) == pytest.approx(v(r, "revenue", 2025) * d["gross_margin"].value)
    assert v(r, "ebit", 2025) == pytest.approx(v(r, "revenue", 2025) * d["ebit_margin"].value)
    t = d["effective_tax_rate"].value
    assert v(r, "fcff", 2025) == pytest.approx(v(r, "ebit", 2025) * (1 - t) + v(r, "depreciation_amortization", 2025)
                                               - v(r, "capex", 2025) - v(r, "delta_operating_nwc", 2025))
    assert v(r, "interest_expense", 2025) == pytest.approx(d["cost_of_debt"].value * 100 * 1.05 ** 3)


def test_negative_earnings_and_tax_losses():
    over = {(y, "ebit"): -80.0 for y in (2023, 2024)}
    over |= {(y, "parent_net_income"): -84.0 for y in (2023, 2024)}
    over |= {(y, "tax_expense"): 0.0 for y in (2023, 2024)}
    r = run(overrides=over, policy="conservative_baseline")
    p = r.projection
    assert p.status == "VALID"
    # historical losses reconstruct the opening pools (book: pre-tax; operating: EBIT)
    assert v(r, "operating_tax_loss_pool", 2024) == pytest.approx(160.0)
    assert v(r, "book_tax_loss_pool", 2024) > 160.0
    # recurring margin is the median of history (2 positive, 2 negative) -> still positive here; force negative:
    neg = {(y, "ebit"): -80.0 for y in (2021, 2022, 2023, 2024)} | {(y, "parent_net_income"): -84.0 for y in
                                                                   (2021, 2022, 2023, 2024)}
    r2 = run(overrides=neg, policy="fixed_payout")
    p2 = r2.projection
    assert p2.status == "VALID" and {"NEGATIVE_EBIT", "NEGATIVE_NET_INCOME"} <= set(p2.flags)
    for y in p2.years:
        assert v(r2, "operating_tax", y) == 0.0 and v(r2, "tax_expense", y) == 0.0       # no negative tax
        assert v(r2, "nopat", y) == pytest.approx(v(r2, "ebit", y))                     # NEGATIVE-EBIT-v1
        assert v(r2, "dividends", y) == 0.0                                             # payout on max(NI, 0)
    assert v(r2, "operating_tax_loss_pool", 2025) > v(r2, "operating_tax_loss_pool", 2024)


def test_tax_loss_pool_shields_then_expires():
    # big 2024 loss, then profitable projection: operating tax is reduced while the pool lasts
    over = {(2024, "ebit"): -2000.0, (2024, "parent_net_income"): -1500.0, (2024, "tax_expense"): 0.0}
    r = run(overrides=over)
    p = r.projection
    assert "TAX_LOSS_CARRYFORWARD_USED" in p.flags
    t = r.drivers.estimates["effective_tax_rate"].value
    assert v(r, "operating_tax", 2025) < t * v(r, "ebit", 2025)
    pool = [v(r, "operating_tax_loss_pool", y) for y in [2024, *p.years]]
    assert all(a >= b for a, b in zip(pool, pool[1:]))  # monotonically consumed


def test_working_capital_effect():
    base = run()
    hi = run(overrides={(y, "accounts_receivable"): 400.0 * 1.05 ** i for i, y in enumerate(range(2021, 2025))})
    # higher receivables intensity -> larger NWC -> FCFF lower by exactly the extra dNWC in steady state
    for y in base.projection.years[1:]:
        extra = v(hi, "delta_operating_nwc", y) - v(base, "delta_operating_nwc", y)
        assert extra > 0
        assert v(hi, "fcff", y) == pytest.approx(v(base, "fcff", y) - extra)
    # year-1 change is measured against actual base balances
    assert v(base, "delta_operating_nwc", 2025) == pytest.approx(v(base, "operating_nwc", 2025) - (150 + 120 - 90) * 1.05 ** 3)


def test_capex_effect_and_asset_rollforward():
    base = run()
    hi = run(overrides={(y, "capex"): 100.0 * 1.05 ** i for i, y in enumerate(range(2021, 2025))})
    y = 2025
    dcap = v(hi, "capex", y) - v(base, "capex", y)
    assert dcap > 0 and v(hi, "fcff", y) == pytest.approx(v(base, "fcff", y) - dcap)
    assert v(hi, "other_operating_assets", y) - v(base, "other_operating_assets", y) == pytest.approx(dcap)


def test_acquisitions_separate_from_capex():
    over = {(y, "acquisitions_net"): 60.0 for y in range(2021, 2025)}
    hist = run(policy="historical_continuation", overrides=over)
    cons = run(policy="conservative_baseline", overrides=over)
    y = 2025
    assert v(hist, "acquisitions", y) > 0 and v(cons, "acquisitions", y) == 0
    assert v(hist, "capex", y) == pytest.approx(v(cons, "capex", y))       # capex unaffected
    assert v(hist, "fcff", y) == pytest.approx(v(cons, "fcff", y) - v(hist, "acquisitions", y))


def test_dilution_and_buybacks_change_share_count():
    dil = run(shares=(1e3, 1.02e3, 1.0404e3, 1.061208e3))
    g = dil.drivers.estimates["diluted_share_growth"].value
    assert g == pytest.approx(0.02)
    assert v(dil, "shares_outstanding", 2025) == pytest.approx(1.061208e3 * 1.02)
    assert v(dil, "diluted_shares", 2025) == v(dil, "shares_outstanding", 2025)
    bb = run(policy="min_cash_excess_distribution")
    y = 2025
    assert v(bb, "share_repurchases", y) > 0
    assert v(bb, "shares_repurchased", y) == pytest.approx(v(bb, "share_repurchases", y) / v(bb, "transaction_price", y))
    assert v(bb, "shares_outstanding", y) < v(bb, "shares_outstanding", 2024)


def test_known_pending_bonus_share_applied_in_ex_year():
    load, as_of = company(actions=[ca("B", "bonus_share", "2025-04-25", "2026-06-10", ratio=1.3)])
    r = run_projection(load, instrument_id=INST, as_of=as_of, loaded=CFG)
    assert v(r, "pending_share_ratio", 2026) == 1.3 and v(r, "pending_share_ratio", 2025) == 1.0
    assert v(r, "shares_outstanding", 2026) == pytest.approx(v(r, "shares_outstanding", 2025) * 1.3)
    assert v(r, "transaction_price", 2026) == pytest.approx(10.0 / 1.3)
    assert "PENDING_CORPORATE_ACTION_APPLIED" in r.projection.flags


def test_fcff_fcfe_typed_and_bridge():
    p = run().projection
    assert type(p.fcff) is FCFFSeries and type(p.fcfe) is FCFESeries
    assert p.fcff.years == p.fcfe.years == p.years
    assert p.fcff.values != p.fcfe.values


def test_revolver_draw_is_flagged():
    over = {(2024, "cash"): 0.0, (2024, "total_assets"): 1000 * 1.05 ** 3 - 200 * 1.05 ** 3}
    r = run(overrides=over)
    assert "REVOLVER_DRAW" in r.projection.flags and v(r, "revolver_draw", 2025) > 0
    assert v(r, "cash", 2025) >= CFG.config.projection.min_cash_to_revenue * v(r, "revenue", 2025) - 1e-6


def test_insufficient_data_not_invented():
    load, as_of = company(drop={(2024, "inventory")})
    r = run_projection(load, instrument_id=INST, as_of=as_of, loaded=CFG)
    assert r.projection.status == "INSUFFICIENT_DATA" and r.projection.missing_inputs == ["inventory@FY2024"]
    assert r.projection.items == {}


def test_not_applicable_inventory_is_zero_with_label():
    r = run(overrides={(2024, "inventory"): "na"})
    assert r.projection.status == "VALID"
    assert v(r, "inventory", 2024) == 0.0 and "BASE_INVENTORY_NOT_APPLICABLE_AS_ZERO" in r.projection.flags


def test_rejected_projection_is_not_usable(monkeypatch):
    import vms.statements.projection as proj
    from vms.statements.invariants import Violation
    monkeypatch.setattr(proj, "check_invariants",
                        lambda *a, **k: [Violation(code="CASH_RECONCILIATION_FAIL", year=2025, detail="x")])
    p = run().projection
    assert p.status == "REJECTED" and not p.usable and p.violations[0].code == "CASH_RECONCILIATION_FAIL"


def test_deterministic():
    a, b = run().projection, run().projection
    assert a.model_dump() == b.model_dump()
