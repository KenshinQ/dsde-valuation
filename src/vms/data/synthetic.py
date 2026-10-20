"""SYNTHETIC operating-company data source (offline, seeded).

Every record carries source_id='SYNTHETIC'. The numbers are toy values chosen
for plausibility of magnitude only; they describe no real company and carry no
investment meaning.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from vms.schemas import FinancialObservation, MarketObservation, QualityStatus, UnitScale
from vms.seeding import stream_rng

SYNTHETIC_SOURCE = "SYNTHETIC"
SYNTHETIC_INSTRUMENT = "SYN000001.SZ"
TZ = ZoneInfo("Asia/Shanghai")

_QUARTER_ENDS = [(3, 31), (6, 30), (9, 30), (12, 31)]
# A-share statutory deadlines: Q1/Q3 within 1 month, H1 within 2 months, annual within 4 months.
_PUBLICATION_LAG_DAYS = {3: 28, 6: 55, 9: 28, 12: 110}


def _quarter_ends(start_year: int, n_quarters: int) -> list[date]:
    out = []
    y, q = start_year, 0
    while len(out) < n_quarters:
        m, d = _QUARTER_ENDS[q]
        out.append(date(y, m, d))
        q = (q + 1) % 4
        y += q == 0
    return out


def generate(seed: int, *, start_year: int = 2021, n_quarters: int = 16,
             instrument_id: str = SYNTHETIC_INSTRUMENT) -> tuple[list[FinancialObservation], list[MarketObservation]]:
    """Standalone-quarter flows (convention: NOT cumulative) and quarter-end stocks, in 万元 CNY."""
    rng = stream_rng(seed, "synthetic_data")
    fin: list[FinancialObservation] = []
    revenue = 50_000.0  # 万元 per quarter
    shares = 1.0e9
    price = 20.0
    mkt: list[MarketObservation] = []
    for pe in _quarter_ends(start_year, n_quarters):
        revenue *= 1.0 + rng.normal(0.02, 0.04)
        gm = float(np.clip(rng.normal(0.32, 0.02), 0.05, 0.8))
        ebit_m = float(np.clip(gm - rng.normal(0.18, 0.015), -0.2, 0.6))
        published = datetime.combine(pe + timedelta(days=_PUBLICATION_LAG_DAYS[pe.month]), time(18, 0), TZ)
        fields = {
            ("income", "revenue"): revenue,
            ("income", "gross_profit"): revenue * gm,
            ("income", "ebit"): revenue * ebit_m,
            ("cash_flow", "capex"): -revenue * float(rng.uniform(0.04, 0.07)),
            ("balance_sheet", "cash"): revenue * float(rng.uniform(0.8, 1.2)),
            ("balance_sheet", "interest_bearing_debt"): revenue * float(rng.uniform(0.3, 0.5)),
        }
        for (stype, name), val in fields.items():
            fin.append(FinancialObservation(
                instrument_id=instrument_id, period_end=pe, published_at=published,
                ingested_at=published + timedelta(days=1), statement_type=stype, field_name=name,
                value=round(float(val), 4), currency="CNY", unit_scale=UnitScale.TEN_THOUSAND,
                source_id=SYNTHETIC_SOURCE, revision_id="r0", quality_status=QualityStatus.OBSERVED))
        # Explicitly missing field, to exercise missing-value handling (never invented).
        fin.append(FinancialObservation(
            instrument_id=instrument_id, period_end=pe, published_at=published, ingested_at=None,
            statement_type="balance_sheet", field_name="minority_interest", value=None, currency="CNY",
            unit_scale=UnitScale.TEN_THOUSAND, source_id=SYNTHETIC_SOURCE, revision_id=None,
            quality_status=QualityStatus.MISSING))
        # One market observation per quarter-end trading close (15:00 CST).
        price *= float(np.exp(rng.normal(0.01, 0.12)))
        mkt.append(MarketObservation(
            instrument_id=instrument_id, timestamp=datetime.combine(pe, time(15, 0), TZ),
            raw_close=round(price, 2), adjusted_close=round(price, 2), shares_outstanding=shares,
            corporate_action_version="ca0", currency="CNY", source_id=SYNTHETIC_SOURCE))
    return fin, mkt
