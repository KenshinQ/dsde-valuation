"""R2c: deposit-taking FI P/B-ROE relative pricing sidecar (common-equity BPS, raw close).

Uses existing build_peer_set + aggregate_multiples. Peer field = pb_common
(= peer raw_close / peer common BPS). Insufficient PIT peers → INELIGIBLE / PEER_SCARCITY
(no silent fill). Shared book math with RIM is labeled — not independent intrinsic evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from vms.assumptions import cite
from vms.methods.multiples.aggregate import aggregate_multiples
from vms.methods.multiples.apply import apply_equity_multiple
from vms.methods.multiples.definitions import MetricDefinition, ClaimObject, ValueClaimKind
from vms.methods.multiples.peers import PeerAttributes, PeerFilterConfig, build_peer_set
from vms.methods.rim.distribution import historical_common_roe
from vms.methods.rim.hist_pb import (
    PEER_FIELD_PB_COMMON,
    subject_pb_at_asof,
    subject_spot_raw_close,
)
from vms.methods.rim.from_snapshot import RimBridgeResult
from vms.pit.snapshot import PITSnapshot
from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label
from vms.schemas.observations import PeerObservation

DEFAULT_PEER_MIN = 5
DEFAULT_PEER_WARN = 8

_PB_COMMON_DEF = MetricDefinition(
    method_id="pb_common",
    display_name="P/B common-equity (deposit-taking FI)",
    peer_field_name=PEER_FIELD_PB_COMMON,
    denominator_field="common_equity",
    claim_object=ClaimObject.EQUITY,
    value_claim=ValueClaimKind.RELATIVE_EQUITY,
    applies_ev_bridge=False,
    formula="EquityValue = peer_pb_common × common_equity; VPS = EquityValue / diluted_shares",
    notes="Relative pricing only; common-equity BPS; raw close numerator. Not an independent "
          "intrinsic claim vs RIM (shared book math).",
)


@dataclass(frozen=True)
class PbRoeReport:
    ok: bool
    status: str  # VALID | INELIGIBLE | UNAVAILABLE
    ineligible_reason: str | None
    flags: list[str]
    assumption_ids: list[str]
    subject_pb: float | None
    subject_bps: float | None
    subject_roe: float | None
    subject_raw_close: float | None
    common_equity: float | None
    diluted_shares: float | None
    peer_field: str
    peer_n_included: int
    peer_n_excluded: int
    peer_min_count: int
    peer_median_pb: float | None
    peer_multiple: float | None
    relative_equity_value: float | None
    relative_vps: float | None
    rim_vps_crosscheck: float | None
    shared_book_math_note: str
    peer_set: dict[str, Any] = field(default_factory=dict)
    aggregate: dict[str, Any] = field(default_factory=dict)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "ineligible_reason": self.ineligible_reason,
            "flags": list(self.flags),
            "assumption_ids": list(self.assumption_ids),
            "subject_pb": self.subject_pb,
            "subject_bps": self.subject_bps,
            "subject_roe": self.subject_roe,
            "subject_raw_close": self.subject_raw_close,
            "common_equity": self.common_equity,
            "diluted_shares": self.diluted_shares,
            "peer_field": self.peer_field,
            "peer_n_included": self.peer_n_included,
            "peer_n_excluded": self.peer_n_excluded,
            "peer_min_count": self.peer_min_count,
            "peer_median_pb": self.peer_median_pb,
            "peer_multiple": self.peer_multiple,
            "relative_equity_value": self.relative_equity_value,
            "relative_vps": self.relative_vps,
            "rim_vps_crosscheck": self.rim_vps_crosscheck,
            "shared_book_math_note": self.shared_book_math_note,
            "peer_set": self.peer_set,
            "aggregate": self.aggregate,
            "detail": self.detail,
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "ensemble": None,
            "value_claim": "RELATIVE_PRICING_NOT_INDEPENDENT_INTRINSIC",
        }


SHARED_BOOK_NOTE = (
    "P/B-ROE relative VPS and RIM share common-equity book math; "
    "this is a relative-pricing cross-check, NOT independent intrinsic evidence. "
    "INVESTMENT_VALUE_NOT_ESTABLISHED."
)


def _latest_roe(snap: PITSnapshot, *, zeros_explicit: bool) -> tuple[float | None, list[str]]:
    hist = historical_common_roe(snap, zeros_explicit=zeros_explicit)
    if not hist.roe:
        return None, list(hist.flags) + ["SUBJECT_ROE_UNAVAILABLE"]
    return float(hist.roe[-1]), list(hist.flags)


def run_pb_roe_relative(
    snap: PITSnapshot,
    *,
    bridge: RimBridgeResult,
    peer_observations: Sequence[PeerObservation] | None = None,
    rim_vps_crosscheck: float | None = None,
    peer_min_count: int = DEFAULT_PEER_MIN,
    peer_warn_count: int = DEFAULT_PEER_WARN,
    require_same_sw_l1: bool = True,
    zeros_explicit: bool = True,
) -> PbRoeReport:
    """Compute subject P/B-ROE cross-check and optional peer-relative VPS."""
    aids = cite(
        "RIM-PB-ROE-PEER-v1",
        "RIM-COMMON-EQUITY-v1",
        "PEER-MULTIPLE-RELATIVE-v1",
        "HITHINK-NO-VENDOR-QFQ-v1",
        "NO-DOUBLE-EV-BRIDGE-v1",
    )
    flags: list[str] = [
        "RELATIVE_PRICING_ONLY",
        "SHARED_BOOK_MATH_NOT_INDEPENDENT_EVIDENCE",
        "NO_ENSEMBLE",
    ]
    ce = bridge.common_equity_0
    shares = None if not bridge.rim_inputs else bridge.rim_inputs.get("diluted_shares")
    spot, sflags = subject_spot_raw_close(snap)
    flags.extend(sflags)
    subject_roe, rflags = _latest_roe(snap, zeros_explicit=zeros_explicit)
    flags.extend(rflags)

    if ce is None or shares is None or spot is None:
        return PbRoeReport(
            ok=False,
            status="INELIGIBLE",
            ineligible_reason="MISSING_SUBJECT_PB_INPUTS",
            flags=sorted(set(flags + ["MISSING_SUBJECT_PB_INPUTS"])),
            assumption_ids=aids,
            subject_pb=None,
            subject_bps=None,
            subject_roe=subject_roe,
            subject_raw_close=spot,
            common_equity=ce,
            diluted_shares=None if shares is None else float(shares),
            peer_field=PEER_FIELD_PB_COMMON,
            peer_n_included=0,
            peer_n_excluded=0,
            peer_min_count=peer_min_count,
            peer_median_pb=None,
            peer_multiple=None,
            relative_equity_value=None,
            relative_vps=None,
            rim_vps_crosscheck=rim_vps_crosscheck,
            shared_book_math_note=SHARED_BOOK_NOTE,
            detail="need common_equity, diluted_shares, raw_close",
        )

    sub_pb, sub_bps, pbflags = subject_pb_at_asof(
        common_equity=float(ce), diluted_shares=float(shares), raw_close=float(spot),
    )
    flags.extend(pbflags)

    peers = list(peer_observations or [])
    bank_label = deposit_taking_fi_sw_label()
    subject_attrs = PeerAttributes(
        profile_label=bank_label or None,
        size=float(ce),
        profitability=subject_roe,
    )
    peer_attrs: dict[str, PeerAttributes] = {}
    for p in peers:
        # optional profile on attributes via source convention: only filter when attrs present
        peer_attrs.setdefault(
            p.peer_instrument_id,
            PeerAttributes(profile_label=bank_label or None),
        )

    filters = PeerFilterConfig(
        require_same_profile=bool(require_same_sw_l1 and bank_label),
        exclude_subject_self=True,
    )
    peer_report = build_peer_set(
        subject_instrument_id=snap.instrument_id,
        as_of=snap.as_of,
        metric_field=PEER_FIELD_PB_COMMON,
        peers=peers,
        subject_attrs=subject_attrs,
        peer_attrs=peer_attrs,
        filters=filters,
    )
    agg = aggregate_multiples(
        peer_report.multiples,
        estimator="median",
        peer_min_count=peer_min_count,
        peer_warn_count=peer_warn_count,
    )
    flags.extend(agg.flags)

    if not agg.ok or agg.multiple is None:
        # AC: insufficient PIT peers (incl. empty) → PEER_SCARCITY / INELIGIBLE (no silent fill)
        reason = "PEER_SCARCITY"
        return PbRoeReport(
            ok=False,
            status="INELIGIBLE",
            ineligible_reason=reason,
            flags=sorted(set(flags + [reason, "PB_ROE_RELATIVE_UNAVAILABLE"])),
            assumption_ids=aids,
            subject_pb=sub_pb,
            subject_bps=sub_bps,
            subject_roe=subject_roe,
            subject_raw_close=spot,
            common_equity=float(ce),
            diluted_shares=float(shares),
            peer_field=PEER_FIELD_PB_COMMON,
            peer_n_included=peer_report.n_included,
            peer_n_excluded=peer_report.n_excluded,
            peer_min_count=peer_min_count,
            peer_median_pb=agg.median,
            peer_multiple=None,
            relative_equity_value=None,
            relative_vps=None,
            rim_vps_crosscheck=rim_vps_crosscheck,
            shared_book_math_note=SHARED_BOOK_NOTE,
            peer_set=peer_report.model_dump(mode="json"),
            aggregate=agg.model_dump(mode="json"),
            detail=agg.detail,
        )

    valued = apply_equity_multiple(
        definition=_PB_COMMON_DEF,
        multiple=float(agg.multiple),
        denominator=float(ce),
        diluted_shares=float(shares),
    )
    flags.extend(valued.flags)
    if not valued.valid:
        return PbRoeReport(
            ok=False,
            status="INELIGIBLE",
            ineligible_reason=valued.invalid_reason or "APPLY_PB_FAILED",
            flags=sorted(set(flags)),
            assumption_ids=aids,
            subject_pb=sub_pb,
            subject_bps=sub_bps,
            subject_roe=subject_roe,
            subject_raw_close=spot,
            common_equity=float(ce),
            diluted_shares=float(shares),
            peer_field=PEER_FIELD_PB_COMMON,
            peer_n_included=peer_report.n_included,
            peer_n_excluded=peer_report.n_excluded,
            peer_min_count=peer_min_count,
            peer_median_pb=agg.median,
            peer_multiple=float(agg.multiple),
            relative_equity_value=None,
            relative_vps=None,
            rim_vps_crosscheck=rim_vps_crosscheck,
            shared_book_math_note=SHARED_BOOK_NOTE,
            peer_set=peer_report.model_dump(mode="json"),
            aggregate=agg.model_dump(mode="json"),
            detail=valued.invalid_reason or "",
        )

    return PbRoeReport(
        ok=True,
        status="VALID",
        ineligible_reason=None,
        flags=sorted(set(flags)),
        assumption_ids=aids,
        subject_pb=sub_pb,
        subject_bps=sub_bps,
        subject_roe=subject_roe,
        subject_raw_close=spot,
        common_equity=float(ce),
        diluted_shares=float(shares),
        peer_field=PEER_FIELD_PB_COMMON,
        peer_n_included=peer_report.n_included,
        peer_n_excluded=peer_report.n_excluded,
        peer_min_count=peer_min_count,
        peer_median_pb=agg.median,
        peer_multiple=float(agg.multiple),
        relative_equity_value=valued.equity_value,
        relative_vps=valued.value_per_share,
        rim_vps_crosscheck=rim_vps_crosscheck,
        shared_book_math_note=SHARED_BOOK_NOTE,
        peer_set=peer_report.model_dump(mode="json"),
        aggregate=agg.model_dump(mode="json"),
        detail=f"peer_median_pb={agg.multiple}; relative_vps={valued.value_per_share}",
    )


def make_pb_common_peer(
    *,
    subject_instrument_id: str,
    peer_instrument_id: str,
    pb: float,
    published_at: datetime,
    metric_timestamp: datetime | None = None,
    source_id: str = "test_peer_pb_common",
) -> PeerObservation:
    """Helper for tests / callers that already computed peer pb_common."""
    from vms.schemas.observations import QualityStatus

    return PeerObservation(
        subject_instrument_id=subject_instrument_id,
        peer_instrument_id=peer_instrument_id,
        published_at=published_at,
        field_name=PEER_FIELD_PB_COMMON,
        value=float(pb),
        currency="CNY",
        unit_scale="unit",
        metric_timestamp=metric_timestamp or published_at,
        source_id=source_id,
        quality_status=QualityStatus.OBSERVED,
    )
