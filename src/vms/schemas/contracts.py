"""VMS-0.2 Phase 0 domain contracts (SPEC §§6.1, 7.2, 10.1, 11, 16.3, 17.4).

These enums and lightweight models establish the Adaptive Multi-Method vocabulary
without implementing profile classification, routing, or valuation methods.
Empty method registries are valid; no method here claims to produce a value.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


# --------------------------------------------------------------------------- §6.1 observation quality (SPEC spelling)
class ObservationQualityStatus(str, Enum):
    """Canonical §6.1 spellings. Observation models in observations.py still accept
    lowercase aliases for VMS-0.1 data compatibility (see QualityStatus there)."""

    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


# --------------------------------------------------------------------------- §6.4 data-quality run status
class DataQualityGateStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    BLOCKED = "BLOCKED"
    PIT_INCOMPLETE = "PIT_INCOMPLETE"
    UNSUPPORTED_PROFILE = "UNSUPPORTED_PROFILE"
    INSUFFICIENT_METHOD_COVERAGE = "INSUFFICIENT_METHOD_COVERAGE"


# --------------------------------------------------------------------------- §10.1 valuation targets
class ValuationTarget(str, Enum):
    FUNDAMENTAL_VALUE_CURRENT = "FUNDAMENTAL_VALUE_CURRENT"
    FUNDAMENTAL_VALUE_HORIZON = "FUNDAMENTAL_VALUE_HORIZON"
    RELATIVE_VALUE_CURRENT = "RELATIVE_VALUE_CURRENT"
    MARKET_EXIT_PRICE = "MARKET_EXIT_PRICE"
    ASSET_NAV = "ASSET_NAV"
    TOTAL_RETURN = "TOTAL_RETURN"


# --------------------------------------------------------------------------- §7.2 profile labels / flags
class ProfileLabel(str, Enum):
    MATURE_OPERATING = "MATURE_OPERATING"
    GROWTH_OR_REINVESTMENT_HEAVY = "GROWTH_OR_REINVESTMENT_HEAVY"
    CYCLICAL_OPERATING = "CYCLICAL_OPERATING"
    FINANCIAL_INSTITUTION = "FINANCIAL_INSTITUTION"
    ASSET_HEAVY_OR_RESOURCE = "ASSET_HEAVY_OR_RESOURCE"
    HOLDING_OR_CONGLOMERATE = "HOLDING_OR_CONGLOMERATE"
    DISTRESSED_OR_TURNAROUND = "DISTRESSED_OR_TURNAROUND"
    HYBRID_OR_UNCLEAR = "HYBRID_OR_UNCLEAR"


class ProfileFlag(str, Enum):
    """Independent flags from SPEC §7.2 (classifier populates these in Phase 2)."""

    CURRENT_FCF_NEGATIVE = "CURRENT_FCF_NEGATIVE"
    EARNINGS_NEGATIVE_OR_UNSTABLE = "EARNINGS_NEGATIVE_OR_UNSTABLE"
    DIVIDEND_PAYING = "DIVIDEND_PAYING"
    HIGH_CASH_OR_NET_CASH = "HIGH_CASH_OR_NET_CASH"
    HIGH_LEVERAGE = "HIGH_LEVERAGE"
    MAJOR_DILUTION = "MAJOR_DILUTION"
    MATERIAL_NONOPERATING_ASSETS = "MATERIAL_NONOPERATING_ASSETS"
    HIGH_CYCLICALITY = "HIGH_CYCLICALITY"
    SHORT_PUBLIC_HISTORY = "SHORT_PUBLIC_HISTORY"
    MATERIAL_SEGMENT_COMPLEXITY = "MATERIAL_SEGMENT_COMPLEXITY"
    LOW_DATA_QUALITY = "LOW_DATA_QUALITY"


# --------------------------------------------------------------------------- §16.3 method result status
class MethodEligibilityStatus(str, Enum):
    """Per-method outcome in a result bundle. Distinct from observation QualityStatus."""

    NOT_RUN = "NOT_RUN"
    INELIGIBLE = "INELIGIBLE"
    FAILED = "FAILED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    VALID = "VALID"


# --------------------------------------------------------------------------- §17.4 claim / calibration labels
class ClaimStatus(str, Enum):
    ENGINEERING_PASS = "ENGINEERING_PASS"
    DATA_QUALITY_PASS = "DATA_QUALITY_PASS"
    CALIBRATION_PASS = "CALIBRATION_PASS"
    CALIBRATION_INSUFFICIENT = "CALIBRATION_INSUFFICIENT"
    ENSEMBLE_CALIBRATED = "ENSEMBLE_CALIBRATED"
    INVESTMENT_VALUE_NOT_ESTABLISHED = "INVESTMENT_VALUE_NOT_ESTABLISHED"
    INVESTMENT_VALUE_SUPPORTED = "INVESTMENT_VALUE_SUPPORTED"


# --------------------------------------------------------------------------- Method family ids (registry keys only)
class MethodFamilyId(str, Enum):
    """Declared method identifiers. Presence in the enum does not mean implemented."""

    FCFF_DCF = "fcff_dcf"
    FCFE_DCF = "fcfe_dcf"
    DDM = "ddm"
    RESIDUAL_INCOME = "residual_income"
    PE = "pe"
    PB = "pb"
    EV_EBIT = "ev_ebit"
    EV_EBITDA = "ev_ebitda"
    EV_SALES = "ev_sales"
    NAV = "nav"
    SOTP = "sotp"


class MethodImplementationStatus(str, Enum):
    """Registry-level implementation flag. Phase 0 ships an empty or NOT_IMPLEMENTED registry."""

    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    IMPLEMENTED = "IMPLEMENTED"
    DISABLED = "DISABLED"


class MethodRegistryEntry(_Strict):
    """Declarative method plugin stub in config/method_registry.yaml.

    Phase 0: entries may exist only as documentation of intended ids; computation
    interfaces arrive in later phases. enabled=True with NOT_IMPLEMENTED is rejected.
    """

    method_id: str = Field(min_length=1)
    family: MethodFamilyId | None = None
    display_name: str = ""
    implementation_status: MethodImplementationStatus = MethodImplementationStatus.NOT_IMPLEMENTED
    enabled: bool = False
    supported_targets: list[ValuationTarget] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _no_fake_value(self) -> "MethodRegistryEntry":
        if self.enabled and self.implementation_status is not MethodImplementationStatus.IMPLEMENTED:
            raise ValueError(
                f"method_id={self.method_id!r}: enabled=true requires implementation_status=IMPLEMENTED; "
                f"got {self.implementation_status.value} (Phase 0 forbids fake valuing methods)"
            )
        if self.implementation_status is MethodImplementationStatus.IMPLEMENTED and not self.supported_targets:
            raise ValueError(
                f"method_id={self.method_id!r}: IMPLEMENTED methods must declare supported_targets"
            )
        return self


class MethodRegistryConfig(_Strict):
    registry_version: str = Field(min_length=1)
    methods: list[MethodRegistryEntry] = Field(default_factory=list)

    @field_validator("methods")
    @classmethod
    def _unique_ids(cls, v: list[MethodRegistryEntry]) -> list[MethodRegistryEntry]:
        ids = [m.method_id for m in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate method_id values: {dupes}")
        return v

    @property
    def enabled_methods(self) -> list[MethodRegistryEntry]:
        return [m for m in self.methods if m.enabled]


class RouterConfig(_Strict):
    """Declarative router policy placeholders (Phase 2+ consumes; Phase 0 validates only)."""

    router_version: str = Field(min_length=1)
    require_hard_gates: bool = True
    allow_ensemble_without_calibration: bool = False
    min_eligible_methods_for_coverage: int = Field(default=1, ge=0)
    default_target: ValuationTarget = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    notes: str = "Phase 0 placeholder; routing logic is Phase 2+"


class ProfileCatalogEntry(_Strict):
    label: ProfileLabel
    description: str = ""
    candidate_method_ids: list[str] = Field(default_factory=list)
    default_exclusions: list[str] = Field(default_factory=list)


class ProfilesCatalogConfig(_Strict):
    catalog_version: str = Field(min_length=1)
    profiles: list[ProfileCatalogEntry] = Field(min_length=1)

    @field_validator("profiles")
    @classmethod
    def _unique_labels(cls, v: list[ProfileCatalogEntry]) -> list[ProfileCatalogEntry]:
        labels = [p.label for p in v]
        if len(set(labels)) != len(labels):
            raise ValueError("duplicate profile labels in catalog")
        return v


class MethodStatusRecord(_Strict):
    """One method's status row in a Phase-0+ result bundle (method_eligibility.json)."""

    method_id: str = Field(min_length=1)
    status: MethodEligibilityStatus
    reason: str = ""
    target: ValuationTarget | None = None


class Phase0ClaimLabels(_Strict):
    """Required claim labels on every Phase 0 result bundle."""

    ENGINEERING_PASS: bool
    DATA_QUALITY_PASS: bool | None = None
    CALIBRATION_STATUS: Literal["INCONCLUSIVE", "INSUFFICIENT", "PASS", "FAIL"] = "INCONCLUSIVE"
    investment_value: Literal[
        ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value,
        ClaimStatus.INVESTMENT_VALUE_SUPPORTED.value,
    ] = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    investment_value_reason: str = (
        "Phase 0 contracts/demo only; no valuation method executed; "
        "engineering success is not investment alpha (SPEC §2.12 / §17.4)"
    )
    data_label: str = "SYNTHETIC"


__all__ = [
    "ObservationQualityStatus",
    "DataQualityGateStatus",
    "ValuationTarget",
    "ProfileLabel",
    "ProfileFlag",
    "MethodEligibilityStatus",
    "ClaimStatus",
    "MethodFamilyId",
    "MethodImplementationStatus",
    "MethodRegistryEntry",
    "MethodRegistryConfig",
    "RouterConfig",
    "ProfileCatalogEntry",
    "ProfilesCatalogConfig",
    "MethodStatusRecord",
    "Phase0ClaimLabels",
]
