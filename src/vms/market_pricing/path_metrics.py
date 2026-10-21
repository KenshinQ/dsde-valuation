"""Extract future financial metrics from a FinancialPathRecord at a horizon (SPEC §14.4 step 1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.market_pricing.terminal_multiples import metric_denominator_field
from vms.statements.paths import FinancialPathRecord


class HorizonMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    path_id: str
    horizon_years: int
    calendar_year: int | None
    metric_id: str
    denominator_field: str
    denominator_value: float | None
    diluted_shares: float | None
    cash: float | None
    debt: float | None
    flags: list[str] = Field(default_factory=list)
    lineage: dict[str, Any] = Field(default_factory=dict)


def _item(rec: FinancialPathRecord, name: str, year: int) -> float | None:
    if rec.projection is None:
        return None
    tv = rec.projection.items.get(f"{name}@{year}")
    return None if tv is None else float(tv.value)


def extract_horizon_metrics(
    rec: FinancialPathRecord,
    *,
    horizon_years: int,
    metric_id: str,
) -> HorizonMetrics:
    """Sample (deterministically read) future financial metrics from the fundamental path."""
    flags: list[str] = []
    if rec.status != "VALID" or rec.projection is None:
        return HorizonMetrics(
            valid=False,
            invalid_reason="PATH_NOT_VALID",
            path_id=rec.path_id,
            horizon_years=horizon_years,
            calendar_year=None,
            metric_id=metric_id,
            denominator_field=metric_denominator_field(metric_id),
            denominator_value=None,
            diluted_shares=None,
            cash=None,
            debt=None,
            flags=["PATH_INVALID"],
        )
    years = list(rec.projection.years)
    if horizon_years < 1 or horizon_years > len(years):
        return HorizonMetrics(
            valid=False,
            invalid_reason="HORIZON_OUT_OF_RANGE",
            path_id=rec.path_id,
            horizon_years=horizon_years,
            calendar_year=None,
            metric_id=metric_id,
            denominator_field=metric_denominator_field(metric_id),
            denominator_value=None,
            diluted_shares=None,
            cash=None,
            debt=None,
        )
    year = years[horizon_years - 1]
    field = metric_denominator_field(metric_id)
    denom = _item(rec, field, year)
    shares = rec.shares.get(str(year))
    if shares is None:
        shares = _item(rec, "diluted_shares", year)
    cash = rec.cash.get(str(year))
    if cash is None:
        cash = _item(rec, "cash", year)
    debt = rec.debt.get(str(year))
    if debt is None:
        debt = _item(rec, "interest_bearing_debt", year)
    if denom is None or not (denom == denom):  # NaN check
        return HorizonMetrics(
            valid=False,
            invalid_reason="MISSING_DENOMINATOR",
            path_id=rec.path_id,
            horizon_years=horizon_years,
            calendar_year=year,
            metric_id=metric_id,
            denominator_field=field,
            denominator_value=None,
            diluted_shares=shares,
            cash=cash,
            debt=debt,
            flags=["MISSING_METRIC"],
        )
    # Soft validity: negative earnings for P/E etc.
    if field in {"parent_net_income", "ebit", "ebitda"} and denom <= 0:
        flags.append("NONPOSITIVE_DENOMINATOR")
        return HorizonMetrics(
            valid=False,
            invalid_reason="NONPOSITIVE_DENOMINATOR",
            path_id=rec.path_id,
            horizon_years=horizon_years,
            calendar_year=year,
            metric_id=metric_id,
            denominator_field=field,
            denominator_value=denom,
            diluted_shares=shares,
            cash=cash,
            debt=debt,
            flags=flags,
        )
    if shares is None or shares <= 0:
        flags.append("MISSING_OR_NONPOSITIVE_SHARES")
        return HorizonMetrics(
            valid=False,
            invalid_reason="NONPOSITIVE_SHARES",
            path_id=rec.path_id,
            horizon_years=horizon_years,
            calendar_year=year,
            metric_id=metric_id,
            denominator_field=field,
            denominator_value=denom,
            diluted_shares=shares,
            cash=cash,
            debt=debt,
            flags=flags,
        )
    return HorizonMetrics(
        valid=True,
        path_id=rec.path_id,
        horizon_years=horizon_years,
        calendar_year=year,
        metric_id=metric_id,
        denominator_field=field,
        denominator_value=denom,
        diluted_shares=float(shares),
        cash=float(cash) if cash is not None else 0.0,
        debt=float(debt) if debt is not None else 0.0,
        flags=flags,
        lineage={
            "path_id": rec.path_id,
            "calendar_year": year,
            "denominator_field": field,
            "denominator_value": denom,
            "diluted_shares": float(shares),
            "cash": float(cash) if cash is not None else 0.0,
            "debt": float(debt) if debt is not None else 0.0,
        },
    )
