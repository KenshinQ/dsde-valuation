"""Peer-data leakage tests (SPEC §20 Phase 1 + §21.3).

Future peer membership, survivors-only reconstitutions, and future peer metrics/prices
must not change historical PIT peer samples.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from tests.conftest import make_load
from tests.factories import INST, fobs, mobs
from vms.data import synthetic as S
from vms.pit.asof import parse_as_of
from vms.quality.report import assess
from vms.schemas import PeerObservation, QualityStatus

CST = timezone(timedelta(hours=8))

def _peer(peer_id: str, published: str, *, start=None, end=None, field=None, value=None,
          metric_ts=None, delisted=None) -> PeerObservation:
    kw = dict(
        subject_instrument_id=INST, peer_instrument_id=peer_id,
        published_at=datetime.fromisoformat(published).replace(tzinfo=CST),
        membership_start=start, membership_end=end, delisted_at=None,
        field_name=field, value=value,
        currency="CNY" if value is not None else None,
        unit_scale="unit" if value is not None else None,
        metric_timestamp=None if metric_ts is None else datetime.fromisoformat(metric_ts).replace(tzinfo=CST),
        source_id=S.SYNTHETIC_SOURCE, revision_id="r0",
        quality_status=QualityStatus.OBSERVED if value is not None or field is None else QualityStatus.MISSING,
    )
    if delisted is not None:
        kw["delisted_at"] = datetime.fromisoformat(delisted).replace(tzinfo=CST)
    return PeerObservation(**kw)


def _base_load(peers):
    return make_load([fobs("2022-12-31", "revenue", 100, "2023-04-28")],
                     [mobs("2023-06-30", 10.0)], peers=peers)


def _ids(snap):
    return {p.peer_instrument_id for p in snap.peers}


def test_future_peer_membership_publication_excluded(qcfg):
    peers = [
        _peer("KEEP.SZ", "2021-06-01T09:00:00", start=date(2021, 1, 1)),
        _peer("FUTURE_PUB.SZ", "2024-01-15T09:00:00", start=date(2021, 1, 1)),
    ]
    snap, rep = assess(_base_load(peers), instrument_id=INST, as_of=parse_as_of("2023-06-30")[0], cfg=qcfg)
    assert _ids(snap) == {"KEEP.SZ"}
    assert rep.excluded_post_as_of["peers"] == 1


def test_future_membership_start_excluded_even_if_published_early(qcfg):
    """Index reconstitution announces 2024 join in 2021 docs — still not a member at 2023-06-30."""
    peers = [
        _peer("JOIN_2024.SZ", "2021-01-01T09:00:00", start=date(2024, 1, 1)),
        _peer("ALREADY.SZ", "2021-01-01T09:00:00", start=date(2020, 1, 1)),
    ]
    snap, _ = assess(_base_load(peers), instrument_id=INST, as_of=parse_as_of("2023-06-30")[0], cfg=qcfg)
    assert _ids(snap) == {"ALREADY.SZ"}


def test_survivors_only_reconstitution_does_not_drop_historical_peer(qcfg):
    """Peer known at as_of stays even if a later reconstitution omits it (anti-survivorship)."""
    as_of = parse_as_of("2023-06-30")[0]
    historical = [
        _peer("GONE_LATER.SZ", "2020-01-01T09:00:00", start=date(2019, 1, 1), end=date(2025, 12, 31)),
        _peer("STAY.SZ", "2020-01-01T09:00:00", start=date(2019, 1, 1)),
    ]
    # Post-as_of survivors-only list: drops GONE_LATER, adds NEW_IPO (classic look-ahead bias source)
    future_recon = [
        _peer("STAY.SZ", "2025-01-01T09:00:00", start=date(2019, 1, 1)),
        _peer("NEW_IPO.SZ", "2025-01-01T09:00:00", start=date(2024, 6, 1)),
    ]
    base, _ = assess(_base_load(historical), instrument_id=INST, as_of=as_of, cfg=qcfg)
    with_future, _ = assess(_base_load(historical + future_recon), instrument_id=INST, as_of=as_of, cfg=qcfg)
    assert _ids(base) == {"GONE_LATER.SZ", "STAY.SZ"}
    assert _ids(with_future) == _ids(base)  # future recon cannot change earlier snapshot


def test_future_peer_metric_price_excluded(qcfg):
    peers = [
        _peer("P.SZ", "2021-01-01T09:00:00", start=date(2020, 1, 1),
              field="ev_ebitda", value=10.0, metric_ts="2023-06-30T15:00:00"),
        _peer("P.SZ", "2021-01-01T09:00:00", start=date(2020, 1, 1),
              field="ev_ebitda", value=99.0, metric_ts="2023-07-01T15:00:00"),
    ]
    # Same peer_id two metric vintages: only the one with metric_timestamp <= as_of enters.
    snap, rep = assess(_base_load(peers), instrument_id=INST, as_of=parse_as_of("2023-06-30")[0], cfg=qcfg)
    metrics = [p for p in snap.peers if p.field_name == "ev_ebitda"]
    assert len(metrics) == 1
    assert metrics[0].value_cny == pytest.approx(10.0)
    assert rep.excluded_post_as_of["peers"] == 1


def test_peer_snapshot_invariant_to_information_after_as_of(qcfg):
    as_of = parse_as_of("2023-06-30")[0]
    known = [
        _peer("A.SZ", "2021-01-01T09:00:00", start=date(2020, 1, 1)),
        _peer("B.SZ", "2022-01-01T09:00:00", start=date(2021, 1, 1),
              field="ev_ebitda", value=7.0, metric_ts="2023-03-31T15:00:00"),
    ]
    future = [
        _peer("C.SZ", "2024-01-01T09:00:00", start=date(2020, 1, 1)),
        _peer("B.SZ", "2021-01-01T09:00:00", start=date(2021, 1, 1),
              field="ev_ebitda", value=70.0, metric_ts="2024-03-31T15:00:00"),
        _peer("D.SZ", "2020-01-01T09:00:00", start=date(2024, 1, 1)),
    ]
    full_load = _base_load(known + future)
    known_load = _base_load(known)
    snap_full, rep_full = assess(full_load, instrument_id=INST, as_of=as_of, cfg=qcfg)
    snap_known, rep_known = assess(known_load, instrument_id=INST, as_of=as_of, cfg=qcfg)
    assert snap_full.model_dump(mode="json")["peers"] == snap_known.model_dump(mode="json")["peers"]
    # Exclusion counts differ (full saw more post-as_of peers) but peer payload identical.
    assert snap_full.peers == snap_known.peers
    assert rep_full.excluded_post_as_of["peers"] > rep_known.excluded_post_as_of["peers"]
