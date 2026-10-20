"""Quality gate: each applicable §6.1 check, status precedence, production block, exploratory override."""

import pytest

from tests.conftest import make_load
from tests.factories import INST, ca, fobs, mobs, src, ts
from vms.quality.report import GateError, QualityState, assess, gate

BASE_FIN = [fobs("2024-03-31", "revenue", 100, "2024-04-28"), fobs("2024-03-31", "capex", 5, "2024-04-28"),
            fobs("2024-03-31", "total_assets", 300, "2024-04-28"),
            fobs("2024-03-31", "total_liabilities", 100, "2024-04-28"),
            fobs("2024-03-31", "total_equity", 200, "2024-04-28")]
BASE_MKT = [mobs("2024-04-30", 10.0)]


def run(fin=BASE_FIN, mkt=BASE_MKT, acts=(), sources=None, as_of="2024-12-31", qcfg=None, ca_provided=True,
        mode="production", reason=None):
    load = make_load(fin, mkt, acts, sources=[src()] if sources is None else sources, ca_provided=ca_provided)
    snap, rep = assess(load, instrument_id=INST, as_of=ts(as_of, 15), cfg=qcfg, mode=mode, override_reason=reason)
    return snap, rep, {i.code: i for i in rep.issues}


def test_clean_passes(qcfg):
    _, rep, issues = run(qcfg=qcfg)
    assert rep.status is QualityState.PASS, issues
    assert rep.pit_complete and rep.usable_for_production


def test_ev_bridge_deferred_and_all_checks_listed(qcfg):
    _, rep, _ = run(qcfg=qcfg)
    st = {c.check: c.status for c in rep.checks}
    assert st["EV_BRIDGE"] == "DEFERRED"
    assert all(v == "RUN" for k, v in st.items() if k != "EV_BRIDGE")
    for c in ("DUPLICATES_CONFLICTS", "UNIT_CURRENCY", "POST_AS_OF", "PERIOD_COVERAGE", "CUMULATIVE_CONVERSION",
              "BALANCE_SHEET_IDENTITY", "CASH_FLOW_SIGN_UNIT", "SHARE_COUNT_CORPORATE_ACTIONS", "PRICE_ADJUSTMENT",
              "PROVENANCE"):
        assert c in st


@pytest.mark.parametrize("extra,code", [
    ([fobs("2024-06-30", "capex", -5, "2024-08-28")], "SIGN_CONVENTION_VIOLATION"),
    ([fobs("2024-06-30", "revenue", -1, "2024-08-28")], "SIGN_CONVENTION_VIOLATION"),
    ([fobs("2024-06-30", "cash", -1, "2024-08-28")], "SIGN_CONVENTION_VIOLATION"),
    ([fobs("2024-06-30", "revenue", 250, "2024-08-28", currency="USD")], "CURRENCY_NOT_CNY"),
    ([fobs("2024-06-30", "revenue", 250, "2024-08-28", stype="balance_sheet")], "STATEMENT_TYPE_MISMATCH"),
    ([fobs("2024-03-31", "revenue", 101, "2024-04-28", rev="x")], "CONFLICTING_VERSIONS"),
])
def test_critical_blocks(qcfg, extra, code):
    _, rep, issues = run(fin=BASE_FIN + extra, qcfg=qcfg)
    assert code in issues and issues[code].severity.value == "CRITICAL"
    assert rep.status is QualityState.BLOCKED and not rep.usable_for_production
    with pytest.raises(GateError, match="BLOCKED") as ei:
        gate(rep)
    assert code in str(ei.value) and "--mode exploratory" in str(ei.value)


def test_no_market_or_financial_data_blocks(qcfg):
    _, rep, issues = run(mkt=[], qcfg=qcfg)
    assert "NO_MARKET_DATA" in issues and rep.status is QualityState.BLOCKED
    _, rep, issues = run(fin=[], qcfg=qcfg)
    assert "NO_FINANCIAL_DATA" in issues and rep.status is QualityState.BLOCKED


def test_exploratory_override_recorded(qcfg):
    fin = BASE_FIN + [fobs("2024-06-30", "capex", -5, "2024-08-28")]
    with pytest.raises(ValueError, match="override reason"):
        run(fin=fin, qcfg=qcfg, mode="exploratory")
    _, rep, _ = run(fin=fin, qcfg=qcfg, mode="exploratory", reason="investigating provider sign convention")
    assert rep.status is QualityState.BLOCKED and not rep.usable_for_production  # status is NOT laundered
    assert rep.override.reason == "investigating provider sign convention"
    assert rep.override.overridden_critical_codes == ["SIGN_CONVENTION_VIOLATION"]
    gate(rep)  # exploratory: does not raise


@pytest.mark.parametrize("fin_extra,code", [
    ([fobs("2024-09-30", "total_assets", 300, "2024-10-28"), fobs("2024-09-30", "total_liabilities", 100, "2024-10-28"),
      fobs("2024-09-30", "total_equity", 150, "2024-10-28")], "BALANCE_SHEET_IDENTITY_FAIL"),
    ([fobs("2024-09-30", "total_assets", 300, "2024-10-28")], "BALANCE_SHEET_IDENTITY_UNCHECKED"),
    ([fobs("2024-06-30", "revenue", 250, "2024-08-28"), fobs("2024-06-30", "capex", 2000, "2024-08-28")],
     "CAPEX_REVENUE_IMPLAUSIBLE"),
    ([fobs("2024-03-31", "revenue", 1_000_000, "2024-05-10", rev="r1")], "SUSPECTED_UNIT_MISMATCH"),
    ([fobs("2024-06-30", "total_assets", 3_000_000, "2024-08-28")], "SUSPECTED_UNIT_MISMATCH"),
    ([fobs("2024-09-30", "revenue", 330, "2024-10-28")], "MISSING_QUARTER"),
    ([fobs("2024-05-31", "revenue", 330, "2024-06-28")], "IRREGULAR_PERIOD"),
    ([fobs("2024-06-30", "revenue", 250, "2024-08-28"), fobs("2024-06-30", "revenue", 250, "2024-08-28")],
     "DUPLICATE_RECORD"),
    ([fobs("2024-06-30", "foo_metric", 1, "2024-08-28")], "NON_CANONICAL_FIELD"),
])
def test_warnings(qcfg, fin_extra, code):
    _, rep, issues = run(fin=BASE_FIN + fin_extra, qcfg=qcfg)
    assert code in issues, issues
    if issues[code].severity.value == "WARNING":
        assert rep.status is QualityState.PASS_WITH_WARNINGS


