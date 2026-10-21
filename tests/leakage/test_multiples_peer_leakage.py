"""Phase 5 multiples: future peer membership must not enter historical samples."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from vms.methods.multiples.peers import build_peer_set
from vms.schemas.observations import PeerObservation, QualityStatus

CST = timezone(timedelta(hours=8))
ASOF = datetime(2023, 6, 30, 15, tzinfo=CST)
SUBJ = "SUBJ.SZ"


def _p(pid, published, *, start=None, field="pe", value=10.0, metric_ts=None):
    return PeerObservation(
        subject_instrument_id=SUBJ, peer_instrument_id=pid,
        published_at=datetime.fromisoformat(published).replace(tzinfo=CST),
        membership_start=start or date(2020, 1, 1),
        field_name=field, value=value, currency="CNY", unit_scale="unit",
        metric_timestamp=(
            None if metric_ts is None
            else datetime.fromisoformat(metric_ts).replace(tzinfo=CST)
        ),
        source_id="SYNTHETIC", revision_id="r0", quality_status=QualityStatus.OBSERVED,
    )


def test_future_reconstitution_does_not_change_historical_peer_multiples():
    historical = [
        _p("A.SZ", "2021-01-01T09:00:00", value=10.0, metric_ts="2023-06-30T15:00:00"),
        _p("B.SZ", "2021-01-01T09:00:00", value=12.0, metric_ts="2023-06-30T15:00:00"),
        _p("C.SZ", "2021-01-01T09:00:00", value=11.0, metric_ts="2023-06-30T15:00:00"),
        _p("D.SZ", "2021-01-01T09:00:00", value=13.0, metric_ts="2023-06-30T15:00:00"),
        _p("E.SZ", "2021-01-01T09:00:00", value=14.0, metric_ts="2023-06-30T15:00:00"),
    ]
    future = [
        _p("NEW_IPO.SZ", "2025-01-01T09:00:00", start=date(2024, 6, 1), value=99.0,
           metric_ts="2025-01-01T15:00:00"),
        _p("A.SZ", "2025-01-01T09:00:00", value=999.0, metric_ts="2025-01-01T15:00:00"),
    ]
    base = build_peer_set(subject_instrument_id=SUBJ, as_of=ASOF, metric_field="pe", peers=historical)
    mixed = build_peer_set(
        subject_instrument_id=SUBJ, as_of=ASOF, metric_field="pe", peers=historical + future,
    )
    assert [i.peer_instrument_id for i in base.included] == [i.peer_instrument_id for i in mixed.included]
    assert base.multiples == mixed.multiples
    assert "NEW_IPO.SZ" not in {i.peer_instrument_id for i in mixed.included}
    # Future metric vintage for A must not replace the PIT value
    a = next(i for i in mixed.included if i.peer_instrument_id == "A.SZ")
    assert a.multiple == 10.0
