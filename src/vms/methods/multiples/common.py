"""Shared helpers for Phase-5 multiple method plugins."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vms.methods.cash_flow.common import append_gate, base_eligibility, flag_exclusion
from vms.methods.eligibility import EligibilityResult, GateReason
from vms.methods.multiples.aggregate import AggregateResult, aggregate_multiples
from vms.methods.multiples.apply import MultipleValueResult, apply_equity_multiple, apply_ev_multiple
from vms.methods.multiples.cycle import CycleNormalizationReport, assess_cycle_normalization
from vms.methods.multiples.definitions import MetricDefinition, get_definition
from vms.methods.multiples.denominators import check_denominator, subject_metric
from vms.methods.multiples.midcycle import MidCycleConfidence, estimate_mid_cycle_denominator
from vms.methods.multiples.peers import (
    PeerAttributes,
    PeerFilterConfig,
    PeerSetReport,
    build_peer_set,
)
from vms.methods.protocol import MethodConfig, MethodResult, ValuationContext
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry, ProfileFlag, ProfileLabel
from vms.schemas.observations import PeerObservation


def parse_as_of_dt(context: ValuationContext) -> datetime:
    raw = context.as_of
    if isinstance(raw, datetime):
        return raw
    # ISO date or datetime
    s = str(raw)
    if len(s) == 10:
        from vms.pit.asof import parse_as_of
        return parse_as_of(s)[0]
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def subject_from_context(context: ValuationContext) -> dict[str, Any]:
    """Subject fundamentals attached on ValuationContext.subject_metrics (Phase 5)."""
    sm = getattr(context, "subject_metrics", None) or {}
    return dict(sm)


def peers_from_context(context: ValuationContext) -> list[PeerObservation]:
    rows = getattr(context, "peer_observations", None) or ()
    return list(rows)


def multiples_cfg(context: ValuationContext) -> dict[str, Any]:
    loaded = context.loaded
    if loaded is None:
        return {}
    cfg = getattr(loaded.config, "multiples", None)
    if cfg is None:
        return {}
    return cfg.model_dump(mode="json") if hasattr(cfg, "model_dump") else dict(cfg)


def peer_min_from_entry(entry: MethodRegistryEntry, cfg: dict[str, Any]) -> int:
    qm = entry.quality_minimums or {}
    if "peer_min_count" in qm:
        try:
            return int(qm["peer_min_count"])
        except (TypeError, ValueError):
            pass
    return int(cfg.get("peer_min_count", 5))


def check_peer_count_gate(context: ValuationContext, entry: MethodRegistryEntry) -> GateReason:
    cfg = multiples_cfg(context)
    need = peer_min_from_entry(entry, cfg)
    # soft at eligibility if peers not yet attached; hard at value_paths
    n = int(context.peer_count or 0)
    if n <= 0 and peers_from_context(context):
        n = len({p.peer_instrument_id for p in peers_from_context(context)})
    passed = n >= need or n == 0  # n==0 deferred to value time with structured PEER_DATA_INSUFFICIENT
    return GateReason(
        code="PEER_COUNT_HINT",
        detail=f"peer_count={n}; peer_min_count={need}",
        passed=True if n == 0 else n >= need,
    )


def eligibility_with_denominator_hint(
    entry: MethodRegistryEntry,
    context: ValuationContext,
    definition: MetricDefinition,
) -> EligibilityResult:
    elig = base_eligibility(entry, context)
    elig = flag_exclusion(entry, context, elig)
    # Exclusion strings like negative_or_near_zero_earnings
    subject = subject_from_context(context)
    denom = subject_metric(subject, definition.denominator_field)
    cfg = multiples_cfg(context)
    eps = float(cfg.get("near_zero_eps", 1e-6))
    if denom is not None:
        dec = check_denominator(field=definition.denominator_field, value=denom, near_zero_eps=eps)
        elig = append_gate(elig, GateReason(
            code=dec.code if not dec.ok else "DENOMINATOR_GATE",
            detail=dec.detail,
            passed=dec.ok,
        ))
    else:
        elig = append_gate(elig, GateReason(
            code="DENOMINATOR_GATE",
            detail=f"{definition.denominator_field} not on context yet; re-checked at value_paths",
            passed=True,
        ))
    # Earnings instability flag for P/E
    if definition.method_id == "pe":
        if any(f is ProfileFlag.EARNINGS_NEGATIVE_OR_UNSTABLE for f in context.profile.flags):
            elig = append_gate(elig, GateReason(
                code="EARNINGS_QUALITY_FLAG",
                detail="EARNINGS_NEGATIVE_OR_UNSTABLE present",
                passed=False,
            ))
    peer_gate = check_peer_count_gate(context, entry)
    # Don't hard-fail eligibility solely on peer hint when count unknown; soft note
    if peer_gate.detail.startswith("peer_count=0"):
        elig = append_gate(elig, peer_gate.model_copy(update={"passed": True}))
    else:
        elig = append_gate(elig, peer_gate)
    return elig


def run_multiple_method(
    *,
    entry: MethodRegistryEntry,
    context: ValuationContext,
    config: MethodConfig,
) -> MethodResult:
    definition = get_definition(entry.method_id)
    elig = eligibility_with_denominator_hint(entry, context, definition)
    if not elig.eligible:
        codes = [r.code for r in elig.reasons if not r.passed]
        return MethodResult(
            method_id=entry.method_id,
            status=MethodEligibilityStatus.INELIGIBLE,
            reason_codes=codes or ["HARD_GATE_FAILED"],
            detail="; ".join(r.detail for r in elig.reasons if not r.passed),
            output_basis=list(entry.output_basis),
        )

    cfg = multiples_cfg(context)
    assumptions = dict(config.assumptions or {})
    # Allow per-call overrides
    for k in ("aggregator", "winsor_pct", "trim_pct", "peer_min_count", "near_zero_eps",
              "mid_cycle_denominator"):
        if k in assumptions:
            cfg[k] = assumptions[k]

    subject = subject_from_context(context)
    # Allow assumptions to inject subject metrics for offline fixtures
    for k, v in (assumptions.get("subject_metrics") or {}).items():
        subject.setdefault(k, v)

    denom_field = definition.denominator_field
    trailing = subject_metric(subject, denom_field)
    # Optional ebitda construction
    if denom_field == "ebitda" and trailing is None:
        ebit = subject_metric(subject, "ebit")
        da = subject_metric(subject, "depreciation_amortization")
        if ebit is not None and da is not None:
            trailing = ebit + da
            subject["ebitda"] = trailing

    mid = assumptions.get("mid_cycle_denominator")
    if mid is None:
        mid = subject_metric(subject, f"mid_cycle_{denom_field}")

    midcycle_est = None
    # Skeleton estimator: only auto-call for cyclical profiles when mid_* not supplied.
    # Non-cyclical must not auto-normalize / claim mid-cycle (SPEC cyc-midcycle-skel).
    cyclical = False
    if context.profile is not None:
        cyclical = (
            context.profile.primary_profile is ProfileLabel.CYCLICAL_OPERATING
            or any(f is ProfileFlag.HIGH_CYCLICALITY for f in context.profile.flags)
        )
    if mid is None and cyclical:
        series = assumptions.get("pit_denominator_series")
        if series is None:
            series = subject.get(f"pit_{denom_field}_series")
        if series is None:
            series = subject.get("pit_denominator_series")
        # Call even when series is None → honest None + LOW diagnostics (no invent).
        midcycle_est = estimate_mid_cycle_denominator(
            series,
            as_of=context.as_of,
            sector_prior=assumptions.get("sector_prior_mid_cycle"),
            use_sector_prior_stub=bool(assumptions.get("use_sector_prior_stub")),
        )
        # Inject into assess only on HIGH + finite denom; LOW/None → trailing flags.
        if (
            midcycle_est.confidence is MidCycleConfidence.HIGH
            and midcycle_est.mid_cycle_denominator is not None
            and midcycle_est.mid_cycle_denominator > 0
        ):
            mid = midcycle_est.mid_cycle_denominator

    cycle = assess_cycle_normalization(
        context, trailing_denominator=trailing, mid_cycle_denominator=mid,
        method_id=definition.method_id,
    )
    denom_value = cycle.normalized_denominator if cycle.mid_cycle_available else trailing

    eps = float(cfg.get("near_zero_eps", 1e-6))
    dec = check_denominator(field=denom_field, value=denom_value, near_zero_eps=eps)
    if not dec.ok:
        return MethodResult(
            method_id=entry.method_id,
            status=MethodEligibilityStatus.INELIGIBLE,
            reason_codes=[dec.code, "INELIGIBLE_DENOMINATOR"],
            detail=dec.detail,
            output_basis=list(entry.output_basis),
            diagnostics={
                "denominator": dec.model_dump(mode="json"),
                "cycle": cycle.model_dump(mode="json"),
                **({"midcycle_estimate": midcycle_est.model_dump(mode="json")} if midcycle_est is not None else {}),
            },
        )

    as_of = parse_as_of_dt(context)
    peers = peers_from_context(context)
    # Optional peers injected via assumptions (already-built PeerObservation dicts not supported —
    # tests attach on context). Filter config:
    filt_raw = cfg.get("filters") or {}
    filters = PeerFilterConfig(**{k: v for k, v in filt_raw.items() if k in PeerFilterConfig.model_fields})
    subj_attrs_raw = assumptions.get("subject_attrs") or cfg.get("subject_attrs") or {}
    subject_attrs = PeerAttributes(**{k: v for k, v in subj_attrs_raw.items() if k in PeerAttributes.model_fields}) \
        if subj_attrs_raw else PeerAttributes(
            profile_label=context.profile.primary_profile.value if context.profile else None,
        )
    peer_attrs_raw = assumptions.get("peer_attrs") or {}
    peer_attrs = {
        pid: PeerAttributes(**{k: v for k, v in attrs.items() if k in PeerAttributes.model_fields})
        for pid, attrs in peer_attrs_raw.items()
    }

    peer_report: PeerSetReport = build_peer_set(
        subject_instrument_id=context.instrument_id,
        as_of=as_of,
        metric_field=definition.peer_field_name,
        peers=peers,
        subject_attrs=subject_attrs,
        peer_attrs=peer_attrs,
        filters=filters,
    )

    agg: AggregateResult = aggregate_multiples(
        peer_report.multiples,
        estimator=cfg.get("aggregator", "median"),
        winsor_pct=float(cfg.get("winsor_pct", 0.10)),
        trim_pct=float(cfg.get("trim_pct", 0.10)),
        peer_min_count=peer_min_from_entry(entry, cfg),
        peer_warn_count=int(cfg.get("peer_warn_count", 8)),
        max_dispersion_ratio=float(cfg.get("max_dispersion_ratio", 2.0)),
        shrink_prior=cfg.get("shrink_prior"),
        shrink_strength=float(cfg.get("shrink_strength", 0.0)),
    )
    if not agg.ok:
        status = MethodEligibilityStatus.INELIGIBLE
        if "HIGH_PEER_DISPERSION" in agg.flags and agg.multiple is not None:
            status = MethodEligibilityStatus.LOW_CONFIDENCE
        return MethodResult(
            method_id=entry.method_id,
            status=status if "PEER_DATA_INSUFFICIENT" in agg.flags else MethodEligibilityStatus.FAILED,
            reason_codes=["PEER_DATA_INSUFFICIENT"] if "PEER_DATA_INSUFFICIENT" in agg.flags else ["AGGREGATION_FAILED"],
            detail=agg.detail,
            output_basis=list(entry.output_basis),
            values={},
            diagnostics={
                "peer_set": peer_report.model_dump(mode="json"),
                "aggregate": agg.model_dump(mode="json"),
                "cycle": cycle.model_dump(mode="json"),
                "denominator": dec.model_dump(mode="json"),
                "metric_definition": definition.model_dump(mode="json"),
            },
        )

    shares = subject_metric(subject, "diluted_shares")
    if shares is None:
        shares = subject_metric(subject, "shares_outstanding")
    cash = subject_metric(subject, "cash") or 0.0
    debt = subject_metric(subject, "interest_bearing_debt") or 0.0
    lease = subject_metric(subject, "lease_debt_like") or float(
        getattr(getattr(getattr(context.loaded, "config", None), "valuation", None), "lease_debt_like", 0.0) or 0.0
    )
    minority = subject_metric(subject, "minority_interest_book")
    if minority is None and context.loaded is not None:
        minority = context.loaded.config.valuation.minority_interest_book
    if minority is None:
        minority = 0.0
    other = subject_metric(subject, "other_senior_claims")
    if other is None and context.loaded is not None:
        other = context.loaded.config.valuation.other_senior_claims
    if other is None:
        other = 0.0

    assert agg.multiple is not None and denom_value is not None
    if definition.applies_ev_bridge:
        if shares is None or shares <= 0:
            return MethodResult(
                method_id=entry.method_id,
                status=MethodEligibilityStatus.FAILED,
                reason_codes=["NONPOSITIVE_SHARES"],
                detail="EV methods require positive diluted_shares for bridge",
                output_basis=list(entry.output_basis),
                diagnostics={"peer_set": peer_report.model_dump(mode="json"), "aggregate": agg.model_dump(mode="json")},
            )
        valued: MultipleValueResult = apply_ev_multiple(
            definition=definition, multiple=agg.multiple, denominator=denom_value,
            cash=cash, debt=debt, lease_debt_like=lease, minority_interest_book=float(minority),
            other_senior_claims=float(other), diluted_shares=float(shares),
        )
    else:
        valued = apply_equity_multiple(
            definition=definition, multiple=agg.multiple, denominator=denom_value,
            diluted_shares=shares,
        )

    if not valued.valid:
        return MethodResult(
            method_id=entry.method_id,
            status=MethodEligibilityStatus.FAILED,
            reason_codes=[valued.invalid_reason or "VALUE_FAILED"],
            detail=valued.invalid_reason or "apply failed",
            output_basis=list(entry.output_basis),
            diagnostics={
                "peer_set": peer_report.model_dump(mode="json"),
                "aggregate": agg.model_dump(mode="json"),
                "valued": valued.model_dump(mode="json"),
            },
        )

    flags = sorted(set(valued.flags) | set(agg.flags) | set(cycle.flags) | set(dec.warnings))
    status = MethodEligibilityStatus.VALID
    if "CYCLE_ESTIMATE_LOW_CONFIDENCE" in flags or "SMALL_PEER_SAMPLE" in flags or "HIGH_PEER_DISPERSION" in flags:
        status = MethodEligibilityStatus.LOW_CONFIDENCE

    values = {
        "metric_definition": definition.model_dump(mode="json"),
        "multiple_used": valued.multiple_used,
        "denominator_field": valued.denominator_field,
        "denominator_value": valued.denominator_value,
        "claim_object": valued.claim_object,
        "value_claim": valued.value_claim,
        "enterprise_value": valued.enterprise_value,
        "equity_value": valued.equity_value,
        "value_per_share": valued.value_per_share,
        "diluted_shares": valued.diluted_shares,
        "ev_bridge_applied": valued.ev_bridge_applied,
        "bridge": valued.bridge,
        "formula": valued.formula,
        "peer_n": agg.n,
        "peer_median": agg.median,
        "aggregator": agg.estimator,
        "flags": flags,
    }
    return MethodResult(
        method_id=entry.method_id,
        status=status,
        reason_codes=[],
        detail=(
            f"{definition.display_name}: multiple={valued.multiple_used}; "
            f"n_peers={agg.n}; bridge={valued.ev_bridge_applied}; claim={valued.value_claim}"
        ),
        output_basis=list(entry.output_basis),
        values=values,
        diagnostics={
            "peer_set": peer_report.model_dump(mode="json"),
            "aggregate": agg.model_dump(mode="json"),
            "cycle": cycle.model_dump(mode="json"),
            "denominator": dec.model_dump(mode="json"),
            "assumptions": valued.assumptions,
            **({"midcycle_estimate": midcycle_est.model_dump(mode="json")} if midcycle_est is not None else {}),
        },
    )
