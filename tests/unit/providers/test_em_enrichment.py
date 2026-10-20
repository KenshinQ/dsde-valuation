"""Unit tests for Eastmoney CA / shares / industry mappers + leakage."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from vms.providers.eastmoney.equity import apply_shares_to_market, equity_share_timeline, shares_known_at
from vms.providers.eastmoney.industry import map_to_sw_l1, parse_company_survey, to_classification
from vms.providers.eastmoney.sharebonus import map_sharebonus_row, map_sharebonus_rows
from vms.schemas.observations import MarketObservation

TZ = ZoneInfo("Asia/Shanghai")


def test_sharebonus_cash_per_share_div10():
    row = {
        "SECURITY_CODE": "600519",
        "REPORT_DATE": "2025-12-31 00:00:00",
        "PLAN_NOTICE_DATE": "2026-04-17 00:00:00",
        "NOTICE_DATE": "2026-06-22 00:00:00",
        "EX_DIVIDEND_DATE": "2026-06-26 00:00:00",
        "PRETAX_BONUS_RMB": 280.2423,
        "BONUS_IT_RATIO": None,
        "BONUS_RATIO": 0,
        "IT_RATIO": None,
    }
    evs = map_sharebonus_row(row, instrument_id="600519.SH")
    assert len(evs) == 1
    e = evs[0]
    assert e.action_type == "cash_dividend"
    assert abs(e.cash_per_share - 28.02423) < 1e-9
    assert e.announced_at == datetime(2026, 4, 17, 15, 0, tzinfo=TZ)
    assert e.ex_date == date(2026, 6, 26)
    assert e.source_id == "em_sharebonus"


def test_sharebonus_bonus_share_ratio():
    # 10转6 → share_ratio 1.6
    row = {
        "SECURITY_CODE": "000002",
        "REPORT_DATE": "2007-12-31",
        "PLAN_NOTICE_DATE": "2008-03-21",
        "NOTICE_DATE": "2008-06-05",
        "EX_DIVIDEND_DATE": "2008-06-16",
        "PRETAX_BONUS_RMB": 1.0,
        "BONUS_IT_RATIO": 6.0,
        "BONUS_RATIO": 0,
        "IT_RATIO": 6,
    }
    evs = map_sharebonus_row(row, instrument_id="000002.SZ")
    types = {e.action_type: e for e in evs}
    assert "cash_dividend" in types
    assert abs(types["cash_dividend"].cash_per_share - 0.1) < 1e-12
    assert "bonus_share" in types
    assert abs(types["bonus_share"].share_ratio - 1.6) < 1e-12


def test_sharebonus_skips_without_announce_or_ex():
    row = {
        "SECURITY_CODE": "600519",
        "REPORT_DATE": "2026-06-30",
        "PLAN_NOTICE_DATE": "2026-04-17",
        "NOTICE_DATE": "2026-04-17",
        "EX_DIVIDEND_DATE": None,  # 预披露
        "PRETAX_BONUS_RMB": None,
    }
    assert map_sharebonus_row(row, instrument_id="600519.SH") == []


def test_sharebonus_never_invents_announce_from_ex_only():
    row = {
        "SECURITY_CODE": "600519",
        "REPORT_DATE": "2024-12-31",
        "PLAN_NOTICE_DATE": None,
        "NOTICE_DATE": None,
        "EX_DIVIDEND_DATE": "2025-06-26",
        "PRETAX_BONUS_RMB": 276.73,
    }
    assert map_sharebonus_row(row, instrument_id="600519.SH") == []


def test_sharebonus_leakage_future_announce_excluded_by_as_of_filter():
    """Mapper stamps announced_at; PIT snapshot must drop future announces (contract)."""
    from vms.pit.snapshot import build_snapshot
    from vms.schemas.observations import ReportingConvention, SourceDescriptor, Versioning

    rows = [
        {
            "SECURITY_CODE": "600519",
            "REPORT_DATE": "2024-12-31",
            "PLAN_NOTICE_DATE": "2025-04-03",
            "NOTICE_DATE": "2025-06-20",
            "EX_DIVIDEND_DATE": "2025-06-26",
            "PRETAX_BONUS_RMB": 276.73,
        },
        {
            "SECURITY_CODE": "600519",
            "REPORT_DATE": "2025-12-31",
            "PLAN_NOTICE_DATE": "2026-04-17",  # future vs as_of 2025-12-31
            "NOTICE_DATE": "2026-06-22",
            "EX_DIVIDEND_DATE": "2026-06-26",
            "PRETAX_BONUS_RMB": 280.2423,
        },
    ]
    events, _ = map_sharebonus_rows(rows, instrument_id="600519.SH")
    assert len(events) == 2
    as_of = datetime(2025, 12, 31, 15, 0, tzinfo=TZ)
    src = SourceDescriptor(
        source_id="em_sharebonus",
        reporting_convention=ReportingConvention.UNKNOWN,
        versioning=Versioning.LATEST_ONLY,
    )
    # minimal market bar so snapshot builds
    mkt = [MarketObservation(
        instrument_id="600519.SH", timestamp=datetime(2025, 12, 30, 15, 0, tzinfo=TZ),
        raw_close=1400.0, currency="CNY", source_id="t",
    )]
    snap, _, _ = build_snapshot(
        instrument_id="600519.SH", as_of=as_of,
        financial=[], market=mkt, corporate_actions=events,
        sources={"em_sharebonus": src, "t": src},
    )
    # only the 2025-04-03 announced dividend known
    assert len(snap.corporate_actions) == 1
    assert snap.corporate_actions[0].event.announced_at.date() == date(2025, 4, 3)
    assert snap.corporate_actions[0].event.cash_per_share == pytest.approx(27.673)


def test_equity_timeline_pit():
    rows = [
        {"NOTICE_DATE": "2024-01-10", "TOTAL_SHARES": 1000.0},
        {"NOTICE_DATE": "2025-05-28", "TOTAL_SHARES": 900.0},
        {"NOTICE_DATE": "2026-05-28", "TOTAL_SHARES": 800.0},
    ]
    tl = equity_share_timeline(rows)
    assert shares_known_at(tl, date(2023, 12, 31)) is None
    assert shares_known_at(tl, date(2024, 1, 10)) == 1000.0
    assert shares_known_at(tl, date(2025, 6, 1)) == 900.0
    assert shares_known_at(tl, date(2026, 5, 27)) == 900.0  # future announce excluded
    assert shares_known_at(tl, date(2026, 5, 28)) == 800.0


def test_apply_shares_leakage():
    tl = equity_share_timeline([
        {"NOTICE_DATE": "2025-06-01", "TOTAL_SHARES": 1_250_081_601.0},
    ])
    bars = [
        MarketObservation(
            instrument_id="600519.SH",
            timestamp=datetime(2025, 5, 30, 15, 0, tzinfo=TZ),
            raw_close=1500.0, currency="CNY", source_id="t",
        ),
        MarketObservation(
            instrument_id="600519.SH",
            timestamp=datetime(2025, 6, 2, 15, 0, tzinfo=TZ),
            raw_close=1510.0, currency="CNY", source_id="t",
        ),
    ]
    out = apply_shares_to_market(bars, tl)
    assert out[0].shares_outstanding is None
    assert out[1].shares_outstanding == 1_250_081_601.0


def test_industry_bank_and_moutai():
    assert map_to_sw_l1("银行", "金融业-货币金融服务")[0] == "银行"
    assert map_to_sw_l1("证券", "金融业-资本市场服务")[0] == "非银金融"
    assert map_to_sw_l1("酿酒行业", "制造业-酒、饮料和精制茶制造业")[0] == "食品饮料"
    body = {
        "jbzl": {"sshy": "酿酒行业", "sszjhhy": "制造业-酒、饮料和精制茶制造业"},
        "fxxg": {"ssrq": "2001-08-27"},
    }
    parsed = parse_company_survey(body)
    assert parsed["sw_l1_proxy"] == "食品饮料"
    cls = to_classification(parsed, instrument_id="600519.SH")
    assert cls is not None
    assert cls.scheme == "SW2021_L1"
    assert cls.industry == "食品饮料"
    assert cls.published_at.date() == date(2001, 8, 27)
