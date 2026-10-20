"""Leakage tests (SPEC §19, Phase 1 acceptance).

Core invariant: a snapshot (and every quality finding except the post-as_of *count*) built at
``as_of`` from the full dataset is identical to one built from only the records known at
``as_of``. Hence later publications, restatements, prices, corporate actions and action revisions
cannot change earlier snapshots.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.conftest import make_load
from tests.factories import fobs
from vms.data import synthetic as S
from vms.pit.asof import parse_as_of
from vms.quality.report import assess

INST = S.SYNTHETIC_INSTRUMENT


def _assess(load, as_of, qcfg):
    return assess(load, instrument_id=INST, as_of=as_of, cfg=qcfg)


def _known_only(syn, as_of):
    fin, mkt, ca = syn
    return make_load([o for o in fin if o.published_at <= as_of], [o for o in mkt if o.timestamp <= as_of],
                     [e for e in ca if e.announced_at <= as_of])


def _comparable(snap, rep):
    return (snap.model_dump(mode="json"), rep.status,
            [i.model_dump(mode="json") for i in rep.issues if i.code != "POST_AS_OF_EXCLUDED"])


AS_OFS = st.builds(lambda d, h: datetime.combine(date(2021, 1, 1) + timedelta(days=d), time(h), S.TZ),
                   st.integers(0, 365 * 5), st.integers(0, 23))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(as_of=AS_OFS)
def test_snapshot_invariant_to_information_after_as_of(syn, qcfg, as_of):
    full = _comparable(*_assess(make_load(*syn), as_of, qcfg))
    known = _comparable(*_assess(_known_only(syn, as_of), as_of, qcfg))
    assert full == known


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(as_of=AS_OFS)
def test_every_snapshot_input_known_at_as_of(syn, qcfg, as_of):
    snap, _ = _assess(make_load(*syn), as_of, qcfg)
    for f in snap.financials:
        assert f.published_at <= as_of
        assert all(v.published_at <= as_of for v in f.version_history)
    assert all(m.timestamp <= as_of for m in snap.market)
    assert all(a.event.announced_at <= as_of for a in snap.corporate_actions)
    assert all(a.status == "pending" for a in snap.corporate_actions if a.event.ex_date > as_of.astimezone(S.TZ).date())


# ---------------------------------------------------------------- financials
def test_future_publication_excluded_late_annual_report(syn_load, qcfg):
    snap, rep = _assess(syn_load, parse_as_of("2024-05-15")[0], qcfg)
    assert not [f for f in snap.financials if f.period_end == S.LATE_PERIOD]
    assert {i.code for i in rep.issues} >= {"MISSING_QUARTER"}
    snap2, _ = _assess(syn_load, parse_as_of("2024-06-21")[0], qcfg)
    assert [f for f in snap2.financials if f.period_end == S.LATE_PERIOD]


def test_date_only_as_of_excludes_evening_publication_same_day(syn_load, qcfg):
    q1 = date(2023, 3, 31)  # published 2023-04-28 18:00
    on_day, _ = _assess(syn_load, parse_as_of("2023-04-28")[0], qcfg)
    next_day, _ = _assess(syn_load, parse_as_of("2023-04-29")[0], qcfg)
    assert on_day.get("revenue", q1) is None
    assert next_day.get("revenue", q1) is not None


def test_future_restatement_excluded(syn_load, qcfg):
    before, _ = _assess(syn_load, parse_as_of("2023-08-28")[0], qcfg)   # 15:00, restatement at 18:00
    after, _ = _assess(syn_load, parse_as_of("2023-08-29")[0], qcfg)
    b = before.get("revenue", S.RESTATED_PERIOD, "cumulative_ytd")
    a = after.get("revenue", S.RESTATED_PERIOD, "cumulative_ytd")
    assert b.revision_id == "r0" and len(b.version_history) == 1
    assert a.revision_id == "r1" and a.value_cny < b.value_cny and len(a.version_history) == 2
    # derived standalone Q4 uses only the versions known at each as_of
    qb = before.get("revenue", S.RESTATED_PERIOD, "standalone_quarter")
    qa = after.get("revenue", S.RESTATED_PERIOD, "standalone_quarter")
    assert any("#r0@" in r for r in qb.derived_from) and not any("#r1@" in r for r in qb.derived_from)
    assert any("#r1@" in r for r in qa.derived_from)
    assert qa.value_cny == pytest.approx(qb.value_cny - (b.value_cny - a.value_cny))


def test_injected_future_restatement_of_old_period_does_not_change_old_snapshot(syn, qcfg):
    as_of = parse_as_of("2023-01-15")[0]
    base, rep0 = _assess(make_load(*syn), as_of, qcfg)
    sneaky = [o.model_copy(update={"value": o.value * 10, "revision_id": "r9",
                                   "published_at": datetime(2025, 1, 1, 9, tzinfo=S.TZ)})
              for o in syn[0] if o.period_end == date(2022, 9, 30) and o.value is not None]
    snap, rep = _assess(make_load(syn[0] + sneaky, syn[1], syn[2]), as_of, qcfg)
    assert _comparable(snap, rep) == _comparable(base, rep0)


# ---------------------------------------------------------------- prices
def test_prices_after_as_of_excluded_close_at_as_of_included(syn_load, qcfg):
    snap, _ = _assess(syn_load, parse_as_of("2023-05-31")[0], qcfg)   # obs at 2023-05-31 15:00
    assert snap.market[-1].timestamp == datetime(2023, 5, 31, 15, tzinfo=S.TZ)
    early, _ = _assess(syn_load, datetime(2023, 5, 31, 14, 59, tzinfo=S.TZ), qcfg)
    assert early.market[-1].timestamp == datetime(2023, 4, 30, 15, tzinfo=S.TZ)


def test_vendor_forward_adjusted_close_never_enters_snapshot(syn, syn_load, qcfg):
    as_of = parse_as_of("2023-12-29")[0]   # bonus share not yet announced
    snap, _ = _assess(syn_load, as_of, qcfg)
    assert "adjusted_close" not in snap.market[0].model_dump()
    vendor = {m.timestamp: m.adjusted_close for m in syn[1]}
    for m in snap.market:
        assert m.pit_adjusted_close == m.raw_close            # no future 1.3 factor
        assert vendor[m.timestamp] == pytest.approx(m.raw_close / S.BONUS_RATIO, rel=1e-3)  # vendor embeds it


# ---------------------------------------------------------------- corporate actions
def test_corporate_action_not_known_before_announcement(syn_load, qcfg):
    snap, _ = _assess(syn_load, parse_as_of("2024-06-20")[0], qcfg)   # 15:00; announced 18:00
    assert snap.corporate_actions == []
    snap, _ = _assess(syn_load, parse_as_of("2024-06-21")[0], qcfg)
    assert {a.event.action_id: a.status for a in snap.corporate_actions} == \
        {S.BONUS_ACTION_ID: "pending", S.DIVIDEND_ACTION_ID: "pending"}
    assert all(m.pit_adjustment_factor == 1.0 for m in snap.market)  # pending actions do not adjust


def test_corporate_action_revision_after_as_of_invisible(syn_load, qcfg):
    a, _ = _assess(syn_load, parse_as_of("2024-07-01")[0], qcfg)   # revision at 18:00
    b, _ = _assess(syn_load, parse_as_of("2024-07-02")[0], qcfg)
    div = lambda s: next(x for x in s.corporate_actions if x.event.action_id == S.DIVIDEND_ACTION_ID)  # noqa: E731
    assert div(a).event.cash_per_share == 0.50 and div(a).known_versions == 1
    assert div(b).event.cash_per_share == 0.45 and div(b).known_versions == 2


def test_effective_action_adjusts_only_prior_prices(syn_load, qcfg):
    snap, _ = _assess(syn_load, parse_as_of("2024-08-01")[0], qcfg)
    for m in snap.market:
        expected = 1 / S.BONUS_RATIO if m.timestamp.date() < S.EX_DATE else 1.0
        assert m.pit_adjustment_factor == pytest.approx(expected)


def test_future_corporate_action_does_not_explain_past_share_change(qcfg):
    from tests.factories import INST as T, ca, mobs, ts
    mkt = [mobs("2024-06-28", 13.0, shares=1e9), mobs("2024-07-31", 10.0, shares=1.3e9)]
    load = make_load([fobs("2024-03-31", "revenue", 1, "2024-04-28")], mkt,
                     [ca("B", "bonus_share", "2024-08-20", "2024-08-30", ratio=1.3)])
    _, rep = assess(load, instrument_id=T, as_of=ts("2024-08-01", 15), cfg=qcfg)
    assert "UNEXPLAINED_SHARE_CHANGE" in {i.code for i in rep.issues}
