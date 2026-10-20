from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CST = timezone(timedelta(hours=8))


@pytest.fixture
def repo() -> Path:
    return REPO


@pytest.fixture
def fin_kwargs() -> dict:
    return dict(instrument_id="SYN000001.SZ", period_end=date(2024, 3, 31),
                published_at=datetime(2024, 4, 28, 18, 0, tzinfo=CST), statement_type="income",
                field_name="revenue", value=123.4, currency="CNY", unit_scale="ten_thousand",
                source_id="SYNTHETIC", revision_id="r0", quality_status="observed")


@pytest.fixture
def mkt_kwargs() -> dict:
    return dict(instrument_id="SYN000001.SZ", timestamp=datetime(2024, 3, 29, 15, tzinfo=CST),
                raw_close=10.0, adjusted_close=9.5, shares_outstanding=1e9,
                corporate_action_version="ca0", currency="CNY", source_id="SYNTHETIC")


@pytest.fixture
def req_kwargs() -> dict:
    return dict(instrument_id="SYN000001.SZ", as_of=datetime(2025, 6, 30, 15, tzinfo=CST),
                spot_price=20.0, horizons_years=[1, 3, 5], monte_carlo_paths=1000,
                random_seed=42, configuration_version="vms-default-0.1.0")
