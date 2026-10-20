"""Sector-profile plug-in interface (SPEC §7.2).

Sector logic lives only in registered ``SectorProfile`` classes and in configuration
(``industry`` block). Nothing else branches on industry. Profile resolution:

1. no PIT classification known  -> default profile, flag INDUSTRY_UNCLASSIFIED (INDUSTRY-UNCLASSIFIED-v1)
2. classification scheme differs from config -> UNSUPPORTED_PROFILE (cannot map safely)
3. industry in ``unsupported``  -> UNSUPPORTED_PROFILE (raw metrics only, no projection/DCF)
4. industry in ``profile_map``  -> that registered profile
5. otherwise                    -> default profile (+ PROFILE_CAUTION if listed in ``caution``)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from vms.assumptions import cite
from vms.schemas import InstrumentClassification
from vms.schemas.config import ConfigError, DriverProfile, IndustryConfig


class ProfileStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"


class ProfileResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: ProfileStatus
    profile_id: str | None
    scheme: str | None
    industry: str | None
    reason: str
    flags: list[str]
    assumptions: list[str]


class SectorProfile(ABC):
    """A sector profile: which drivers it needs and how it projects statements."""

    profile_id: ClassVar[str]
    required_drivers: ClassVar[frozenset[str]]

    def validate_driver_profile(self, dp: DriverProfile) -> None:
        if dp.profile_id != self.profile_id:
            raise ConfigError(f"driver profile id '{dp.profile_id}' does not match sector profile '{self.profile_id}'")
        names = {d.name: d for d in dp.drivers}
        missing = sorted(self.required_drivers - set(names))
        if missing:
            raise ConfigError(f"driver profile '{dp.profile_id}' lacks drivers required by the projection: {missing}")
        not_proj = sorted(n for n in self.required_drivers if names[n].role != "projection")
        if not_proj:
            raise ConfigError(f"drivers {not_proj} are required for projection but marked role=diagnostic")
        no_prior = sorted(n for n in self.required_drivers if names[n].prior is None)
        if no_prior:
            raise ConfigError(f"projection drivers {no_prior} need a labeled 'prior' fallback in '{dp.profile_id}'")

    @abstractmethod
    def project(self, **kwargs: Any) -> Any:
        """Deterministic statement projection; see the concrete profile for the signature."""


_REGISTRY: dict[str, type[SectorProfile]] = {}


def register_profile(cls: type[SectorProfile]) -> type[SectorProfile]:
    if cls.profile_id in _REGISTRY:
        raise ValueError(f"profile '{cls.profile_id}' already registered")
    _REGISTRY[cls.profile_id] = cls
    return cls


def registered_profiles() -> list[str]:
    import vms.statements  # noqa: F401  (registers built-in profiles)
    return sorted(_REGISTRY)


def get_profile(profile_id: str) -> SectorProfile:
    import vms.statements  # noqa: F401
    if profile_id not in _REGISTRY:
        raise ConfigError(f"profile '{profile_id}' is not registered; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[profile_id]()


def resolve_profile(classification: InstrumentClassification | None, cfg: IndustryConfig) -> ProfileResolution:
    a = cite("INDUSTRY-SW-L1-v1", "INDUSTRY-UNCLASSIFIED-v1")
    registered = registered_profiles()
    for ind, pid in cfg.profile_map.items():
        if pid not in registered:
            raise ConfigError(f"industry.profile_map: '{ind}' -> '{pid}' is not a registered profile {registered}")
    if cfg.default_profile not in registered:
        raise ConfigError(f"industry.default_profile '{cfg.default_profile}' not registered {registered}")
    if classification is None:
        return ProfileResolution(status=ProfileStatus.SUPPORTED, profile_id=cfg.default_profile, scheme=None,
                                 industry=None, reason="no classification known at as_of; generic profile used",
                                 flags=["INDUSTRY_UNCLASSIFIED"], assumptions=a)
    sch, ind = classification.scheme, classification.industry
    if sch != cfg.scheme:
        return ProfileResolution(status=ProfileStatus.UNSUPPORTED_PROFILE, profile_id=None, scheme=sch, industry=ind,
                                 reason=f"classification scheme '{sch}' is not the configured '{cfg.scheme}'; "
                                        "industry support cannot be determined", flags=["INDUSTRY_SCHEME_MISMATCH"],
                                 assumptions=a)
    if ind in cfg.unsupported:
        return ProfileResolution(status=ProfileStatus.UNSUPPORTED_PROFILE, profile_id=None, scheme=sch, industry=ind,
                                 reason=f"industry '{ind}' is configured unsupported (generic FCFF/EV inappropriate); "
                                        "raw metrics only, no projection", flags=["UNSUPPORTED_PROFILE"],
                                 assumptions=a)
    pid = cfg.profile_map.get(ind, cfg.default_profile)
    flags = ["PROFILE_CAUTION"] if ind in cfg.caution else []
    return ProfileResolution(status=ProfileStatus.SUPPORTED, profile_id=pid, scheme=sch, industry=ind,
                             reason=f"industry '{ind}' -> profile '{pid}'", flags=flags, assumptions=a)
