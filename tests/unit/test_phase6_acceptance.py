"""VMS-0.2 Phase 6 acceptance (SPEC §20 Phase 6 / §12.4 / §12.7 / §24)."""

from __future__ import annotations

import pytest

from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.asset_based import run_eligible_phase6_methods
from vms.methods.nav.math import NavLine, book_totals_are_not_nav, compute_nav
from vms.methods.protocol import ValuationContext
from vms.methods.rim.math import assess_clean_surplus, residual_income_value
from vms.methods.sotp.math import compute_sotp
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.router import route_methods
from vms.schemas.config import load_config
from vms.schemas.contracts import MethodEligibilityStatus, ProfileLabel, ValuationTarget


def _financial_profile(repo):
    loaded = load_config(repo / "config/default.yaml")
    data = load_fixture(fixtures_dir() / "financial_institution.json")
    feats = features_from_fixture(data)
    profile = classify_profile(feats)
    return loaded, profile, frozenset(data.get("available_fields") or [])


def _holding_profile(repo):
    loaded = load_config(repo / "config/default.yaml")
    data = load_fixture(fixtures_dir() / "holding.json")
    feats = features_from_fixture(data)
    profile = classify_profile(feats)
    return loaded, profile, frozenset(data.get("available_fields") or [])


# ---- AC1: RIM validates book-equity and clean-surplus or becomes ineligible ----
def test_ac1_rim_clean_surplus_or_ineligible():
    # Unassessable: missing dividends/OCI/issuance without zeros_explicit
    cs = assess_clean_surplus(
        beginning_book=100.0, net_income=12.0,
        dividends=None, net_issuance=None, oci=None,
        ending_book_observed=None, zeros_explicit=False,
    )
    assert cs.assessable is False and cs.treatment == "UNASSESSABLE"

    bad = residual_income_value(
        book_equity_0=100.0, net_income=[12.0, 13.0], cost_of_equity=0.10,
        # no div/iss/oci, zeros_explicit False
    )
    assert bad.valid is False and bad.invalid_reason == "CLEAN_SURPLUS_UNASSESSABLE"

    # Negative book → ineligible
    neg = residual_income_value(
        book_equity_0=-5.0, net_income=[1.0], cost_of_equity=0.10,
        dividends=[0.0], net_issuance=[0.0], oci=[0.0], zeros_explicit=True,
    )
    assert neg.valid is False and neg.invalid_reason == "NEGATIVE_BOOK_EQUITY"

    # Large unexplained deviation → CLEAN_SURPLUS_FAIL
    fail = residual_income_value(
        book_equity_0=100.0, net_income=[12.0], cost_of_equity=0.10,
        dividends=[4.0], net_issuance=[0.0], oci=[0.0],
        ending_book_observed=200.0,  # implied end = 100+12-4=108
        zeros_explicit=True, max_deviation_ratio=0.05,
    )
    assert fail.valid is False and fail.invalid_reason == "CLEAN_SURPLUS_FAIL"

    # Hand fixture MODELED
    # RI1 = 12 - 0.1*100 = 2; BE1 = 100+12-4 = 108
    # RI2 = 12.5 - 0.1*108 = 1.7; BE2 = 108+12.5-4.2 = 116.3
    # RI3 = 13 - 0.1*116.3 = 1.37
    ok = residual_income_value(
        book_equity_0=100.0,
        net_income=[12.0, 12.5, 13.0],
        dividends=[4.0, 4.2, 4.4],
        net_issuance=[0.0, 0.0, 0.0],
        oci=[0.0, 0.0, 0.0],
        cost_of_equity=0.10,
        terminal_growth=0.02,
        zeros_explicit=True,
        diluted_shares=10.0,
    )
    assert ok.valid is True
    assert ok.clean_surplus and ok.clean_surplus.treatment == "MODELED"
    assert ok.equity_value is not None and ok.equity_value > ok.book_equity_0
    # PV check: be0 + pv_ri + pv_tv
    assert abs(ok.equity_value - (ok.book_equity_0 + ok.pv_ri + ok.pv_tv)) < 1e-9


def test_ac1_rim_hand_fixture_numeric():
    ok = residual_income_value(
        book_equity_0=100.0,
        net_income=[12.0],
        dividends=[0.0],
        net_issuance=[0.0],
        oci=[0.0],
        cost_of_equity=0.10,
        terminal_growth=0.0,
        zeros_explicit=True,
    )
    assert ok.valid
    # RI1 = 12 - 10 = 2; TV = 2*1.0/0.10 = 20; PV_RI=2/1.1; PV_TV=20/1.1
    # Equity = 100 + 2/1.1 + 20/1.1 = 100 + 20 = 120
    assert abs(ok.residual_income[0] - 2.0) < 1e-12
    assert abs(ok.equity_value - 120.0) < 1e-9


