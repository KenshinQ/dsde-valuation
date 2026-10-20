"""PIT snapshot builder: version resolution, cumulative conversion, provenance, price adjustment."""

from datetime import date

import pytest

from tests.factories import INST, ca, fobs, mobs, src, ts
from vms.pit.snapshot import build_snapshot


def snap(fin, mkt=(), acts=(), sources=None, as_of="2025-01-01"):
    sources = {s.source_id: s for s in (sources if sources is not None else [src()])}
    s, stats, ic = build_snapshot(instrument_id=INST, as_of=ts(as_of, 15), financial=list(fin), market=list(mkt),
                                  corporate_actions=list(acts), sources=sources)
    return s, stats, {i.code: i for i in ic.issues()}


YTD = [fobs("2024-03-31", "revenue", 100, "2024-04-28"), fobs("2024-06-30", "revenue", 250, "2024-08-28"),
       fobs("2024-09-30", "revenue", 330, "2024-10-28"), fobs("2024-12-31", "revenue", 500, "2025-04-25")]


def test_cn_cumulative_ytd_converted_to_standalone():
    s, _, issues = snap(YTD, as_of="2025-05-01")
    got = {f.period_end.month: f.value_cny for f in s.financials if f.basis == "standalone_quarter"}
    assert got == {3: 100, 6: 150, 9: 80, 12: 170}
    q2 = s.get("revenue", date(2024, 6, 30), "standalone_quarter")
    assert q2.quality_status.value == "derived"
    assert q2.formula == "standalone(2024-06-30) = ytd(2024-06-30) - ytd(2024-03-31)"
    assert len(q2.derived_from) == 2 and all("revenue@2024-0" in r for r in q2.derived_from)
    # the reported cumulative record is preserved alongside the derived one
    assert s.get("revenue", date(2024, 6, 30), "cumulative_ytd").value_cny == 250
    assert issues["CUMULATIVE_DERIVED"].count == 4


def test_no_conversion_without_declared_convention():
    s, _, issues = snap(YTD, sources=[], as_of="2025-05-01")
    assert all(f.basis == "unknown_basis" for f in s.financials)
    assert "CUMULATIVE_DERIVED" not in issues and "CUMULATIVE_CONVENTION_UNKNOWN" not in issues  # flagged by checks


def test_standalone_convention_not_converted():
    s, _, _ = snap(YTD, sources=[src("STANDALONE_QUARTER")], as_of="2025-05-01")
    assert {f.basis for f in s.financials} == {"standalone_quarter"} and all(f.formula is None for f in s.financials)


def test_stocks_never_converted():
    fin = [fobs("2024-03-31", "cash", 100, "2024-04-28"), fobs("2024-06-30", "cash", 120, "2024-08-28")]
    s, _, _ = snap(fin, as_of="2025-01-01")
    assert [f.basis for f in s.financials] == ["balance", "balance"]
    assert [f.value_cny for f in s.financials] == [100, 120]


def test_prior_missing_yields_missing_with_provenance():
    s, _, issues = snap([YTD[1]], as_of="2025-01-01")  # H1 without Q1
    d = s.get("revenue", date(2024, 6, 30), "standalone_quarter")
    assert d.value_cny is None and d.quality_status.value == "missing"
    assert d.flags == ["CUMULATIVE_PRIOR_MISSING"] and d.derived_from and d.formula
    assert issues["CUMULATIVE_PRIOR_MISSING"].count == 1


def test_null_input_propagates_missing():
    fin = [fobs("2024-03-31", "revenue", None, "2024-04-28"), YTD[1]]
    s, _, _ = snap(fin)
    assert s.get("revenue", date(2024, 6, 30), "standalone_quarter").value_cny is None
    assert s.get("revenue", date(2024, 3, 31), "standalone_quarter").value_cny is None


def test_low_confidence_input_propagates():
    fin = [fobs("2024-03-31", "revenue", 100, "2024-04-28", status="low_confidence"), YTD[1]]
    s, _, _ = snap(fin)
    assert s.get("revenue", date(2024, 6, 30), "standalone_quarter").quality_status.value == "low_confidence"


def test_irregular_period_not_converted():
    fin = [fobs("2024-05-31", "revenue", 100, "2024-06-28")]
    s, _, _ = snap(fin)
    assert len(s.financials) == 1 and "IRREGULAR_PERIOD" in s.financials[0].flags


