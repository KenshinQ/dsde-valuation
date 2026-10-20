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
    description: str = ""

    @model_validator(mode="after")
    def _bounds(self) -> "DriverSpec":
        if not (math.isfinite(self.lower) and math.isfinite(self.upper)):
            raise ValueError(f"driver '{self.name}': bounds must be finite")
        if self.lower >= self.upper:
            raise ValueError(f"driver '{self.name}': lower={self.lower} must be < upper={self.upper}")
        if self.transform is DriverTransform.LOGIT and not (0.0 <= self.lower and self.upper <= 1.0):
            raise ValueError(
                f"driver '{self.name}': transform 'logit' requires bounds within [0, 1], "
                f"got [{self.lower}, {self.upper}]"
            )
        if self.transform is DriverTransform.LOG1P and self.lower <= -1.0:
            raise ValueError(f"driver '{self.name}': transform 'log1p' requires lower > -1, got {self.lower}")
        return self


class DriverProfile(_Strict):
    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    supported: bool
    bounds_status: Literal["placeholder", "calibrated"] = Field(
        description="'placeholder' until Phase 2/3 estimation justifies the bounds"
    )
    unsupported_industries: list[str] = Field(default_factory=list)
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