# ---- AC2: NAV requires explicit asset/claim assumptions; book ≠ fair ----
def test_ac2_nav_requires_explicit_fair_not_raw_book():
    refused = book_totals_are_not_nav(total_assets=200.0, total_liabilities=80.0)
    assert refused.valid is False
    assert refused.unsupported is True
    assert refused.invalid_reason == "MISSING_ASSET_INPUTS"
    assert "BOOK_NE_FAIR" in refused.flags

    # fair=book without justification → gap
    bad = compute_nav(assets=[
        NavLine(line_id="ppe", kind="asset", book_value=100.0, fair_value=100.0, justification=""),
    ])
    assert bad.valid is False
    assert bad.unsupported is True
    assert any("book_as_fair" in g or "justification" in g for g in bad.data_gap)

    # Explicit FV + haircut
    ok = compute_nav(
        assets=[
            NavLine(
                line_id="mine", kind="asset", book_value=100.0, fair_value=120.0,
                haircut=0.10, justification="reserve/production DCF appraisal before as_of",
                basis="reserve",
            ),
            NavLine(
                line_id="cash", kind="asset", book_value=20.0, fair_value=20.0,
                justification="cash at amortized cost equals fair value", basis="market",
            ),
        ],
        claims=[
            NavLine(
                line_id="debt", kind="claim", book_value=40.0, fair_value=40.0,
                justification="debt at par", basis="configured",
            ),
        ],
        corporate_overhead_pv=5.0,
        disposal_tax=2.0,
    )
    assert ok.valid is True
    # assets: 120*0.9 + 20 = 128; claims 40; -5 -2 = 81
    assert abs(ok.nav_equity - 81.0) < 1e-9
    assert ok.reconciliation["gross_asset_fair_after_haircut"] == pytest.approx(128.0)


# ---- AC3: SOTP reconciles segments, group costs, debt, minorities, inter-segment ----
def test_ac3_sotp_reconciles_segments_and_group_items():
    ok = compute_sotp(
        segments=[
            {"segment_id": "a", "equity_value": 100.0, "method": "configured",
             "inter_segment_receivable": 10.0, "inter_segment_payable": 0.0},
            {"segment_id": "b", "equity_value": 80.0, "method": "configured",
             "inter_segment_receivable": 0.0, "inter_segment_payable": 10.0},
        ],
        inter_segment_elimination=0.0,  # 10 - 10
        group_costs_pv=5.0,
        parent_debt=30.0,
        minority_interest=8.0,
        non_operating_assets=12.0,
        holding_discount={"rate": 0.10, "uncertain": True, "rationale": "conglomerate prior"},
    )
    assert ok.valid is True
    # gross=180; elim=0; pre_hd = 180-0-5-30-8+12 = 149; after hd = 149*0.9 = 134.1
    assert ok.reconciliation["sum_segment_equity"] == pytest.approx(180.0)
    assert ok.reconciliation["equity_before_holding_discount"] == pytest.approx(149.0)
    assert ok.equity_value == pytest.approx(134.1)
    assert ok.holding_discount["rate"] == pytest.approx(0.10)
    assert "HOLDING_DISCOUNT_EXPLICIT" in ok.flags

    # Mismatch elimination vs segment claims
    bad = compute_sotp(
        segments=[
            {"segment_id": "a", "equity_value": 50.0, "inter_segment_receivable": 5.0},
            {"segment_id": "b", "equity_value": 50.0, "inter_segment_payable": 5.0},
        ],
        inter_segment_elimination=99.0,
    )
    assert bad.valid is False and bad.invalid_reason == "INTER_SEGMENT_UNRECONCILED"


# ---- AC4: bank / holding fixtures route appropriately ----
def test_ac4_financial_routes_to_rim_industrial_fcff_disabled(repo):
    loaded, profile, fields = _financial_profile(repo)
    assert profile.primary_profile is ProfileLabel.FINANCIAL_INSTITUTION
    registry = build_registry_from_config(loaded.method_registry)

    # Industrial FCFF / EV EBITDA disabled even with full industrial fields
    industrial_fields = fields | frozenset({
        "revenue", "ebit", "cash_flow_from_operations", "capex",
        "interest_bearing_debt", "cash", "depreciation_amortization",
    })
    route = route_methods(
        registry=registry, profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=industrial_fields,
    )
    by_id = {e.method_id: e for e in route.eligibility}
    assert by_id["fcff_dcf"].eligible is False
    # ev_ebitda not in FUNDAMENTAL target supported_targets — check RELATIVE
    route_rel = route_methods(
        registry=registry, profile=profile,
        target=ValuationTarget.RELATIVE_VALUE_CURRENT,
        available_fields=industrial_fields, peer_count=8,
    )
    by_rel = {e.method_id: e for e in route_rel.eligibility}
    assert by_rel["ev_ebitda"].eligible is False
    assert by_rel["pb"].eligible is True  # bank P/B candidate

    rim_inputs = {
        "book_equity_0": 200.0,
        "net_income": [24.0, 25.0, 26.0],
        "dividends": [8.0, 8.5, 9.0],
        "net_issuance": [0.0, 0.0, 0.0],
        "oci": [0.0, 0.0, 0.0],
        "zeros_explicit": True,
        "cost_of_equity": 0.10,
        "terminal_growth": 0.02,
    }
    run = run_eligible_phase6_methods(
        registry=registry, profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        loaded=loaded, available_fields=fields,
        rim_inputs=rim_inputs,
        method_assumptions={"residual_income": rim_inputs},
    )
    assert "residual_income" in run.eligible_run
    rim = next(r for r in run.results if r.method_id == "residual_income")
    assert rim.status is MethodEligibilityStatus.VALID
    assert rim.values.get("ev_bridge_applied") is False
    assert run.ensemble is None


