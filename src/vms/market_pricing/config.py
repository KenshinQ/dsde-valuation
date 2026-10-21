"""Market-pricing / exit-price configuration (SPEC §14). Explicit placeholders, not calibrated."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FallbackPriorConfig(_Strict):
    """Low-confidence prior used when estimation is unsupported (SPEC §14.3)."""

    COMPRESSED: float = Field(default=0.15, ge=0, le=1)
    NORMAL: float = Field(default=0.55, ge=0, le=1)
    EXPANDED: float = Field(default=0.25, ge=0, le=1)
    DISLOCATION: float = Field(default=0.05, ge=0, le=1)

    def as_dict(self) -> dict[str, float]:
        return {
            "COMPRESSED": self.COMPRESSED,
            "NORMAL": self.NORMAL,
            "EXPANDED": self.EXPANDED,
            "DISLOCATION": self.DISLOCATION,
        }

    @model_validator(mode="after")
    def _sum(self) -> "FallbackPriorConfig":
        s = self.COMPRESSED + self.NORMAL + self.EXPANDED + self.DISLOCATION
        if abs(s - 1.0) > 1e-9:
            raise ValueError(f"fallback prior must sum to 1.0; got {s}")
        return self


class StateScaleConfig(_Strict):
    """Multiplicative scales on the base terminal multiple by market-pricing state."""

    COMPRESSED: float = Field(default=0.75, gt=0, lt=5)
    NORMAL: float = Field(default=1.0, gt=0, lt=5)
    EXPANDED: float = Field(default=1.30, gt=0, lt=5)
    DISLOCATION: float = Field(default=0.55, gt=0, lt=5)

    def scale(self, state: str) -> float:
        return float(getattr(self, state))


class TerminalMultipleFamilyConfig(_Strict):
    """Base center / dispersion for one terminal-multiple family (explicit ASSUMPTION)."""

    metric_id: Literal["pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"]
    center: float = Field(gt=0, description="base multiple under NORMAL market-pricing state")
    log_sigma: float = Field(default=0.25, gt=0, lt=2.0, description="lognormal sigma around scaled center")
    min_multiple: float = Field(default=0.5, gt=0)
    max_multiple: float = Field(default=80.0, gt=0)

    @model_validator(mode="after")
    def _bounds(self) -> "TerminalMultipleFamilyConfig":
        if self.min_multiple >= self.max_multiple:
            raise ValueError("min_multiple must be < max_multiple")
        if not (self.min_multiple <= self.center <= self.max_multiple):
            raise ValueError("center must lie within [min_multiple, max_multiple]")
        return self


class MeanReversionConfig(_Strict):
    """Configured (not estimated) slow/fast reversion toward NORMAL. Never invented from short series."""

    enabled: bool = False
    estimation_status: Literal["UNSUPPORTED", "CONFIGURED_ONLY"] = "UNSUPPORTED"
    # Probability of transitioning toward NORMAL each year when not already NORMAL.
    slow_reversion_rate: float = Field(default=0.10, ge=0, le=1)
    fast_reversion_rate: float = Field(default=0.35, ge=0, le=1)
    # Stay probability when already NORMAL under configured MR.
    normal_stay: float = Field(default=0.80, ge=0, le=1)


class ConvergenceScenarioConfig(_Strict):
    """Optional named convergence-to-intrinsic scenario. Disabled by default (SPEC §14.4)."""

    enabled: bool = False
    scenario_id: str = "CONVERGENCE_TO_INTRINSIC"
    # Stochastic rate: each path draws u~U(0,1); if u < rate, blend toward intrinsic.
    stochastic_rate: float = Field(default=0.25, ge=0, le=1)
    # Weight on intrinsic when convergence fires: exit = (1-w)*market + w*intrinsic
    blend_weight: float = Field(default=0.5, ge=0, le=1)


class DependenceConfig(_Strict):
    """Optional explicit dependence between fundamental and market-pricing states.

    Default NONE: market and fundamental evolve independently.
    CONFIGURED requires an explicit transition overlay (Phase 9 ships NONE only as runtime default;
    configuring dependence=CONFIGURED without a matrix is rejected).
    """

    mode: Literal["NONE", "CONFIGURED"] = "NONE"
    # Optional: map fundamental_state -> multiplicative tilt factors on market prior
    # (keys must be fundamental labels; values dict of market state -> weight multiplier).
    fundamental_tilt: dict[str, dict[str, float]] | None = None


class MarketPricingConfig(_Strict):
    """Top-level market-pricing / exit-price config (SPEC §14)."""

    version: str = "vms-market-pricing-0.2.phase9"
    default_metric_id: Literal["pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"] = "ev_ebitda"
    min_history_obs_for_estimation: int = Field(default=12, ge=1, le=120)
    fallback_prior: FallbackPriorConfig = Field(default_factory=FallbackPriorConfig)
    state_scales: StateScaleConfig = Field(default_factory=StateScaleConfig)
    families: list[TerminalMultipleFamilyConfig] = Field(
        default_factory=lambda: [
            TerminalMultipleFamilyConfig(metric_id="pe", center=15.0, log_sigma=0.30, min_multiple=3.0, max_multiple=60.0),
            TerminalMultipleFamilyConfig(metric_id="pb", center=2.0, log_sigma=0.25, min_multiple=0.3, max_multiple=12.0),
            TerminalMultipleFamilyConfig(metric_id="ev_ebit", center=12.0, log_sigma=0.25, min_multiple=2.0, max_multiple=40.0),
            TerminalMultipleFamilyConfig(metric_id="ev_ebitda", center=8.0, log_sigma=0.25, min_multiple=2.0, max_multiple=30.0),
            TerminalMultipleFamilyConfig(metric_id="ev_sales", center=2.5, log_sigma=0.30, min_multiple=0.2, max_multiple=20.0),
        ]
    )
    mean_reversion: MeanReversionConfig = Field(default_factory=MeanReversionConfig)
    convergence: ConvergenceScenarioConfig = Field(default_factory=ConvergenceScenarioConfig)
    dependence: DependenceConfig = Field(default_factory=DependenceConfig)
    lease_debt_like: float = Field(default=0.0, ge=0)
    other_senior_claims: float = Field(default=0.0, ge=0)
    minority_interest_book: float = Field(default=0.0, ge=0)

    def family(self, metric_id: str) -> TerminalMultipleFamilyConfig:
        for f in self.families:
            if f.metric_id == metric_id:
                return f
        raise KeyError(f"no terminal-multiple family configured for metric_id={metric_id!r}")

    @model_validator(mode="after")
    def _unique_families(self) -> "MarketPricingConfig":
        ids = [f.metric_id for f in self.families]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate terminal-multiple families: {ids}")
        if self.default_metric_id not in ids:
            raise ValueError(f"default_metric_id {self.default_metric_id!r} not in families {ids}")
        if self.dependence.mode == "CONFIGURED" and not self.dependence.fundamental_tilt:
            raise ValueError("dependence.mode=CONFIGURED requires fundamental_tilt")
        return self


def default_market_pricing_config() -> MarketPricingConfig:
    return MarketPricingConfig()
