"""Versioned public DSDE-facing contracts (SPEC §18 / Phase 10).

These schemas are the *only* supported payload shapes for external decision-layer
consumers. They must remain importable without DSDE installed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vms import SCHEMA_VERSION, __version__

DSDE_CONTRACT_VERSION = "vms-dsde-contract-0.2.phase10"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReturnDistributionExport(_M):
    """Public return-distribution export for DSDE (Track B)."""

    schema_kind: Literal["ReturnDistributionExport"] = "ReturnDistributionExport"
    contract_version: str = DSDE_CONTRACT_VERSION
    schema_version: str = SCHEMA_VERSION
    package_version: str = __version__
    spot_price: float
    entry_prices: list[float]
    horizons_years: list[int]
    mixture: list[dict[str, Any]]
    compounding_convention: str
    price_series_convention: str
    exit_ref: dict[str, Any]
    quality_flags: list[str] = Field(default_factory=list)
    investment_value: str = "INVESTMENT_VALUE_NOT_ESTABLISHED"
    content_fingerprint: str | None = None
    notes: list[str] = Field(default_factory=list)


class DSDEConsumerView(_M):
    """Stable, versioned payload for a decision optimizer (DSDE or otherwise)."""

    schema_kind: Literal["DSDEConsumerView"] = "DSDEConsumerView"
    contract_version: str = DSDE_CONTRACT_VERSION
    schema_version: str = SCHEMA_VERSION
    package_version: str = __version__
    run_id: str
    instrument_id: str
    as_of: str
    spot_price: float | None
    entry_prices: list[float]
    horizons_years: list[int]
    return_mixture: list[dict[str, Any]]
    return_export: dict[str, Any] | None = None
    valuation_summary: dict[str, Any]
    uncertainty_diagnostics: dict[str, Any]
    regime_posterior: dict[str, Any] | None
    market_pricing_ref: dict[str, Any] | None = None
    labels: dict[str, Any]
    investment_value: str
    notes: list[str] = Field(default_factory=list)
