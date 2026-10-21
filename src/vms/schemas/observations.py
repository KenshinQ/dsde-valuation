"""Canonical data contracts (SPEC §5.1–§5.3).

All timestamps must be timezone-aware. All monetary amounts carry currency
and unit-scale metadata. Validation errors are meant to be actionable: each
message names the field, the offending value and what is expected.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vms.schemas.contracts import ValuationTarget

# ISO-4217 codes accepted at ingestion. Internal base currency is CNY (§5.2);
# conversion to CNY is a Phase 1 concern and requires explicit FX data.
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"CNY", "HKD", "USD"})
BASE_CURRENCY = "CNY"


class QualityStatus(str, Enum):
    """Per-observation quality status (§5.1)."""

    OBSERVED = "observed"
    DERIVED = "derived"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    LOW_CONFIDENCE = "low_confidence"


class UnitScale(str, Enum):
    """Multiplicative scale of a reported amount."""

    UNIT = "unit"                     # 元
    THOUSAND = "thousand"             # 千元
    TEN_THOUSAND = "ten_thousand"     # 万元
    MILLION = "million"               # 百万元
    HUNDRED_MILLION = "hundred_million"  # 亿元
    BILLION = "billion"

    @property
    def multiplier(self) -> float:
        return _UNIT_MULTIPLIERS[self]


_UNIT_MULTIPLIERS = {
    UnitScale.UNIT: 1.0,
    UnitScale.THOUSAND: 1e3,
    UnitScale.TEN_THOUSAND: 1e4,
    UnitScale.MILLION: 1e6,
    UnitScale.HUNDRED_MILLION: 1e8,
    UnitScale.BILLION: 1e9,
}

# Common Chinese-source aliases mapped to canonical names (explicit, not fuzzy).
_UNIT_ALIASES = {"元": "unit", "千元": "thousand", "万元": "ten_thousand",
                 "百万元": "million", "亿元": "hundred_million", "1": "unit"}

_MISSING_STATUSES = {QualityStatus.MISSING, QualityStatus.NOT_APPLICABLE}


def _require_tz(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            f"{field}={value.isoformat()} is timezone-naive; provide an explicit offset, "
            f"e.g. '{value.isoformat()}+08:00' for Asia/Shanghai"
        )
    return value


def _require_finite(value: float | None, field: str) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{field}={value!r} is not finite; NaN/Inf are not allowed, use null + quality_status")
    return value


def _validate_currency(value: str) -> str:
    code = value.strip().upper() if isinstance(value, str) else value
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError(
            f"currency={value!r} is not supported; expected an ISO-4217 code in {sorted(SUPPORTED_CURRENCIES)}"
        )
    return code


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FinancialObservation(_Base):
    instrument_id: str = Field(min_length=1)
    period_end: date
    published_at: datetime
    ingested_at: datetime | None = None
    statement_type: Literal["income", "cash_flow", "balance_sheet"]
    field_name: str = Field(min_length=1)
    value: float | None
    currency: str
    unit_scale: UnitScale
    source_id: str = Field(min_length=1)
    revision_id: str | None = None
    quality_status: QualityStatus

    @field_validator("published_at", "ingested_at")
    @classmethod
    def _tz(cls, v: datetime | None, info):  # noqa: ANN001
        return None if v is None else _require_tz(v, info.field_name)

    @field_validator("value")
    @classmethod
    def _finite(cls, v):  # noqa: ANN001
        return _require_finite(v, "value")

    @field_validator("currency")
    @classmethod
    def _currency(cls, v):  # noqa: ANN001
        return _validate_currency(v)

    @field_validator("unit_scale", mode="before")
    @classmethod
    def _unit_alias(cls, v):  # noqa: ANN001
        if isinstance(v, str) and v.strip() in _UNIT_ALIASES:
            return _UNIT_ALIASES[v.strip()]
        return v

    @model_validator(mode="after")
    def _cross_field(self) -> "FinancialObservation":
        if self.value is None and self.quality_status not in _MISSING_STATUSES:
            raise ValueError(
                f"{self.field_name}@{self.period_end}: value is null but quality_status="
                f"'{self.quality_status.value}'; null values must be 'missing' or 'not_applicable' "
                "(missing values must never be silently invented)"
            )
        if self.value is not None and self.quality_status in _MISSING_STATUSES:
            raise ValueError(
                f"{self.field_name}@{self.period_end}: quality_status='{self.quality_status.value}' "
                f"but value={self.value}; set value to null or use 'observed'/'derived'/'low_confidence'"
            )
        if self.published_at.date() < self.period_end:
            raise ValueError(
                f"{self.field_name}: published_at={self.published_at.isoformat()} precedes "
                f"period_end={self.period_end}; a period cannot be reported before it ends"
            )
        if self.ingested_at is not None and self.ingested_at < self.published_at:
            raise ValueError(
                f"{self.field_name}: ingested_at={self.ingested_at.isoformat()} precedes "
                f"published_at={self.published_at.isoformat()}"
            )
        return self

    @property
    def value_in_units(self) -> float | None:
        """Value multiplied by its unit scale (still in original currency)."""
        return None if self.value is None else self.value * self.unit_scale.multiplier


class MarketObservation(_Base):
    instrument_id: str = Field(min_length=1)
    timestamp: datetime
    raw_close: float = Field(gt=0)
    adjusted_close: float | None = Field(default=None, gt=0)
    shares_outstanding: float | None = Field(default=None, gt=0)
    corporate_action_version: str | None = None
    # Not in the §5.3 minimal contract; added because §5.2 requires currency on all amounts.
    currency: str = Field(description="ISO-4217 code of raw/adjusted close")
    source_id: str = Field(min_length=1)

    @field_validator("timestamp")
    @classmethod
    def _tz(cls, v):  # noqa: ANN001
        return _require_tz(v, "timestamp")

    @field_validator("raw_close", "adjusted_close", "shares_outstanding")
    @classmethod
    def _finite(cls, v, info):  # noqa: ANN001
        return _require_finite(v, info.field_name)

    @field_validator("currency")
    @classmethod
    def _currency(cls, v):  # noqa: ANN001
        return _validate_currency(v)


class ReportingConvention(str, Enum):
    """How a source reports income/cash-flow FLOWS within a fiscal year."""

    CN_CUMULATIVE_YTD = "CN_CUMULATIVE_YTD"      # Q1, H1, 9M, FY cumulative (A-share statutory style)
    STANDALONE_QUARTER = "STANDALONE_QUARTER"    # each period_end carries its own quarter only
    UNKNOWN = "UNKNOWN"                          # never converted; flagged


class Versioning(str, Enum):
    """Whether a source preserves every published version (needed for unbiased PIT history)."""

    FULL_HISTORY = "FULL_HISTORY"
    LATEST_ONLY = "LATEST_ONLY"
    UNKNOWN = "UNKNOWN"


class SourceDescriptor(_Base):
    """Declared per source in ``sources.yaml``. Nothing about a source is ever guessed."""

    source_id: str = Field(min_length=1)
    reporting_convention: ReportingConvention
    versioning: Versioning
    fiscal_year_end: Literal["12-31"] = "12-31"
    description: str = ""


CorporateActionType = Literal["cash_dividend", "bonus_share", "stock_split", "share_issuance",
                              "share_cancellation"]
#: Price-neutral share-count changes that require price adjustment.
PRICE_ADJUSTING_ACTIONS = frozenset({"bonus_share", "stock_split"})
SHARE_CHANGING_ACTIONS = frozenset({"bonus_share", "stock_split", "share_issuance", "share_cancellation"})


class CorporateActionEvent(_Base):
    """Corporate action, known from ``announced_at`` (the PIT availability time).

    share_ratio: post-action shares per pre-action share (10送3 => 1.3; 1:2 split => 2.0;
    cancellation of 1% => 0.99). cash_per_share: gross cash dividend per pre-action share.
    Revisions of the same action share ``action_id`` with later ``announced_at``.
    """

    action_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    action_type: CorporateActionType
    announced_at: datetime
    ex_date: date
    share_ratio: float | None = Field(default=None, gt=0)
    cash_per_share: float | None = Field(default=None, ge=0)
    currency: str
    source_id: str = Field(min_length=1)
    revision_id: str | None = None

    @field_validator("announced_at")
    @classmethod
    def _tz(cls, v):  # noqa: ANN001
        return _require_tz(v, "announced_at")

    @field_validator("share_ratio", "cash_per_share")
    @classmethod
    def _finite(cls, v, info):  # noqa: ANN001
        return _require_finite(v, info.field_name)

    @field_validator("currency")
    @classmethod
    def _currency(cls, v):  # noqa: ANN001
        return _validate_currency(v)

    @model_validator(mode="after")
    def _consistency(self) -> "CorporateActionEvent":
        if self.action_type == "cash_dividend":
            if self.cash_per_share is None:
                raise ValueError(f"{self.action_id}: cash_dividend requires cash_per_share")
            if self.share_ratio not in (None, 1.0):
                raise ValueError(f"{self.action_id}: cash_dividend must not change shares (share_ratio={self.share_ratio})")
        else:
            if self.share_ratio is None or self.share_ratio == 1.0:
                raise ValueError(f"{self.action_id}: {self.action_type} requires share_ratio != 1 (e.g. 1.3 for 10送3)")
        if self.ex_date < self.announced_at.date():
            raise ValueError(
                f"{self.action_id}: ex_date={self.ex_date} precedes announced_at={self.announced_at.isoformat()}"
            )
        return self


class InstrumentClassification(_Base):
    """Industry classification, known from ``published_at`` (PIT; reclassifications get new rows)."""

    instrument_id: str = Field(min_length=1)
    scheme: str = Field(min_length=1, description="e.g. SW2021_L1")
    industry: str = Field(min_length=1, description="e.g. 机械设备 (SW2021_L1 name)")
    published_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator("published_at")
    @classmethod
    def _tz(cls, v):  # noqa: ANN001
        return _require_tz(v, "published_at")


class ValuationRequest(_Base):
    instrument_id: str = Field(min_length=1)
    as_of: datetime
    spot_price: float = Field(gt=0)
    horizons_years: list[int] = Field(min_length=1)
    monte_carlo_paths: int = Field(gt=0, le=10_000_000)
    random_seed: int = Field(ge=0, lt=2**63)
    configuration_version: str = Field(min_length=1)
    # VMS-0.2 §10.1: every router/value call names exactly one target.
    # Default preserves VMS-0.1 call sites until callers migrate.
    target: ValuationTarget = Field(default=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT)

    @field_validator("as_of")
    @classmethod
    def _tz(cls, v):  # noqa: ANN001
        return _require_tz(v, "as_of")

    @field_validator("spot_price")
    @classmethod
    def _finite(cls, v):  # noqa: ANN001
        return _require_finite(v, "spot_price")

    @field_validator("horizons_years")
    @classmethod
    def _horizons(cls, v: list[int]) -> list[int]:
        bad = [h for h in v if h <= 0]
        if bad:
            raise ValueError(f"horizons_years must be positive integers (years); got non-positive {bad}")
        if len(set(v)) != len(v):
            raise ValueError(f"horizons_years contains duplicates: {v}")
        return sorted(v)

    @field_validator("random_seed", "monte_carlo_paths", mode="before")
    @classmethod
    def _no_bool(cls, v, info):  # noqa: ANN001
        if isinstance(v, bool):
            raise ValueError(f"{info.field_name} must be an integer, not a boolean")
        return v