def test_cumulative_unknown_flagged(qcfg):
    _, rep, issues = run(sources=[src("UNKNOWN")], qcfg=qcfg)
    assert "CUMULATIVE_CONVENTION_UNKNOWN" in issues


def test_pit_incomplete_when_source_undeclared_or_latest_only(qcfg):
    _, rep, issues = run(sources=[], qcfg=qcfg)
    assert "SOURCE_UNDECLARED" in issues and rep.status is QualityState.PIT_INCOMPLETE and not rep.pit_complete
    assert rep.usable_for_production  # PIT_INCOMPLETE does not block, it forbids unbiased-history claims
    _, rep, issues = run(sources=[src(versioning="LATEST_ONLY")], qcfg=qcfg)
    assert "SOURCE_NOT_FULL_HISTORY" in issues and rep.status is QualityState.PIT_INCOMPLETE


def test_blocked_dominates_pit_incomplete(qcfg):
    _, rep, _ = run(fin=BASE_FIN + [fobs("2024-06-30", "capex", -5, "2024-08-28")], sources=[], qcfg=qcfg)
    assert rep.status is QualityState.BLOCKED


def test_share_count_change_explained_vs_unexplained(qcfg):
    mkt = [mobs("2024-06-28", 13.0, shares=1e9), mobs("2024-07-31", 10.0, shares=1.3e9)]
    bonus = [ca("B", "bonus_share", "2024-06-20", "2024-07-10", ratio=1.3)]
    _, _, issues = run(mkt=mkt, acts=bonus, qcfg=qcfg)
    assert "UNEXPLAINED_SHARE_CHANGE" not in issues
    _, _, issues = run(mkt=mkt, acts=[], qcfg=qcfg)
    assert "UNEXPLAINED_SHARE_CHANGE" in issues
    # action announced only after as_of cannot explain a change seen before as_of... and is not known
    _, _, issues = run(mkt=mkt, acts=[ca("B", "bonus_share", "2024-09-20", "2024-10-10", ratio=1.3)], qcfg=qcfg)
    assert "UNEXPLAINED_SHARE_CHANGE" in issues


def test_corporate_actions_table_missing_flagged(qcfg):
    _, _, issues = run(ca_provided=False, qcfg=qcfg)
    assert "CORPORATE_ACTIONS_UNAVAILABLE" in issues


def test_vendor_adjustment_factor_consistency(qcfg):
    mkt = [mobs("2024-06-28", 13.0, adj=10.0), mobs("2024-07-31", 10.0, shares=1.3e9, adj=10.0)]
    bonus = [ca("B", "bonus_share", "2024-06-20", "2024-07-10", ratio=1.3)]
    _, _, issues = run(mkt=mkt, acts=bonus, qcfg=qcfg)
    assert "VENDOR_ADJ_FACTOR_UNEXPLAINED" not in issues and "VENDOR_ADJUSTED_CLOSE_EXCLUDED" in issues
    bad = [mobs("2024-05-31", 12.0, adj=12.0), mobs("2024-06-28", 13.0, adj=10.0)]
    _, _, issues = run(mkt=bad, qcfg=qcfg)
    assert "VENDOR_ADJ_FACTOR_UNEXPLAINED" in issues


def test_market_currency_not_cny(qcfg):
    _, rep, issues = run(mkt=[mobs("2024-04-30", 10.0, currency="HKD")], qcfg=qcfg)
    assert "CURRENCY_NOT_CNY" in issues and rep.status is QualityState.BLOCKED


def test_missing_values_preserved_and_reported(qcfg):
    fin = BASE_FIN + [fobs("2024-03-31", "minority_interest", None, "2024-04-28")]
    snap, _, issues = run(fin=fin, qcfg=qcfg)
    mi = [f for f in snap.financials if f.field_name == "minority_interest"][0]
    assert mi.value_cny is None and mi.quality_status.value == "missing" and mi.source_id == "S"
    assert "EXPLICIT_MISSING_VALUE" in issues


def test_post_as_of_counted(qcfg):
    _, rep, issues = run(fin=BASE_FIN + [fobs("2025-03-31", "revenue", 1, "2025-04-28")], qcfg=qcfg)
    assert rep.excluded_post_as_of["financial"] == 1 and issues["POST_AS_OF_EXCLUDED"].severity.value == "INFO"


def test_restatement_and_late_publication_info(qcfg):
    fin = BASE_FIN + [fobs("2024-03-31", "revenue", 99, "2024-08-28", rev="r1"),
                      fobs("2023-12-31", "revenue", 400, "2024-06-20")]
    _, rep, issues = run(fin=fin, qcfg=qcfg)
    assert issues["RESTATEMENT_KNOWN"].count == 1 and "LATE_PUBLICATION" in issues
