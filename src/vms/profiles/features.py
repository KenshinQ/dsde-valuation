"""Feature bundle for the economic-profile classifier (SPEC §7.3).

Features are explicit scalars known at ``as_of``. Industry taxonomy alone is
insufficient; financial-statement behaviour must be present for confident
classification. Missing fields are tracked for diagnostics.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileFeatureBundle(BaseModel):
    """Inputs to ``classify_profile``. All ratios are dimensionless (e.g. 0.12 = 12%)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str = Field(min_length=1)
    as_of: str = Field(min_length=1, description="ISO date or datetime known at classification")
    # Growth / cash-flow structure
    revenue_cagr_3y: float | None = None
    fcf_to_revenue: float | None = None
    ebit_margin: float | None = None
    ebit_margin_stdev_3y: float | None = None
    net_income_to_revenue: float | None = None
    # Financial-institution / holding / asset structure
    interest_income_to_revenue: float | None = None
    financial_assets_to_assets: float | None = None
    investment_assets_to_assets: float | None = None
    equity_method_income_to_pretax: float | None = None
    ppe_to_assets: float | None = None
    # Leverage / liquidity / payout
    debt_to_assets: float | None = None
    cash_to_assets: float | None = None
    net_cash_to_assets: float | None = None
    dividend_payout: float | None = None
    book_equity: float | None = None
    # Complexity / history (no future labels)
    n_segments: int | None = None
    has_listed_subsidiaries: bool | None = None
    history_years: float | None = None
    # Auxiliary industry (never sufficient alone)
    industry_scheme: str | None = None
    industry_name: str | None = None
    # Explicit data-quality hint from upstream gates
    low_data_quality: bool = False
    fixture_id: str | None = Field(default=None, description="synthetic fixture id when applicable")

    def missing_fields(self) -> list[str]:
        core = [
            "revenue_cagr_3y", "fcf_to_revenue", "ebit_margin", "ebit_margin_stdev_3y",
            "net_income_to_revenue", "debt_to_assets", "cash_to_assets", "book_equity",
            "history_years",
        ]
        return [n for n in core if getattr(self, n) is None]

    def feature_values(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class FeatureSource(BaseModel):
    """Trace that a feature value came from a named input (fixture or snapshot field)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature: str
    value: Any
    source: str
