"""Cyclical normalization hooks (SPEC §12.6).

Phase 5 ships flags / low-confidence markers when mid-cycle inputs are unavailable.
Does not invent a full cycle model; never treats trailing peak earnings as sustainable
by default without qualification.

Skeleton PIT mid-cycle estimator lives in ``vms.methods.multiples.midcycle`` and is
optionally invoked from ``common.run_multiple_method`` for cyclical profiles only.
``assess_cycle_normalization`` remains the sole qualification hook: HIGH estimates
may supply ``mid_cycle_denominator``; None / LOW still flag trailing-without-midcycle.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.protocol import ValuationContext
from vms.schemas.contracts import ProfileFlag, ProfileLabel


class CycleNormalizationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mid_cycle_available: bool
    used_trailing: bool
    flags: list[str] = Field(default_factory=list)
    detail: str = ""
    normalized_denominator: float | None = None
    trailing_denominator: float | None = None


def assess_cycle_normalization(
    context: ValuationContext,
    *,
    trailing_denominator: float | None,
    mid_cycle_denominator: float | None = None,
    method_id: str,
) -> CycleNormalizationReport:
    flags: list[str] = []
    cyclical = (
        context.profile.primary_profile is ProfileLabel.CYCLICAL_OPERATING
        or any(f is ProfileFlag.HIGH_CYCLICALITY for f in context.profile.flags)
    )
    mid = mid_cycle_denominator
    if mid is not None and mid > 0:
        if cyclical:
            flags.append("MID_CYCLE_DENOMINATOR_USED")
        return CycleNormalizationReport(
            mid_cycle_available=True, used_trailing=False, flags=flags,
            detail="mid-cycle denominator supplied",
            normalized_denominator=mid, trailing_denominator=trailing_denominator,
        )

    # No mid-cycle available: only qualify cyclical names (SPEC §12.6).
    # Mature non-cyclical trailing denominators are allowed without cycle-low-confidence.
    if cyclical:
        flags.append("CYCLE_ESTIMATE_LOW_CONFIDENCE")
        flags.append("TRAILING_DENOMINATOR_UNQUALIFIED_RISK")
        flags.append("CYCLICAL_PROFILE_TRAILING_NOT_DEFAULT_SUSTAINABLE")
    elif method_id == "ev_sales":
        # Sales multiple remains relative-pricing; no cycle flag required here.
        pass
    return CycleNormalizationReport(
        mid_cycle_available=False, used_trailing=True, flags=sorted(set(flags)),
        detail="mid-cycle unavailable; trailing used with explicit qualification",
        normalized_denominator=None, trailing_denominator=trailing_denominator,
    )


def cycle_diagnostics(report: CycleNormalizationReport) -> dict[str, Any]:
    return report.model_dump(mode="json")
