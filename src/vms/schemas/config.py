"""Configuration schema and loader (Phase 0).

Many fields are *validated now* but only *consumed* in later phases; each such
field documents the phase that will use it. Nothing in Phase 0 pretends to use
them for valuation.
"""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from vms.schemas.errors import format_validation_error


class ConfigError(ValueError):
    """Raised for any invalid configuration; message is human-actionable."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- driver profile
class DriverFamily(str, Enum):
    DEMAND = "demand"
    PROFITABILITY = "profitability"
    WORKING_CAPITAL = "working_capital"
    REINVESTMENT = "reinvestment"
    CAPITAL_STRUCTURE = "capital_structure"


class DriverTransform(str, Enum):
    IDENTITY = "identity"
    LOG1P = "log1p"
    LOGIT = "logit"


class DriverSpec(_Strict):
    name: str = Field(min_length=1)
    family: DriverFamily
    transform: DriverTransform
    lower: float
    upper: float
    role: Literal["projection", "diagnostic"] = "projection"
    prior: float | None = Field(default=None, description="fallback central value (placeholder) when no history")
    prior_scale: float | None = Field(default=None, gt=0,
                                      description="(Phase 3) prior dispersion in TRANSFORMED space (placeholder)")
    description: str = ""

    @model_validator(mode="after")
    def _bounds(self) -> "DriverSpec":
        if not (math.isfinite(self.lower) and math.isfinite(self.upper)):
            raise ValueError(f"driver '{self.name}': bounds must be finite")
        if self.lower >= self.upper:
            raise ValueError(f"driver '{self.name}': lower={self.lower} must be < upper={self.upper}")
        if self.transform is DriverTransform.LOG1P and self.lower <= -1.0:
            raise ValueError(f"driver '{self.name}': transform 'log1p' requires lower > -1, got {self.lower}")
        if self.prior is not None and not (self.lower <= self.prior <= self.upper):
            raise ValueError(f"driver '{self.name}': prior={self.prior} outside bounds [{self.lower}, {self.upper}]")
        return self


class DriverProfile(_Strict):
    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    supported: bool
    bounds_status: Literal["placeholder", "calibrated"] = Field(
        description="'placeholder' until Phase 2/3 estimation justifies the bounds"
    )
    drivers: list[DriverSpec] = Field(min_length=1)

    @field_validator("drivers")
    @classmethod
    def _unique(cls, v: list[DriverSpec]) -> list[DriverSpec]:
        names = [d.name for d in v]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate driver names: {dupes}")
        return v


# ---------------------------------------------------------------- main config
class MonteCarloConfig(_Strict):
    default_paths: int = Field(gt=0, le=10_000_000)
    default_seed: int = Field(ge=0, lt=2**63)
    max_invalid_path_fraction: float = Field(gt=0, lt=1, description="consumed in Phase 4/5")


class EntryPriceGridConfig(_Strict):
    relative_to_spot: list[float] = Field(min_length=1, description="consumed in Phase 7")

    @field_validator("relative_to_spot")
    @classmethod
    def _positive(cls, v: list[float]) -> list[float]:
        bad = [x for x in v if not (math.isfinite(x) and x > 0)]
        if bad:
            raise ValueError(f"entry price multipliers must be finite and > 0; bad values {bad}")
        if len(set(v)) != len(v):
            raise ValueError(f"entry price multipliers contain duplicates: {v}")
        return sorted(v)


class TerminalValueConfig(_Strict):
    """Consumed in Phase 6. Values are explicit assumptions, not calibrated facts."""

    min_wacc_minus_g: float = Field(gt=0, lt=0.2)
    max_terminal_growth: float = Field(gt=-0.05, lt=0.1)
    tv_fraction_warning: float = Field(gt=0, le=1)


class ReturnsConfig(_Strict):
    """Consumed in Phase 7."""

    loss_thresholds: list[float] = Field(min_length=1)
    hurdles: list[float] = Field(min_length=1)
    cvar_levels: list[float] = Field(min_length=1)

    @field_validator("loss_thresholds")
    @classmethod
    def _losses(cls, v: list[float]) -> list[float]:
        bad = [x for x in v if not (-1.0 <= x < 0.0)]
        if bad:
            raise ValueError(f"loss_thresholds are returns in [-1, 0), e.g. -0.2 for a 20% loss; bad {bad}")
        return sorted(v)

    @field_validator("cvar_levels")
    @classmethod
    def _cvar(cls, v: list[float]) -> list[float]:
        bad = [x for x in v if not (0.5 <= x < 1.0)]
        if bad:
            raise ValueError(f"cvar_levels are confidence levels in [0.5, 1), e.g. 0.95; bad {bad}")
        return sorted(v)

    @field_validator("hurdles")
    @classmethod
    def _hurdles(cls, v: list[float]) -> list[float]:
        bad = [x for x in v if not (math.isfinite(x) and x > -1.0)]
        if bad:
            raise ValueError(f"hurdles must be finite returns > -1; bad {bad}")
        return sorted(v)


class QualityConfig(_Strict):
    """Phase 1 integrity-gate thresholds (explicit, versioned assumptions)."""

    balance_sheet_rel_tol: float = Field(gt=0, lt=0.5, description="|A-L-E|/A above this => warning")
    share_change_rel_tol: float = Field(gt=0, lt=0.5, description="unexplained share change above this => warning")
    adj_factor_rel_tol: float = Field(gt=0, lt=0.5, description="vendor adj-factor jump above this w/o known action")
    unit_jump_ratio: float = Field(gt=1, description="value ratio between versions/periods suggesting unit error")
    max_capex_to_revenue: float = Field(gt=0, description="capex/revenue above this => cash-flow unit warning")
    late_publication_days: int = Field(gt=0, description="published more than this many days after period_end => INFO")
    require_industry_classification: bool = Field(
        default=True, description="INDUSTRY-UNCLASSIFIED-v2: missing PIT classification => CRITICAL (BLOCKED)")


class IndustryConfig(_Strict):
    """Profile resolution by industry (INDUSTRY-SW-L1-v1). No sector logic lives in code."""

    scheme: str = Field(min_length=1)
    unsupported: list[str] = Field(description="industries => UNSUPPORTED_PROFILE (no generic FCFF/DCF)")
    caution: list[str] = Field(default_factory=list, description="supported but flagged PROFILE_CAUTION")
    profile_map: dict[str, str] = Field(default_factory=dict,
                                        description="industry -> registered dedicated profile_id (none yet)")
    default_profile: str = "operating_company"

    @model_validator(mode="after")
    def _disjoint(self) -> "IndustryConfig":
        overlap = set(self.unsupported) & (set(self.caution) | set(self.profile_map))
        if overlap:
            raise ValueError(f"industries listed both as unsupported and caution/mapped: {sorted(overlap)}")
        return self


class ProjectionConfig(_Strict):
    default_years: int = Field(ge=1, le=30)
    driver_history_years: int = Field(ge=1, le=20, description="max annual observations for central values")
    min_history_years: int = Field(ge=1, le=20, description="fewer => LOW_CONFIDENCE flag")
    statutory_tax_rate: float = Field(ge=0, lt=1, description="TAX-CN-STATUTORY-25-v1 fallback")
    tax_loss_carryforward_years: int = Field(ge=0, le=20, description="TAX-CN-LCF-5Y-v1")
    min_cash_to_revenue: float = Field(ge=0, lt=5, description="REVOLVER-MIN-CASH-v1 floor")
    invariant_abs_tol: float = Field(gt=0, description="CNY tolerance for accounting identities")
    revolver_spread: float = Field(default=0.0, ge=0, lt=0.5, description="REVOLVER-RATE-v1: revolver = cost_of_debt + spread")
    cash_interest_rate: float = Field(default=0.0, ge=0, lt=0.5, description="CASH-INTEREST-ZERO-v1 (conservative)")
    bs_residual_warn_ratio: float = Field(default=0.05, gt=0, lt=1,
                                          description="BS-RESIDUAL-WARN-v1: |base residual| / total_assets above => WARNING")


class ConservativeBaseline(_Strict):
    version: Literal["1"] = "1"


class HistoricalContinuation(_Strict):
    version: Literal["1"] = "1"


class FixedPayout(_Strict):
    version: Literal["1"] = "1"
    payout_ratio: float = Field(ge=0, le=2)


class TargetLeverage(_Strict):
    version: Literal["1"] = "1"
    debt_to_ebitda_min: float = Field(ge=0)
    debt_to_ebitda_max: float = Field(gt=0)

    @model_validator(mode="after")
    def _range(self) -> "TargetLeverage":
        if self.debt_to_ebitda_min > self.debt_to_ebitda_max:
            raise ValueError(f"debt_to_ebitda_min={self.debt_to_ebitda_min} > debt_to_ebitda_max={self.debt_to_ebitda_max}")
        return self


class MinCashExcessDistribution(_Strict):
    version: Literal["1"] = "1"
    min_cash_to_revenue: float = Field(ge=0, lt=5)
    dividend_share: float = Field(ge=0, le=1, description="share of excess paid as dividends; rest bought back")


class PolicyParams(_Strict):
    conservative_baseline: ConservativeBaseline
    historical_continuation: HistoricalContinuation
    fixed_payout: FixedPayout
    target_leverage: TargetLeverage
    min_cash_excess_distribution: MinCashExcessDistribution


class CapitalAllocationConfig(_Strict):
    default_policy: Literal["conservative_baseline", "historical_continuation", "fixed_payout", "target_leverage",
                            "min_cash_excess_distribution"]
    policies: PolicyParams


FUNDAMENTAL_STATES = ("GROWTH", "STABLE", "DETERIORATING", "RECOVERY")


class RegimeRules(_Strict):
    """Soft-rule thresholds (REGIME-RULES-v1). Explicit placeholders, not calibrated."""

    growth_high: float = Field(description="TTM revenue growth above this => GROWTH membership > 0.5")
    growth_low: float = Field(description="TTM revenue growth below this => contraction membership > 0.5")
    tau_growth: float = Field(gt=0, description="logistic softness for growth memberships")
    margin_band: float = Field(ge=0, description="EBIT-margin decline (pp, yoy) beyond this => compression")
    tau_margin: float = Field(gt=0)
    recovery_carry: float = Field(ge=0, le=1, description="share of prior RECOVERY mass that keeps 'weak' status")

    @model_validator(mode="after")
    def _order(self) -> "RegimeRules":
        if self.growth_low >= self.growth_high:
            raise ValueError(f"growth_low={self.growth_low} must be < growth_high={self.growth_high}")
        return self


class TransitionPrior(_Strict):
    stay: float = Field(gt=0, description="Dirichlet pseudo-count on the diagonal")
    move: float = Field(gt=0, description="Dirichlet pseudo-count off the diagonal")


class RegimeConfig(_Strict):
    model: Literal["rule_based", "hmm"] = Field(description="'hmm' is an interface only (NOT IMPLEMENTED)")
    model_version: str = Field(min_length=1)
    states: list[str] = Field(min_length=2)
    rules: RegimeRules
    transition_prior: TransitionPrior
    min_state_support: float = Field(gt=0, description="effective transitions per state row below => LOW_SUPPORT")
    market_regime_source: Literal["none"] = Field(
        description="no market-regime model in VMS-0.1 => market dimension UNAVAILABLE (never inferred from fundamentals)")

    @field_validator("states")
    @classmethod
    def _states(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in FUNDAMENTAL_STATES]
        if bad or len(set(v)) != len(v):
            raise ValueError(f"states must be distinct members of {list(FUNDAMENTAL_STATES)}; bad {bad or v}")
        if "STABLE" not in v:
            raise ValueError("states must include STABLE (dropped states are merged into STABLE)")
        return [s for s in FUNDAMENTAL_STATES if s in v]


class WalkForwardConfig(_Strict):
    min_train_years: int = Field(ge=1, description="annual observations needed before the first origin")
    min_origins: int = Field(ge=1, description="fewer scored origins => default spec, never in-sample selection")
    quantiles: list[float] = Field(min_length=1)
    default_spec: Literal["pooled_t", "pooled_empirical", "regime_t", "prior_only"]

    @field_validator("quantiles")
    @classmethod
    def _q(cls, v: list[float]) -> list[float]:
        if any(not (0 < q < 1) for q in v) or len(set(v)) != len(v):
            raise ValueError(f"quantiles must be distinct and in (0, 1); got {v}")
        return sorted(v)


class EstimationConfig(_Strict):
    """Phase 3 driver-distribution estimation (DRIVER-DIST-v1). Explicit placeholders."""

    version: Literal["1"] = "1"
    max_history_years: int = Field(ge=1, le=30)
    min_history_years: int = Field(ge=1, description="fewer observations => SPARSE_HISTORY + LOW_CONFIDENCE")
    prior_strength: float = Field(gt=0, description="pseudo-observations of the profile prior (shrinkage)")
    regime_prior_strength: float = Field(gt=0, description="pseudo-observations pulling regime params to pooled")
    min_regime_support: float = Field(gt=0, description="effective obs per state below => pooled fallback")
    min_empirical_n: int = Field(ge=2, description="observations needed for the empirical residual spec")
    student_t_df: float = Field(gt=2, description="robust parametric family in transformed space")
    boundary_eps: float = Field(gt=0, lt=0.1, description="logit clamp for observations at a bound")
    bootstrap_draws: int = Field(ge=10, le=100_000)
    persisted_param_draws: int = Field(ge=0, le=10_000)
    walk_forward: WalkForwardConfig


class VMSConfig(_Strict):
    configuration_version: str = Field(min_length=1)
    mode: Literal["production", "exploratory"]
    base_currency: Literal["CNY"]
    timezone: str
    driver_profile: str = Field(description="path relative to the config file")
    horizons_years: list[int] = Field(min_length=1)
    monte_carlo: MonteCarloConfig
    entry_price_grid: EntryPriceGridConfig
    terminal_value: TerminalValueConfig
    returns: ReturnsConfig
    quality: QualityConfig
    industry: IndustryConfig
    projection: ProjectionConfig
    capital_allocation: CapitalAllocationConfig
    regimes: RegimeConfig
    estimation: EstimationConfig

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"timezone={v!r} is not a valid IANA zone, e.g. 'Asia/Shanghai'") from None
        return v

    @field_validator("horizons_years")
    @classmethod
    def _horizons(cls, v: list[int]) -> list[int]:
        bad = [h for h in v if h <= 0]
        if bad:
            raise ValueError(f"horizons_years must be positive integers; got {bad}")
        if len(set(v)) != len(v):
            raise ValueError(f"horizons_years contains duplicates: {v}")
        return sorted(v)


class LoadedConfig(_Strict):
    """Validated config plus its resolved driver profile."""

    config: VMSConfig
    profile: DriverProfile
    config_path: str
    profile_path: str


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping, got {type(data).__name__}")
    return data


def load_driver_profile(path: str | Path) -> DriverProfile:
    path = Path(path)
    data = _read_yaml(path)
    try:
        return DriverProfile.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"invalid driver profile\n{format_validation_error(e, str(path))}") from None


def load_config(path: str | Path) -> LoadedConfig:
    path = Path(path).resolve()
    data = _read_yaml(path)
    try:
        cfg = VMSConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"invalid config\n{format_validation_error(e, str(path))}") from None
    profile_path = (path.parent / cfg.driver_profile).resolve()
    profile = load_driver_profile(profile_path)
    return LoadedConfig(config=cfg, profile=profile, config_path=str(path), profile_path=str(profile_path))
