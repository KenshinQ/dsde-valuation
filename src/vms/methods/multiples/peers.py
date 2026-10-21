"""PIT peer-universe construction and comparability filters (SPEC §12.5, §21.3).

Peer membership and metrics use only data known at as_of (via peer_known_at).
Included / excluded names and reasons are always persisted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.pit.snapshot import peer_known_at
from vms.schemas.observations import PeerObservation


class PeerFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    require_same_profile: bool = False
    max_size_ratio: float | None = Field(
        default=None, gt=1.0, description="exclude peer if max(size_peer/size_subj, inverse) exceeds this",
    )
    max_abs_growth_diff: float | None = Field(default=None, ge=0.0)
    max_abs_profitability_diff: float | None = Field(default=None, ge=0.0)
    max_abs_leverage_diff: float | None = Field(default=None, ge=0.0)
    exclude_subject_self: bool = True


class PeerAttributes(BaseModel):
    """Optional comparability attributes known at as_of (must themselves be PIT)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_label: str | None = None
    size: float | None = Field(default=None, description="e.g. market cap or revenue")
    growth: float | None = None
    profitability: float | None = None
    leverage: float | None = None


class PeerExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    peer_instrument_id: str
    reasons: list[str]
    field_name: str | None = None
    value: float | None = None


class PeerInclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    peer_instrument_id: str
    field_name: str
    multiple: float
    published_at: str
    metric_timestamp: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class PeerSetReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_instrument_id: str
    as_of: str
    metric_field: str
    included: list[PeerInclusion] = Field(default_factory=list)
    excluded: list[PeerExclusion] = Field(default_factory=list)
    multiples: list[float] = Field(default_factory=list)
    n_included: int = 0
    n_excluded: int = 0
    pit_gate: str = "peer_known_at"


