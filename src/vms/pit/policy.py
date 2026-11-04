"""PIT policy labels for research scoring vs true version completeness.

``pit_complete`` remains true only for FULL_HISTORY sources.
Declared LATEST_ONLY panels may be research-scored under ``PIT_ASSUMED`` /
``VENDOR_LATEST_AS_OF`` (NOTICE_DATE still gates availability timing) without
claiming historical version reconstructibility or authorizing PASS.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from vms.schemas.observations import SourceDescriptor, Versioning

# Explicit alias used in artifacts / reports (same policy as PIT_ASSUMED).
VENDOR_LATEST_AS_OF = "VENDOR_LATEST_AS_OF"


class PitPolicy(str, Enum):
    """How an origin may enter research ``scores_unbiased``."""

    PIT_COMPLETE = "PIT_COMPLETE"  # all used sources FULL_HISTORY; pit_complete=true
    PIT_ASSUMED = "PIT_ASSUMED"  # declared LATEST_ONLY (vendor-as-of); research-eligible
    PIT_INCOMPLETE = "PIT_INCOMPLETE"  # undeclared / UNKNOWN; excluded from research scores


def classify_pit_policy(
    sources: Mapping[str, SourceDescriptor | None] | None,
) -> PitPolicy:
    """Classify PIT policy from snapshot source map.

    Empty source map → PIT_COMPLETE (matches ``pit_complete=all(...)`` vacuously).
    Any undeclared (None) or UNKNOWN versioning → PIT_INCOMPLETE.
    All FULL_HISTORY → PIT_COMPLETE.
    Only FULL_HISTORY and/or LATEST_ONLY with ≥1 LATEST_ONLY → PIT_ASSUMED.
    """
    if not sources:
        return PitPolicy.PIT_COMPLETE
    vals = list(sources.values())
    if any(sd is None for sd in vals):
        return PitPolicy.PIT_INCOMPLETE
    versionings = {sd.versioning for sd in vals}  # type: ignore[union-attr]
    if Versioning.UNKNOWN in versionings:
        return PitPolicy.PIT_INCOMPLETE
    if versionings == {Versioning.FULL_HISTORY}:
        return PitPolicy.PIT_COMPLETE
    if versionings <= {Versioning.FULL_HISTORY, Versioning.LATEST_ONLY}:
        # At least one LATEST_ONLY (else would have matched FULL_HISTORY-only above).
        return PitPolicy.PIT_ASSUMED
    return PitPolicy.PIT_INCOMPLETE


def research_score_eligible(record: Mapping[str, Any] | None, *, pit_complete: bool | None = None,
                            pit_policy: str | PitPolicy | None = None) -> bool:
    """True when an origin may enter research ``scores_unbiased``.

    Eligible if ``pit_complete`` or ``pit_policy == PIT_ASSUMED``.
    Undeclared / UNKNOWN (PIT_INCOMPLETE policy) stays out.
    """
    if record is not None:
        if pit_complete is None:
            pit_complete = bool(record.get("pit_complete"))
        if pit_policy is None:
            pit_policy = record.get("pit_policy")
    if pit_complete:
        return True
    pol = pit_policy.value if isinstance(pit_policy, PitPolicy) else pit_policy
    return pol == PitPolicy.PIT_ASSUMED.value


def vendor_latest_as_of(pit_policy: PitPolicy | str | None) -> bool:
    """Artifact flag: research path uses vendor LATEST_ONLY as-of assumption."""
    pol = pit_policy.value if isinstance(pit_policy, PitPolicy) else pit_policy
    return pol == PitPolicy.PIT_ASSUMED.value


__all__ = [
    "VENDOR_LATEST_AS_OF",
    "PitPolicy",
    "classify_pit_policy",
    "research_score_eligible",
    "vendor_latest_as_of",
]
