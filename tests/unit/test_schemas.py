"""Schema validation (SPEC §5.3, Phase 0 acceptance: invalid schema/timestamp/unit/currency fail actionably)."""

from __future__ import annotations

import math
from datetime import datetime

import pytest
from pydantic import ValidationError

from vms.schemas import (FinancialObservation, MarketObservation, QualityStatus, UnitScale,
                         ValuationRequest, format_validation_error)


def _err(model, kwargs) -> str:
    with pytest.raises(ValidationError) as ei:
        model(**kwargs)
    return format_validation_error(ei.value)


# ---------------------------------------------------------------- FinancialObservation
def test_financial_valid(fin_kwargs):
    o = FinancialObservation(**fin_kwargs)
    assert o.quality_status is QualityStatus.OBSERVED
    assert o.unit_scale is UnitScale.TEN_THOUSAND
    assert o.value_in_units == pytest.approx(1_234_000.0)


def test_financial_chinese_unit_alias(fin_kwargs):
    assert FinancialObservation(**{**fin_kwargs, "unit_scale": "亿元"}).unit_scale is UnitScale.HUNDRED_MILLION


def test_financial_naive_published_at_rejected(fin_kwargs):
    msg = _err(FinancialObservation, {**fin_kwargs, "published_at": datetime(2024, 4, 28, 18)})
    assert "published_at" in msg and "timezone-naive" in msg and "+08:00" in msg


def test_financial_naive_ingested_at_rejected(fin_kwargs):
    msg = _err(FinancialObservation, {**fin_kwargs, "ingested_at": datetime(2024, 4, 29)})
    assert "ingested_at" in msg and "timezone-naive" in msg


@pytest.mark.parametrize("cur", ["RMB", "EUR", "cny1", ""])
def test_financial_bad_currency(fin_kwargs, cur):
    msg = _err(FinancialObservation, {**fin_kwargs, "currency": cur})
    assert "currency" in msg and "ISO-4217" in msg and "CNY" in msg


def test_financial_currency_normalised_upper(fin_kwargs):
    assert FinancialObservation(**{**fin_kwargs, "currency": " cny "}).currency == "CNY"


@pytest.mark.parametrize("unit", ["millions", "1e4", "", "万"])
def test_financial_bad_unit(fin_kwargs, unit):
    msg = _err(FinancialObservation, {**fin_kwargs, "unit_scale": unit})
    assert "unit_scale" in msg and "ten_thousand" in msg  # lists allowed values


def test_financial_bad_statement_type(fin_kwargs):
    msg = _err(FinancialObservation, {**fin_kwargs, "statement_type": "equity"})
    assert "statement_type" in msg and "balance_sheet" in msg


def test_financial_bad_quality_status(fin_kwargs):
    msg = _err(FinancialObservation, {**fin_kwargs, "quality_status": "ok"})
    assert "quality_status" in msg and "low_confidence" in msg


@pytest.mark.parametrize("v", [math.nan, math.inf, -math.inf])
def test_financial_non_finite_value(fin_kwargs, v):
    assert "not finite" in _err(FinancialObservation, {**fin_kwargs, "value": v})


def test_financial_null_value_requires_missing_status(fin_kwargs):
    msg = _err(FinancialObservation, {**fin_kwargs, "value": None})
    assert "null" in msg and "missing" in msg
    ok = FinancialObservation(**{**fin_kwargs, "value": None, "quality_status": "missing"})
    assert ok.value is None and ok.value_in_units is None


def test_financial_missing_status_with_value_rejected(fin_kwargs):
    assert "set value to null" in _err(FinancialObservation, {**fin_kwargs, "quality_status": "missing"})


def test_financial_published_before_period_end(fin_kwargs):
    from datetime import date
    msg = _err(FinancialObservation, {**fin_kwargs, "period_end": date(2024, 6, 30)})
    assert "precedes period_end" in msg


def test_financial_ingested_before_published(fin_kwargs):
    early = fin_kwargs["published_at"].replace(day=1)
    assert "ingested_at" in _err(FinancialObservation, {**fin_kwargs, "ingested_at": early})


def test_financial_extra_and_missing_fields(fin_kwargs):
    assert "Extra inputs" in _err(FinancialObservation, {**fin_kwargs, "foo": 1})
    kw = dict(fin_kwargs); kw.pop("source_id")
    assert "source_id" in _err(FinancialObservation, kw)


# ---------------------------------------------------------------- MarketObservation
def test_market_valid(mkt_kwargs):
    assert MarketObservation(**mkt_kwargs).raw_close == 10.0


@pytest.mark.parametrize("field,val", [("raw_close", 0), ("raw_close", -1), ("adjusted_close", 0),
                                       ("shares_outstanding", -5), ("raw_close", math.inf)])
def test_market_ranges(mkt_kwargs, field, val):
    assert field in _err(MarketObservation, {**mkt_kwargs, field: val})


def test_market_naive_timestamp(mkt_kwargs):
    assert "timezone-naive" in _err(MarketObservation, {**mkt_kwargs, "timestamp": datetime(2024, 3, 29, 15)})


def test_market_currency_required_and_validated(mkt_kwargs):
    kw = dict(mkt_kwargs); kw.pop("currency")
    assert "currency" in _err(MarketObservation, kw)
    assert "ISO-4217" in _err(MarketObservation, {**mkt_kwargs, "currency": "XYZ"})


# ---------------------------------------------------------------- ValuationRequest
def test_request_valid_sorts_horizons(req_kwargs):
    r = ValuationRequest(**{**req_kwargs, "horizons_years": [5, 1, 3]})
    assert r.horizons_years == [1, 3, 5]


def test_request_naive_as_of(req_kwargs):
    assert "as_of" in _err(ValuationRequest, {**req_kwargs, "as_of": datetime(2025, 6, 30)})


@pytest.mark.parametrize("field,val,needle", [
    ("monte_carlo_paths", 0, "greater than 0"),
    ("monte_carlo_paths", -10, "greater than 0"),
    ("monte_carlo_paths", True, "not a boolean"),
    ("spot_price", 0, "greater than 0"),
    ("spot_price", math.nan, "spot_price"),
    ("random_seed", -1, "greater than or equal to 0"),
    ("horizons_years", [], "at least 1"),
    ("horizons_years", [0, 1], "positive"),
    ("horizons_years", [-1], "positive"),
    ("horizons_years", [1, 1], "duplicates"),
    ("configuration_version", "", "at least 1"),
    ("instrument_id", "  ", "at least 1"),
])
def test_request_ranges(req_kwargs, field, val, needle):
    msg = _err(ValuationRequest, {**req_kwargs, field: val})
    assert field in msg and needle in msg, msg