def test_restatement_latest_known_version_used_history_kept():
    fin = [fobs("2023-12-31", "revenue", 100, "2024-04-25"),
           fobs("2023-12-31", "revenue", 97, "2024-08-28", rev="r1")]
    early, _, _ = snap(fin, as_of="2024-06-01")
    late, _, _ = snap(fin, as_of="2024-09-01")
    assert early.get("revenue", date(2023, 12, 31), "cumulative_ytd").value_cny == 100
    rec = late.get("revenue", date(2023, 12, 31), "cumulative_ytd")
    assert rec.value_cny == 97 and rec.revision_id == "r1"
    assert [v.value_cny for v in rec.version_history] == [100, 97]
    assert len(early.get("revenue", date(2023, 12, 31), "cumulative_ytd").version_history) == 1


def test_unit_scale_normalised_to_cny_yuan():
    s, _, _ = snap([fobs("2024-03-31", "cash", 1.5, "2024-04-28", unit="hundred_million")])
    assert s.financials[0].value_cny == pytest.approx(1.5e8)
    assert s.financials[0].reported_value == 1.5 and s.financials[0].reported_unit_scale == "hundred_million"


def test_exact_duplicate_deduped_and_flagged():
    s, _, issues = snap([YTD[0], YTD[0]])
    assert len([f for f in s.financials if f.basis == "cumulative_ytd"]) == 1
    assert issues["DUPLICATE_RECORD"].count == 1


def test_conflicting_versions_and_sources_critical():
    same_time = [fobs("2024-03-31", "revenue", 100, "2024-04-28"),
                 fobs("2024-03-31", "revenue", 101, "2024-04-28", rev="r0b")]
    _, _, issues = snap(same_time)
    assert "CONFLICTING_VERSIONS" in issues
    two_src = [fobs("2024-03-31", "revenue", 100, "2024-04-28"),
               fobs("2024-03-31", "revenue", 105, "2024-04-29", source="T")]
    _, _, issues = snap(two_src, sources=[src(), src(sid="T")])
    assert "CONFLICTING_SOURCES" in issues
    agree = [fobs("2024-03-31", "revenue", 100, "2024-04-28"),
             fobs("2024-03-31", "revenue", 100, "2024-04-29", source="T")]
    _, _, issues = snap(agree, sources=[src(), src(sid="T")])
    assert "CONFLICTING_SOURCES" not in issues


def test_market_conflict_and_duplicate():
    _, _, issues = snap([], [mobs("2024-01-31", 10), mobs("2024-01-31", 11, source="T")])
    assert "CONFLICTING_MARKET_OBS" in issues
    _, _, issues = snap([], [mobs("2024-01-31", 10), mobs("2024-01-31", 10, source="T")])
    assert "DUPLICATE_RECORD" in issues and "CONFLICTING_MARKET_OBS" not in issues


def test_pit_adjustment_uses_only_effective_known_actions():
    mkt = [mobs("2024-06-28", 13.0), mobs("2024-07-31", 10.0, shares=1.3e9)]
    acts = [ca("B", "bonus_share", "2024-06-20", "2024-07-10", ratio=1.3)]
    pending, _, _ = snap([], mkt[:1], acts, as_of="2024-07-01")
    assert pending.corporate_actions[0].status == "pending"
    assert pending.market[0].pit_adjustment_factor == 1.0
    eff, _, _ = snap([], mkt, acts, as_of="2024-08-01")
    assert eff.corporate_actions[0].status == "effective"
    assert eff.market[0].pit_adjusted_close == pytest.approx(10.0)
    assert eff.market[1].pit_adjustment_factor == 1.0


def test_cash_dividend_does_not_adjust_prices():
    acts = [ca("D", "cash_dividend", "2024-06-20", "2024-07-10", cash=0.5)]
    s, _, _ = snap([], [mobs("2024-06-28", 13.0)], acts, as_of="2024-08-01")
    assert s.market[0].pit_adjustment_factor == 1.0


def test_corporate_action_revision_latest_known():
    acts = [ca("D", "cash_dividend", "2024-06-20", "2024-07-10", cash=0.5),
            ca("D", "cash_dividend", "2024-07-01", "2024-07-10", cash=0.45, rev="r1")]
    a, _, _ = snap([], [], acts, as_of="2024-06-25")
    b, _, _ = snap([], [], acts, as_of="2024-07-05")
    assert a.corporate_actions[0].event.cash_per_share == 0.5 and a.corporate_actions[0].known_versions == 1
    assert b.corporate_actions[0].event.cash_per_share == 0.45 and b.corporate_actions[0].known_versions == 2


def test_naive_as_of_rejected():
    from datetime import datetime
    with pytest.raises(ValueError, match="timezone-aware"):
        build_snapshot(instrument_id=INST, as_of=datetime(2024, 1, 1), financial=[], market=[],
                       corporate_actions=[], sources={})
