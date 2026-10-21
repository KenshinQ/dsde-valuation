"""Run eligible Phase-4 cash-flow methods via the router (no ensemble / averaging)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.methods.protocol import MethodConfig, MethodResult, ValuationContext
from vms.methods.registry import MethodRegistry
from vms.profiles.report import ProfileReport
from vms.router.route import RouteReport, route_methods
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import ClaimStatus, MethodEligibilityStatus, ValuationTarget
from vms.statements.paths import FinancialPathBundle

PHASE4_CASHFLOW_METHODS = ("fcff_dcf", "fcfe_dcf", "ddm")


class MethodRunBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: RouteReport
    results: list[MethodResult] = Field(default_factory=list)
    eligible_run: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    investment_value: str = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    ensemble: None = None  # Phase 8 only
    notes: str = ""


def run_eligible_cashflow_methods(
    *,
    registry: MethodRegistry,
    profile: ProfileReport,
    target: ValuationTarget,
    financial_paths: FinancialPathBundle,
    loaded: LoadedConfig,
    available_fields: frozenset[str] | set[str] | None = None,
    peer_count: int = 0,
    data_quality_blocked: bool = False,
    method_assumptions: dict[str, dict[str, Any]] | None = None,
) -> MethodRunBundle:
    """Route, then run only eligible *implemented* methods. Never averages results."""
    ctx = ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=target,
        profile=profile,
        available_fields=frozenset(available_fields or ()),
        peer_count=peer_count,
        data_quality_blocked=data_quality_blocked,
        loaded=loaded,
    )
    route = route_methods(
        registry=registry,
        profile=profile,
        target=target,
        available_fields=available_fields,
        peer_count=peer_count,
        data_quality_blocked=data_quality_blocked,
        attempt_value_paths=False,
        context_loaded=loaded,
    )
    assumptions = method_assumptions or {}
    results: list[MethodResult] = []
    eligible_run: list[str] = []
    skipped: list[str] = []

    for elig in route.eligibility:
        if elig.method_id not in PHASE4_CASHFLOW_METHODS:
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
        # Always invoke plugin for structured ineligibility (e.g. DDM payout) —
        # plugin re-checks gates and never fabricates values when ineligible.
        result = plugin.value_paths(ctx, financial_paths, cfg)
        results.append(result)
        if result.status is MethodEligibilityStatus.VALID and result.values:
            eligible_run.append(elig.method_id)
        else:
            skipped.append(elig.method_id)

    notes = (
        f"ran={eligible_run}; skipped/ineligible={skipped}; "
        f"coverage={route.coverage_status}; ensemble=None (Phase 8)"
    )
    return MethodRunBundle(
        route=route,
        results=results,
        eligible_run=eligible_run,
        skipped=skipped,
        notes=notes,
    )