def test_ac4_holding_routes_to_sotp_nav_or_visible_gap(repo):
    loaded, profile, fields = _holding_profile(repo)
    assert profile.primary_profile is ProfileLabel.HOLDING_OR_CONGLOMERATE
    registry = build_registry_from_config(loaded.method_registry)

    # With schedules → runnable
    nav_in = {
        "assets": [{
            "line_id": "sub", "kind": "asset", "book_value": 50.0, "fair_value": 70.0,
            "haircut": 0.0, "justification": "listed subsidiary market value", "basis": "market",
        }],
        "claims": [{
            "line_id": "debt", "kind": "claim", "book_value": 20.0, "fair_value": 20.0,
            "justification": "debt at par", "basis": "configured",
        }],
    }
    sotp_in = {
        "segments": [
            {"segment_id": "a", "equity_value": 70.0, "method": "configured"},
            {"segment_id": "b", "equity_value": 30.0, "method": "configured"},
        ],
        "group_costs_pv": 5.0,
        "parent_debt": 20.0,
        "minority_interest": 0.0,
        "non_operating_assets": 0.0,
        "holding_discount": {"rate": 0.1, "rationale": "holding discount prior"},
    }
    run = run_eligible_phase6_methods(
        registry=registry, profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        loaded=loaded, available_fields=fields,
        nav_inputs=nav_in, sotp_inputs=sotp_in,
        method_assumptions={"nav": nav_in, "sotp": sotp_in},
    )
    assert "nav" in run.eligible_run and "sotp" in run.eligible_run
    assert run.ensemble is None

    # Without schedules → visible unsupported / data-gap
    gap = run_eligible_phase6_methods(
        registry=registry, profile=profile,
        target=ValuationTarget.ASSET_NAV,
        loaded=loaded, available_fields=fields,
        nav_inputs={"total_assets": 200.0, "total_liabilities": 100.0},
        sotp_inputs={},
    )
    assert gap.eligible_run == []
    for r in gap.results:
        assert r.status is MethodEligibilityStatus.INELIGIBLE
        assert r.values == {}
        assert r.diagnostics.get("unsupported") is True
        assert r.diagnostics.get("data_gap")


# ---- AC5: missing segment/asset data cannot generate apparently complete NAV ----
def test_ac5_missing_asset_or_segment_cannot_look_complete(repo):
    loaded, profile, fields = _holding_profile(repo)
    registry = build_registry_from_config(loaded.method_registry)
    plugin = registry.plugin("nav")
    ctx = ValuationContext(
        instrument_id=profile.instrument_id, as_of=profile.as_of,
        target=ValuationTarget.ASSET_NAV, profile=profile,
        available_fields=fields, loaded=loaded,
        nav_inputs={"total_assets": 999.0, "total_liabilities": 100.0},
    )
    result = plugin.value_paths(ctx, None, MethodConfig(method_id="nav"))
    assert result.status is MethodEligibilityStatus.INELIGIBLE
    assert result.values == {}
    assert "MISSING_ASSET_INPUTS" in result.reason_codes
    assert result.diagnostics["unsupported"] is True
    # Must not look like a complete NAV number
    assert "nav_equity" not in result.values

    sotp = registry.plugin("sotp")
    ctx2 = ctx.model_copy(update={
        "target": ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        "sotp_inputs": {"parent_debt": 40.0},
        "nav_inputs": {},
    })
    r2 = sotp.value_paths(ctx2, None, MethodConfig(method_id="sotp"))
    assert r2.status is MethodEligibilityStatus.INELIGIBLE
    assert r2.values == {}
    assert "MISSING_SEGMENT_INPUTS" in r2.reason_codes
    assert r2.diagnostics["unsupported"] is True


def test_phase6_methods_registered_implemented(repo):
    loaded = load_config(repo / "config/default.yaml")
    reg = build_registry_from_config(loaded.method_registry)
    for mid in ("residual_income", "nav", "sotp"):
        e = reg.get(mid)
        assert e is not None and e.enabled and e.implementation_status.value == "IMPLEMENTED"
        assert reg.plugin(mid).__class__.__name__ != "DeclaredStubMethod"
