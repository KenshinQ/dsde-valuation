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

from vms.market_pricing.config import MarketPricingConfig

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from vms.schemas.contracts import (
    MethodRegistryConfig,
    ProfilesCatalogConfig,
    RouterConfig,
)
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
    max_invalid_path_fraction: float = Field(gt=0, lt=1, description="reject run / flag when invalid fraction exceeds this")
    correlation_prior_strength: float = Field(gt=0, description="shrink residual correlations toward identity")
    min_correlation_years: int = Field(ge=1, description="below => CORRELATION_SPARSE_HEAVY_SHRINK")
    artifact_path_cap: int = Field(ge=0, le=100_000, description="max MC paths embedded in simulation_bundle.json; 0=all")


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
    terminal_growth: float = Field(gt=-0.05, lt=0.1, description="Gordon g; must be <= max_terminal_growth")

    @model_validator(mode="after")
    def _g_bound(self):  # noqa: ANN202
        if self.terminal_growth > self.max_terminal_growth + 1e-15:
            raise ValueError(f"terminal_growth {self.terminal_growth} > max_terminal_growth {self.max_terminal_growth}")
        return self


class ExitMultipleConfig(_Strict):
    metric: Literal["ebitda", "ebit"] = "ebitda"
    multiple: float | None = Field(default=None, gt=0, description="explicit multiple when peers empty")
    peers: list[float] = Field(default_factory=list, description="synthetic/PIT peer multiples")
    shrink_prior: float = Field(gt=0, description="shrink peer median toward this prior")
    shrink_strength: float = Field(ge=0, description="pseudo-observations of the prior")
    normalize_years: int = Field(ge=1, le=5, description="trailing years averaged for the metric")


class ValuationConfig(_Strict):
    """Phase 6 WACC / DCF / multiple / bridge inputs. Missing RF is a hard config error."""

    risk_free_rate: float = Field(ge=-0.05, le=0.3, description="REQUIRED; never invented (WACC-RF-CONFIG-v1)")
    erp: float = Field(gt=0, lt=0.3, description="equity risk premium default 0.06")
    beta: float | None = Field(default=None, gt=-1, lt=5, description="explicit beta; else from series/prior")
    beta_prior: float = Field(default=1.0, gt=-1, lt=5)
    beta_shrink_strength: float = Field(default=2.0, ge=0)
    beta_n_eff: float = Field(default=0.0, ge=0, description="effective obs for shrink when beta series absent")
    cost_of_equity: float | None = Field(default=None, gt=-0.5, lt=1.0, description="optional override of ke")
    cost_of_debt: float | None = Field(default=None, gt=-0.05, lt=1.0, description="override; else driver/snapshot")
    tax_rate: float | None = Field(default=None, ge=0, lt=1, description="override; else driver effective tax")
    target_debt_weight: float | None = Field(default=None, ge=0, le=1)
    target_equity_weight: float | None = Field(default=None, ge=0, le=1)
    use_snapshot_capital_structure: bool = Field(
        default=True, description="if target weights unset, use market equity + interest-bearing debt at as_of")
    lease_debt_like: float = Field(default=0.0, ge=0, description="explicit lease liability add-on (LEASE-BRIDGE)")
    other_senior_claims: float = Field(default=0.0, description="signed: subtract when positive")
    minority_interest_book: float | None = Field(
        default=None, description="override; else total_equity*(1-parent_share) at horizon if available")
    exit_multiple: ExitMultipleConfig
    composite_weights: dict[str, float] | None = Field(
        default=None, description="None => keep DCF and multiple separate; else versioned weights")

    @model_validator(mode="after")
    def _weights(self):  # noqa: ANN202
        wd, we = self.target_debt_weight, self.target_equity_weight
        if (wd is None) ^ (we is None):
            raise ValueError("target_debt_weight and target_equity_weight must both be set or both null")
        if wd is not None and abs(wd + we - 1.0) > 1e-9:
            raise ValueError(f"target weights must sum to 1; got wd={wd}, we={we}")
        if self.composite_weights is not None:
            if set(self.composite_weights) != {"dcf", "exit_multiple"}:
                raise ValueError("composite_weights keys must be exactly {dcf, exit_multiple}")
            if abs(sum(self.composite_weights.values()) - 1.0) > 1e-9:
                raise ValueError("composite_weights must sum to 1")
        return self


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


FUNDAMENTAL_STATES = ("GROWTH", "STABLE", "DETERIORATING", "RECOVERY", "DISTRESS")  # DISTRESS optional (§8.2)


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
        description="legacy carrier source; Phase 9 estimator lives in vms.market_pricing (never inferred from fundamentals)")

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
    default_spec: Literal["pooled_t", "pooled_empirical", "regime_t", "prior_only", "persistence_t"]
    coverage_tolerance: float = Field(gt=0, lt=0.5, description="flag COVERAGE_MISCALIBRATED when |coverage - nominal| > this")

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