def build_peer_set(
    *,
    subject_instrument_id: str,
    as_of: datetime,
    metric_field: str,
    peers: list[PeerObservation],
    subject_attrs: PeerAttributes | None = None,
    peer_attrs: dict[str, PeerAttributes] | None = None,
    filters: PeerFilterConfig | None = None,
) -> PeerSetReport:
    """Construct a PIT-eligible peer multiple sample for one metric."""
    filters = filters or PeerFilterConfig()
    peer_attrs = peer_attrs or {}
    subject_attrs = subject_attrs or PeerAttributes()

    included: list[PeerInclusion] = []
    excluded: list[PeerExclusion] = []
    seen_keep: set[str] = set()

    for p in peers:
        pid = p.peer_instrument_id
        reasons: list[str] = []

        if filters.exclude_subject_self and pid == subject_instrument_id:
            reasons.append("SELF_PEER")
        if p.subject_instrument_id != subject_instrument_id:
            reasons.append("SUBJECT_MISMATCH")
        if not peer_known_at(p, as_of):
            # Classify PIT reason for persistence
            if p.published_at > as_of:
                reasons.append("PIT_PUBLISHED_AFTER_ASOF")
            else:
                from vms.pit.snapshot import local_date
                as_of_d = local_date(as_of)
                if p.membership_start is not None and p.membership_start > as_of_d:
                    reasons.append("PIT_MEMBERSHIP_START_AFTER_ASOF")
                if p.membership_end is not None and p.membership_end < as_of_d:
                    reasons.append("PIT_MEMBERSHIP_ENDED_BEFORE_ASOF")
                if p.metric_timestamp is not None and p.metric_timestamp > as_of:
                    reasons.append("PIT_METRIC_TIMESTAMP_AFTER_ASOF")
            if not reasons or reasons == ["SUBJECT_MISMATCH"]:
                reasons.append("PIT_NOT_KNOWN_AT_ASOF")
        if p.field_name != metric_field:
            if p.field_name is None:
                reasons.append("MEMBERSHIP_ONLY_ROW")
            else:
                reasons.append(f"METRIC_FIELD_MISMATCH:{p.field_name}")
        if p.value is None:
            reasons.append("MISSING_MULTIPLE_VALUE")
        elif not (isinstance(p.value, (int, float)) and __import__("math").isfinite(p.value) and p.value > 0):
            reasons.append("NONPOSITIVE_OR_NONFINITE_MULTIPLE")

        # Comparability filters (only when attrs provided)
        attrs = peer_attrs.get(pid)
        if filters.require_same_profile:
            if subject_attrs.profile_label is None or attrs is None or attrs.profile_label is None:
                reasons.append("PROFILE_COMPARABILITY_UNKNOWN")
            elif attrs.profile_label != subject_attrs.profile_label:
                reasons.append("PROFILE_MISMATCH")
        if filters.max_size_ratio is not None and subject_attrs.size is not None:
            if attrs is None or attrs.size is None or attrs.size <= 0 or subject_attrs.size <= 0:
                reasons.append("SIZE_COMPARABILITY_UNKNOWN")
            else:
                ratio = max(attrs.size / subject_attrs.size, subject_attrs.size / attrs.size)
                if ratio > filters.max_size_ratio:
                    reasons.append(f"SIZE_RATIO_EXCEEDED:{ratio:.3g}")
        if filters.max_abs_growth_diff is not None and subject_attrs.growth is not None:
            if attrs is None or attrs.growth is None:
                reasons.append("GROWTH_COMPARABILITY_UNKNOWN")
            elif abs(attrs.growth - subject_attrs.growth) > filters.max_abs_growth_diff:
                reasons.append("GROWTH_DIFF_EXCEEDED")
        if filters.max_abs_profitability_diff is not None and subject_attrs.profitability is not None:
            if attrs is None or attrs.profitability is None:
                reasons.append("PROFITABILITY_COMPARABILITY_UNKNOWN")
            elif abs(attrs.profitability - subject_attrs.profitability) > filters.max_abs_profitability_diff:
                reasons.append("PROFITABILITY_DIFF_EXCEEDED")
        if filters.max_abs_leverage_diff is not None and subject_attrs.leverage is not None:
            if attrs is None or attrs.leverage is None:
                reasons.append("LEVERAGE_COMPARABILITY_UNKNOWN")
            elif abs(attrs.leverage - subject_attrs.leverage) > filters.max_abs_leverage_diff:
                reasons.append("LEVERAGE_DIFF_EXCEEDED")

        if reasons:
            excluded.append(PeerExclusion(
                peer_instrument_id=pid, reasons=sorted(set(reasons)),
                field_name=p.field_name, value=p.value,
            ))
            continue

        assert p.value is not None and p.field_name is not None
        # Dedupe: keep latest metric_timestamp / published_at per peer
        key = pid
        inc = PeerInclusion(
            peer_instrument_id=pid,
            field_name=p.field_name,
            multiple=float(p.value),
            published_at=p.published_at.isoformat(),
            metric_timestamp=None if p.metric_timestamp is None else p.metric_timestamp.isoformat(),
            attributes={} if attrs is None else attrs.model_dump(mode="json"),
        )
        if key in seen_keep:
            # Replace if newer
            for i, prev in enumerate(included):
                if prev.peer_instrument_id == key:
                    prev_ts = prev.metric_timestamp or prev.published_at
                    new_ts = inc.metric_timestamp or inc.published_at
                    if new_ts >= prev_ts:
                        included[i] = inc
                    else:
                        excluded.append(PeerExclusion(
                            peer_instrument_id=pid,
                            reasons=["SUPERSEDED_BY_NEWER_PIT_METRIC"],
                            field_name=p.field_name, value=p.value,
                        ))
                    break
        else:
            included.append(inc)
            seen_keep.add(key)

    multiples = [i.multiple for i in included]
    return PeerSetReport(
        subject_instrument_id=subject_instrument_id,
        as_of=as_of.isoformat(),
        metric_field=metric_field,
        included=included,
        excluded=excluded,
        multiples=multiples,
        n_included=len(included),
        n_excluded=len(excluded),
    )
