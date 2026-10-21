"""Profile classification report models (SPEC §7.3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vms.schemas.contracts import ProfileFlag, ProfileLabel


class RuleHitRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    profile: ProfileLabel | None = None
    flag: ProfileFlag | None = None
    weight: float
    detail: str
    feature_refs: list[str] = Field(default_factory=list)


class ManualOverrideStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    applied: bool = False
    override_version: str | None = None
    reason: str | None = None
    overridden_primary: ProfileLabel | None = None
    source_path: str | None = None


class ProfileReport(BaseModel):
    """Full classifier output with traceability (SPEC §7.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    as_of: str
    classifier_version: str
    rules_version: str
    primary_profile: ProfileLabel
    flags: list[ProfileFlag] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    low_confidence: bool
    profile_scores: dict[str, float] = Field(default_factory=dict)
    profile_probabilities: dict[str, float] = Field(default_factory=dict)
    rule_hits: list[RuleHitRecord] = Field(default_factory=list)
    flag_hits: list[RuleHitRecord] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    feature_values: dict[str, Any] = Field(default_factory=dict)
    manual_override: ManualOverrideStatus = Field(default_factory=ManualOverrideStatus)
    investment_value: Literal["INVESTMENT_VALUE_NOT_ESTABLISHED"] = "INVESTMENT_VALUE_NOT_ESTABLISHED"
    notes: str = ""