class SensitivityConfig(_Strict):
    """Phase 8 sensitivity / attribution defaults (explicit labeled shocks, not calibrated)."""

    n_paths: int = Field(default=50, gt=0, le=100_000, description="paths for each sensitivity re-run")
    check_seed_stability: bool = Field(default=False, description="skip expensive seed check on sensitivity re-sims")
    oat_driver_shocks: dict[str, float] = Field(
        default_factory=lambda: {
            "revenue_growth": 0.02,
            "ebit_margin": 0.01,
            "capex_to_revenue": 0.01,
            "receivables_to_revenue": 0.02,
            "diluted_share_growth": 0.01,
        },
        description="additive OAT shocks to path driver levels",
    )
    wacc_shock: float = Field(default=0.01, gt=0, lt=0.2, description="additive shock to cost_of_equity / RF path")
    terminal_growth_shock: float = Field(default=0.005, gt=0, lt=0.05)
    exit_multiple_shock: float = Field(default=1.0, gt=0, lt=20)
    policy_alt: str = Field(default="historical_continuation", description="alternate capital-allocation policy")
    posterior_tilt_state: str = Field(default="GROWTH", description="state to overweight in posterior OAT")
    posterior_tilt: float = Field(default=0.15, ge=0, le=0.9, description="probability mass shifted toward tilt state")
    transition_stay_boost: float = Field(default=0.5, ge=0, le=5.0, description="Dirichlet stay pseudo-count add-on")



class MultiplesPeerFilterConfig(_Strict):
    """Comparability filters for PIT peer universe (SPEC §12.5)."""

    require_same_profile: bool = False
    max_size_ratio: float | None = Field(default=None, gt=1.0)
    max_abs_growth_diff: float | None = Field(default=None, ge=0.0)
    max_abs_profitability_diff: float | None = Field(default=None, ge=0.0)
    max_abs_leverage_diff: float | None = Field(default=None, ge=0.0)
    exclude_subject_self: bool = True


class MultiplesConfig(_Strict):
    """Relative multiples settings (SPEC §12.5–12.6). Phase 5."""

    near_zero_eps: float = Field(default=1e-6, gt=0, lt=1.0)
    peer_min_count: int = Field(default=5, ge=1, le=100)
    peer_warn_count: int = Field(default=8, ge=1, le=200)
    aggregator: Literal["median", "winsorized_mean", "trimmed_mean"] = "median"
    winsor_pct: float = Field(default=0.10, ge=0.0, lt=0.5)
    trim_pct: float = Field(default=0.10, ge=0.0, lt=0.5)
    max_dispersion_ratio: float = Field(default=2.0, gt=0)
    shrink_prior: float | None = Field(default=None, gt=0)
    shrink_strength: float = Field(default=0.0, ge=0)
    filters: MultiplesPeerFilterConfig = Field(default_factory=MultiplesPeerFilterConfig)


class VMSConfig(_Strict):
    configuration_version: str = Field(min_length=1)
    method_registry_file: str = Field(
        default="method_registry.yaml",
        description="path relative to the config file; empty registry is valid in Phase 0",
    )
    router_file: str = Field(default="router.yaml")
    profiles_file: str = Field(default="profiles.yaml")
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
    valuation: ValuationConfig
    multiples: MultiplesConfig = Field(default_factory=MultiplesConfig)
    sensitivity: SensitivityConfig = Field(default_factory=SensitivityConfig)
    market_pricing: MarketPricingConfig = Field(
        default_factory=MarketPricingConfig,
        description="Phase 9 market-pricing regime + exit-price engine (SPEC §14)",
    )

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
    """Validated config plus resolved driver profile and Phase-0 declarative catalogs."""

    config: VMSConfig
    profile: DriverProfile
    config_path: str
    profile_path: str
    method_registry: MethodRegistryConfig
    router: RouterConfig
    profiles_catalog: ProfilesCatalogConfig
    method_registry_path: str
    router_path: str
    profiles_path: str


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


def _load_sidecar(path: Path, model: type, label: str):
    data = _read_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"invalid {label}\n{format_validation_error(e, str(path))}") from None


def load_method_registry(path: str | Path) -> MethodRegistryConfig:
    return _load_sidecar(Path(path), MethodRegistryConfig, "method registry")


def load_router(path: str | Path) -> RouterConfig:
    return _load_sidecar(Path(path), RouterConfig, "router config")


def load_profiles_catalog(path: str | Path) -> ProfilesCatalogConfig:
    return _load_sidecar(Path(path), ProfilesCatalogConfig, "profiles catalog")


def load_config(path: str | Path) -> LoadedConfig:
    path = Path(path).resolve()
    data = _read_yaml(path)
    try:
        cfg = VMSConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"invalid config\n{format_validation_error(e, str(path))}") from None
    profile_path = (path.parent / cfg.driver_profile).resolve()
    profile = load_driver_profile(profile_path)
    registry_path = (path.parent / cfg.method_registry_file).resolve()
    router_path = (path.parent / cfg.router_file).resolve()
    profiles_path = (path.parent / cfg.profiles_file).resolve()
    return LoadedConfig(
        config=cfg,
        profile=profile,
        config_path=str(path),
        profile_path=str(profile_path),
        method_registry=load_method_registry(registry_path),
        router=load_router(router_path),
        profiles_catalog=load_profiles_catalog(profiles_path),
        method_registry_path=str(registry_path),
        router_path=str(router_path),
        profiles_path=str(profiles_path),
    )
