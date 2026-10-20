"""NOTICE_DATE PIT policy leakage tests (HITHINK-PIT-NOTICE-v1)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from vms.providers.hithink.mapping import notice_to_published_at
from vms.providers.hithink.pit import (FALLBACK_SOURCE, NOTICE_SOURCE, build_notice_index,
                                       resolve_published_at)

TZ = ZoneInfo("Asia/Shanghai")


def test_join_notice_by_period_end():
    notices = [
        {"security_code": "600519", "report_date": date(2025, 12, 31), "notice_date": date(2026, 4, 17)},
        {"security_code": "600519", "report_date": date(2026, 3, 31), "notice_date": date(2026, 4, 25)},
    ]
    idx = build_notice_index(notices)
    r = resolve_published_at(
        period_end_ms=int(datetime(2025, 12, 31, tzinfo=TZ).timestamp() * 1000),
        report_date_ms=int(datetime(2026, 4, 17, tzinfo=TZ).timestamp() * 1000),
        notice_by_period_end=idx,
    )
    assert r is not None
    assert r.source == NOTICE_SOURCE
    assert r.published_at == notice_to_published_at(date(2026, 4, 17))
    assert r.published_at.date() != r.period_end  # announce lag


def test_future_notice_still_stored_but_asof_excludes_via_pit_filter():
    """Adapter resolves published_at from NOTICE; PIT snapshot excludes published_at > as_of.

    Here we only assert resolve uses NOTICE date (not period_end). Snapshot exclusion is core PIT.
    """
    future = date(2099, 1, 15)
    idx = {date(2025, 12, 31): future}
    r = resolve_published_at(
        period_end_ms=int(datetime(2025, 12, 31, tzinfo=TZ).timestamp() * 1000),
        report_date_ms=1,
        notice_by_period_end=idx,
    )
    assert r.published_at.date() == future
    assert r.published_at != datetime(2025, 12, 31, 15, 0, tzinfo=TZ)


def test_period_end_never_used_as_published_at_when_notice_present():
    pe = date(2025, 12, 31)
    notice = date(2026, 4, 17)
    pe_ms = int(datetime(pe.year, pe.month, pe.day, tzinfo=TZ).timestamp() * 1000)
    idx = {pe: notice}
    r = resolve_published_at(period_end_ms=pe_ms, report_date_ms=pe_ms, notice_by_period_end=idx)
    assert r.source == NOTICE_SOURCE
    assert r.published_at.date() == notice
    assert r.published_at.date() != pe


def test_report_date_fallback_marked():
    pe = date(2025, 12, 31)
    rd = date(2026, 5, 1)
    pe_ms = int(datetime(pe.year, pe.month, pe.day, tzinfo=TZ).timestamp() * 1000)
    rd_ms = int(datetime(rd.year, rd.month, rd.day, tzinfo=TZ).timestamp() * 1000)
    r = resolve_published_at(
        period_end_ms=pe_ms, report_date_ms=rd_ms, notice_by_period_end={},
        allow_report_date_fallback=True,
    )
    assert r is not None
    assert r.source == FALLBACK_SOURCE
    assert r.published_at == notice_to_published_at(rd)
    assert FALLBACK_SOURCE == "hithink_report_date_ms_fallback"


def test_no_fallback_when_disabled_and_notice_missing():
    pe_ms = int(datetime(2025, 12, 31, tzinfo=TZ).timestamp() * 1000)
    r = resolve_published_at(
        period_end_ms=pe_ms, report_date_ms=pe_ms, notice_by_period_end={},
        allow_report_date_fallback=False,
    )
    assert r is None


def test_snapshot_excludes_post_asof_notice(monkeypatch):
    """Integration-style: FinancialObservation with future NOTICE excluded by assess."""
    from tests.factories import INST, fobs, mobs, src
    from tests.conftest import make_load
    from vms.quality.report import assess
    from vms.schemas.config import load_config
    from vms.schemas.observations import (FinancialObservation, QualityStatus, ReportingConvention,
                                          SourceDescriptor, Versioning)
    from pathlib import Path

    REPO = Path(__file__).resolve().parents[3]
    cfg = load_config(REPO / "config/default.yaml")
    # Use HiThink-like source LATEST_ONLY
    sd = SourceDescriptor(
        source_id="hithink_em_notice",
        reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
        versioning=Versioning.LATEST_ONLY,
    )
    from datetime import time as dtime
    from datetime import timedelta, timezone
    CST = timezone(timedelta(hours=8))
    pe = date(2023, 12, 31)
    early = datetime(2024, 3, 30, 15, 0, tzinfo=CST)
    late = datetime(2024, 8, 15, 15, 0, tzinfo=CST)  # after as_of
    as_of = datetime(2024, 5, 6, 15, 0, tzinfo=CST)
    fin = [
        FinancialObservation(
            instrument_id=INST, period_end=pe, published_at=early,
            statement_type="income", field_name="revenue", value=100.0,
            currency="CNY", unit_scale="unit", source_id="hithink_em_notice",
            quality_status=QualityStatus.OBSERVED,
        ),
        FinancialObservation(
            instrument_id=INST, period_end=pe, published_at=late,
            statement_type="income", field_name="revenue", value=999.0,
            currency="CNY", unit_scale="unit", source_id="hithink_em_notice",
            revision_id="r_late", quality_status=QualityStatus.OBSERVED,
        ),
    ]
    mkt = [mobs("2024-05-06", 10.0, shares=1e3)]
    load = make_load(fin, mkt, [], sources=[sd])
    snap, report = assess(load, instrument_id=INST, as_of=as_of, cfg=cfg.config.quality,
                          mode="exploratory", override_reason="hithink_pit_leakage_test")
    rev_vals = [f.value_cny for f in snap.financials if f.field_name == "revenue" and f.value_cny is not None]
    assert 100.0 in rev_vals
    assert 999.0 not in rev_vals  # late NOTICE excluded
    assert report.excluded_post_as_of.get("financial", 0) >= 1
    assert report.pit_complete is False  # LATEST_ONLY
