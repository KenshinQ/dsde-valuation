"""Run eligible Phase-5 relative-valuation methods via the router (no ensemble)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.cash_flow.run import MethodRunBundle
from vms.methods.protocol import MethodConfig, MethodResult, ValuationContext
from vms.methods.registry import MethodRegistry
from vms.profiles.report import ProfileReport
from vms.router.route import route_methods
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import ClaimStatus, MethodEligibilityStatus, ValuationTarget
from vms.schemas.observations import PeerObservation

PHASE5_MULTIPLE_METHODS = ("pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales")


class MultiplesRunBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: Any
    results: list[MethodResult] = Field(default_factory=list)
    eligible_run: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    investment_value: str = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    ensemble: None = None
    notes: str = ""
    peer_diagnostics: dict[str, Any] = Field(default_factory=dict)


def run_eligible_multiple_methods(
    *,
    registry: MethodRegistry,
    profile: ProfileReport,
    target: ValuationTarget,
    loaded: LoadedConfig,
    available_fields: frozenset[str] | set[str] | None = None,
    subject_metrics: dict[str, Any] | None = None,
    peer_observations: list[PeerObservation] | None = None,
    peer_count: int | None = None,
    data_quality_blocked: bool = False,
    method_assumptions: dict[str, dict[str, Any]] | None = None,
    as_of: str | None = None,
) -> MultiplesRunBundle:
    peers = peer_observations or []
    n_peers = peer_count if peer_count is not None else len({p.peer_instrument_id for p in peers})
    ctx = ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=as_of or profile.as_of,
        target=target,
        profile=profile,
        available_fields=frozenset(available_fields or ()),
        peer_count=n_peers,
        data_quality_blocked=data_quality_blocked,
        loaded=loaded,
        subject_metrics=dict(subject_metrics or {}),
        peer_observations=tuple(peers),
    )
    route = route_methods(
        registry=registry,
        profile=profile,
        target=target,
        available_fields=available_fields,
        peer_count=n_peers,
        data_quality_blocked=data_quality_blocked,
        attempt_value_paths=False,
        context_loaded=loaded,
    )
    assumptions = method_assumptions or {}
    results: list[MethodResult] = []
    eligible_run: list[str] = []
    skipped: list[str] = []
    peer_diagnostics: dict[str, Any] = {}

    for elig in route.eligibility:
        if elig.method_id not in PHASE5_MULTIPLE_METHODS:
            skipped.append(elig.method_id)
            continue
        plugin = registry.plugin(elig.method_id)
        if plugin is None:
            skipped.append(elig.method_id)
            continue
        cfg = MethodConfig(
            method_id=elig.method_id,
            assumptions=dict(assumptions.get(elig.method_id, {})),
        )
        result = plugin.value_paths(ctx, None, cfg)
        results.append(result)
        if result.diagnostics and "peer_set" in result.diagnostics:
            peer_diagnostics[elig.method_id] = result.diagnostics["peer_set"]
        if result.status in (MethodEligibilityStatus.VALID, MethodEligibilityStatus.LOW_CONFIDENCE) and result.values:
            eligible_run.append(elig.method_id)
        else:
            skipped.append(elig.method_id)

    notes = (
        f"ran={eligible_run}; skipped/ineligible={skipped}; "
        f"coverage={route.coverage_status}; ensemble=None (Phase 8); "
        f"claim=RELATIVE_VALUE (not intrinsic ensemble)"
    )
    return MultiplesRunBundle(
        route=route,
        results=results,
        eligible_run=eligible_run,
        skipped=skipped,
        notes=notes,
        peer_diagnostics=peer_diagnostics,
    )


def merge_cashflow_and_multiples(
    cashflow: MethodRunBundle,
    multiples: MultiplesRunBundle,
) -> MethodRunBundle:
    """Concatenate method results without blending (Phase 8 ensemble forbidden)."""
    return MethodRunBundle(
        route=multiples.route if multiples.eligible_run else cashflow.route,
        results=list(cashflow.results) + list(multiples.results),
        eligible_run=list(cashflow.eligible_run) + list(multiples.eligible_run),
        skipped=sorted(set(cashflow.skipped) | set(multiples.skipped)),
        notes=f"cashflow: {cashflow.notes} | multiples: {multiples.notes}",
    )
