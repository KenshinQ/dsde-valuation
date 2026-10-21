"""VMS-0.2 Phase 1: PeerObservation schema + PIT peer snapshot filtering."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tests.conftest import make_load
from tests.factories import INST as SUBJ, fobs, mobs
from vms.pit.asof import parse_as_of
from vms.pit.snapshot import build_snapshot, peer_known_at
from vms.quality.report import assess
from vms.schemas import PeerObservation, QualityStatus

CST = timezone(timedelta(hours=8))

def _peer(**kw) -> PeerObservation:
    base = dict(
        subject_instrument_id=SUBJ,
        peer_instrument_id="PEER0001.SZ",
        published_at=datetime(2022, 6, 1, 9, tzinfo=CST),
        membership_start=date(2022, 1, 1),
        membership_end=None,
        field_name=None,
        value=None,
        currency=None,
        unit_scale=None,
        source_id="SYNTHETIC",
        revision_id="r0",
        quality_status="observed",
    )
    base.update(kw)
    return PeerObservation(**base)


def test_quality_status_accepts_spec_uppercase_aliases(fin_kwargs):
    from vms.schemas import FinancialObservation, ObservationQualityStatus

    o = FinancialObservation(**{**fin_kwargs, "quality_status": "OBSERVED"})
    assert o.quality_status is QualityStatus.OBSERVED
    assert o.quality_status.value == "observed"  # stored lowercase
    assert ObservationQualityStatus.OBSERVED.value == "OBSERVED"
    for raw, expected in [
        ("DERIVED", QualityStatus.DERIVED),
        ("MISSING", QualityStatus.MISSING),
        ("NOT_APPLICABLE", QualityStatus.NOT_APPLICABLE),
        ("LOW_CONFIDENCE", QualityStatus.LOW_CONFIDENCE),
        ("Low_Confidence", QualityStatus.LOW_CONFIDENCE),
    ]:
        assert FinancialObservation(**{**fin_kwargs, "value": None if expected in (
            QualityStatus.MISSING, QualityStatus.NOT_APPLICABLE) else fin_kwargs["value"],
            "quality_status": raw}).quality_status is expected


def test_financial_optional_provenance_fields(fin_kwargs):
    from vms.schemas import FinancialObservation

    o = FinancialObservation(**{**fin_kwargs, "source_document_id": "DOC-1",
                                "derivation_rule_id": None})
    assert o.source_document_id == "DOC-1"
    assert o.derivation_rule_id is None


def test_peer_membership_valid():
    p = _peer()
    assert p.field_name is None and p.peer_instrument_id == "PEER0001.SZ"


def test_peer_rejects_self():
    with pytest.raises(ValidationError, match="must differ"):
        _peer(peer_instrument_id=SUBJ)


def test_peer_metric_requires_currency_unit():
    with pytest.raises(ValidationError, match="currency and unit_scale"):
        _peer(field_name="ev_ebitda", value=12.0, quality_status="observed")


def test_peer_known_at_rules():
    as_of = datetime(2023, 6, 30, 15, tzinfo=CST)
    assert peer_known_at(_peer(), as_of)
    assert not peer_known_at(_peer(published_at=datetime(2023, 7, 1, 9, tzinfo=CST)), as_of)
    assert not peer_known_at(_peer(membership_start=date(2024, 1, 1)), as_of)
    assert not peer_known_at(_peer(membership_end=date(2023, 1, 1)), as_of)
    assert not peer_known_at(
        _peer(field_name="ev_ebitda", value=10.0, currency="CNY", unit_scale="unit",
              metric_timestamp=datetime(2023, 7, 1, 15, tzinfo=CST)), as_of)
    assert peer_known_at(
        _peer(field_name="ev_ebitda", value=10.0, currency="CNY", unit_scale="unit",
              metric_timestamp=datetime(2023, 6, 30, 15, tzinfo=CST)), as_of)


def test_snapshot_excludes_future_peers(qcfg):
    peers = [
        _peer(peer_instrument_id="PEER_OLD.SZ", published_at=datetime(2021, 1, 1, 9, tzinfo=CST)),
        _peer(peer_instrument_id="PEER_FUTURE.SZ", published_at=datetime(2025, 1, 1, 9, tzinfo=CST)),
        _peer(peer_instrument_id="PEER_JOIN_LATER.SZ", published_at=datetime(2021, 1, 1, 9, tzinfo=CST),
              membership_start=date(2024, 1, 1)),
        _peer(peer_instrument_id="PEER_METRIC_FUTURE.SZ", published_at=datetime(2021, 1, 1, 9, tzinfo=CST),
              field_name="ev_ebitda", value=8.0, currency="CNY", unit_scale="unit",
              metric_timestamp=datetime(2024, 1, 2, 15, tzinfo=CST)),
    ]
    load = make_load([fobs("2023-03-31", "revenue", 100, "2023-04-28")],
                     [mobs("2023-06-30", 10.0)], peers=peers)
    snap, rep = assess(load, instrument_id=SUBJ, as_of=parse_as_of("2023-06-30")[0], cfg=qcfg)
    ids = {p.peer_instrument_id for p in snap.peers}
    assert ids == {"PEER_OLD.SZ"}
    assert rep.excluded_post_as_of.get("peers", 0) == 3


def test_io_roundtrip_peers(tmp_path):
    from vms.data.io import load_directory, write_directory
    from vms.data import synthetic

    fin, mkt, ca = synthetic.generate(1)
    peers = [
        _peer(peer_instrument_id="P1.SZ"),
        _peer(peer_instrument_id="P2.SZ", field_name="ev_ebitda", value=9.5,
              currency="CNY", unit_scale="unit",
              metric_timestamp=datetime(2022, 12, 30, 15, tzinfo=CST)),
    ]
    write_directory(tmp_path, fin, mkt, corporate_actions=ca, sources=synthetic.source_descriptors(),
                    classifications=synthetic.classifications(), peers=peers)
    assert (tmp_path / "peer_observations.csv").is_file()
    load = load_directory(tmp_path)
    assert load.ok
    assert len(load.peers) == 2
    assert {p.peer_instrument_id for p in load.peers} == {"P1.SZ", "P2.SZ"}
