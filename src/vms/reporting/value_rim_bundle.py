"""R1: real A-share FINANCIAL_INSTITUTION → residual income via PIT bridge (NOT investment advice).

Leaves legacy industrial FCFF ``industry.unsupported`` intact. Emits rim_inputs,
profile, route eligibility, and a single residual_income MethodResult.
Label always INVESTMENT_VALUE_NOT_ESTABLISHED.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data.io import LoadResult
from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.protocol import ValuationContext
from vms.methods.rim.from_snapshot import (
    BOOK_EQUITY_TE_RULE,
    RimBridgeError,
    features_from_snapshot,
    rim_inputs_from_snapshot,
)
from vms.profiles import classify_profile
from vms.quality.report import DataQualityReport, GateError, QualityState, assess, gate
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.router import route_methods
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import ClaimStatus, MethodEligibilityStatus, ProfileLabel, ValuationTarget

VALUE_RIM_STATUS = "VALUE_RIM_BANK_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value


class ValueRimBundleError(ValueError):
    pass


def build_value_rim_bundle(
    *,
    out_dir: str | Path,
    load: LoadResult,
    input_dir: str | Path,
    instrument_id: str,
    as_of: datetime,
    as_of_note: str,
    loaded: LoadedConfig,
    mode: Literal["production", "exploratory"] = "exploratory",
    override_reason: str | None = None,
    years: int | None = None,
    zeros_explicit: bool = True,
    target: ValuationTarget | None = None,
) -> dict[str, Any]:
    """Assess PIT → classify → bridge rim_inputs → route → run residual_income only."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = loaded.config
    tgt = target or ValuationTarget.FUNDAMENTAL_VALUE_CURRENT

    snap, report = assess(
        load, instrument_id=instrument_id, as_of=as_of, cfg=cfg.quality,
        mode=mode, override_reason=override_reason,
    )
    try:
        gate(report)
    except GateError:
        # still write quality artifacts then re-raise for CLI exit mapping
        stamp = ArtifactStamp(run_id=content_run_id(
            kind="value-rim", instrument=instrument_id, as_of=as_of.isoformat(),
            mode=mode, override=override_reason,
        ))
        write_artifact(out, "data_quality_report.json", report.model_dump(mode="json"), stamp)
        raise

    feats = features_from_snapshot(snap)
    profile = classify_profile(feats)
    if profile.primary_profile is ProfileLabel.MATURE_OPERATING:
        raise ValueRimBundleError(
            f"refusing RIM bridge: primary_profile=MATURE_OPERATING "
            f"(expected FINANCIAL_INSTITUTION for RIM path); notes={profile.notes}"
        )

    try:
        bridge = rim_inputs_from_snapshot(
            snap, loaded=loaded, years=years, zeros_explicit=zeros_explicit,
        )
    except RimBridgeError as e:
        raise ValueRimBundleError(str(e)) from e

    registry = build_registry_from_config(loaded.method_registry)
    available = frozenset({
        "total_equity", "parent_net_income", "dividends_paid", "revenue",
        "total_assets", "total_liabilities", "ebit", "cash_flow_from_operations",
        "capex", "interest_bearing_debt", "cash",
    })
    route = route_methods(
        registry=registry,
        profile=profile,
        target=tgt,
        available_fields=available,
        data_quality_blocked=(report.status is QualityState.BLOCKED),
        attempt_value_paths=False,
        context_loaded=loaded,
        rim_inputs=bridge.rim_inputs if bridge.ok else {},
        subject_metrics={
            "total_equity": (bridge.rim_inputs or {}).get("book_equity_0"),
            "parent_net_income": bridge.last_fy_ni,
        },
    )
    by_id = {e.method_id: e for e in route.eligibility}
    route_rel = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.RELATIVE_VALUE_CURRENT,
        available_fields=available,
        data_quality_blocked=(report.status is QualityState.BLOCKED),
        attempt_value_paths=False,
        context_loaded=loaded,
    )
    by_rel = {e.method_id: e for e in route_rel.eligibility}
    industrial = {
        "fcff_dcf_eligible": bool(by_id.get("fcff_dcf") and by_id["fcff_dcf"].eligible),
        "ev_ebitda_eligible": bool(by_rel.get("ev_ebitda") and by_rel["ev_ebitda"].eligible),
        "note": "industrial FCFF/EV EBITDA remain disabled for FINANCIAL_INSTITUTION; "
                "legacy industry.unsupported untouched",
    }

    method_result = None
    rim_status = "INELIGIBLE"
    equity_value = None
    vps = None
    result_flags: list[str] = list(bridge.flags)
    if bridge.ok:
        plugin = registry.plugin("residual_income")
        if plugin is None:
            raise ValueRimBundleError("residual_income plugin not bound in registry")
        ctx = ValuationContext(
            instrument_id=instrument_id,
            as_of=as_of.isoformat(),
            target=tgt,
            profile=profile,
            available_fields=available,
            data_quality_blocked=(report.status is QualityState.BLOCKED),
            loaded=loaded,
            rim_inputs=dict(bridge.rim_inputs),
            subject_metrics={
                "total_equity": bridge.rim_inputs["book_equity_0"],
                "parent_net_income": bridge.last_fy_ni,
            },
        )
        method_result = plugin.value_paths(
            ctx, None,
            MethodConfig(method_id="residual_income", assumptions=dict(bridge.rim_inputs)),
        )
        rim_status = method_result.status.value
        if method_result.status is MethodEligibilityStatus.VALID and method_result.values:
            equity_value = method_result.values.get("equity_value")
            vps = method_result.values.get("value_per_share")
            result_flags = sorted(set(result_flags) | set(method_result.diagnostics.get("flags") or []))
        elif method_result.diagnostics.get("flags"):
            result_flags = sorted(set(result_flags) | set(method_result.diagnostics["flags"]))
    else:
        rim_status = "INELIGIBLE"
        result_flags = sorted(set(result_flags) | {bridge.ineligible_reason or "BRIDGE_INELIGIBLE"})

    stamp = ArtifactStamp(run_id=content_run_id(
        kind="value-rim", instrument=instrument_id, as_of=as_of.isoformat(),
        data=sha256_of({"n_fin": len(load.financial), "n_mkt": len(load.market)}),
        config=sha256_of(cfg.model_dump(mode="json")),
        mode=mode, override=override_reason, years=years or cfg.projection.default_years,
        zeros_explicit=zeros_explicit,
    ))

    write_artifact(out, "data_manifest.json", {
        "input_dir": str(Path(input_dir).resolve()),
        "instrument_id": instrument_id,
        "as_of": as_of.isoformat(),
        "as_of_interpretation": as_of_note,
        "mode": mode,
        "override_reason": override_reason,
        "pit_complete": snap.pit_complete,
        "quality_status": report.status.value,
        "te_rule": BOOK_EQUITY_TE_RULE,
    }, stamp)
    write_artifact(out, "data_quality_report.json", report.model_dump(mode="json"), stamp)
    write_artifact(out, "pit_snapshot.json", snap.model_dump(mode="json"), stamp)
    write_artifact(out, "profile_report.json", profile.model_dump(mode="json"), stamp)
    write_artifact(out, "rim_bridge.json", bridge.model_dump(mode="json"), stamp)
    write_artifact(out, "rim_inputs.json", bridge.rim_inputs, stamp)
    write_artifact(out, "route_report.json", route.model_dump(mode="json"), stamp)
    if method_result is not None:
        write_artifact(out, "method_result.json", method_result.model_dump(mode="json"), stamp)
    else:
        write_artifact(out, "method_result.json", {
            "method_id": "residual_income",
            "status": rim_status,
            "reason_codes": [bridge.ineligible_reason] if bridge.ineligible_reason else [],
            "detail": bridge.detail,
            "values": {},
            "diagnostics": {"flags": result_flags, "ev_bridge_applied": False},
        }, stamp)

    summary = {
        "status": VALUE_RIM_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "run_id": stamp.run_id,
        "instrument_id": instrument_id,
        "as_of": as_of.isoformat(),
        "mode": mode,
        "override_reason": override_reason,
        "profile_primary": profile.primary_profile.value,
        "profile_low_confidence": profile.low_confidence,
        "profile_confidence": profile.confidence,
        "rim_status": rim_status,
        "bridge_ok": bridge.ok,
        "book_equity_0": (bridge.rim_inputs or {}).get("book_equity_0"),
        "book_equity_year": bridge.book_equity_year,
        "te_rule": BOOK_EQUITY_TE_RULE,
        "ni_policy": bridge.ni_policy,
        "last_fy_ni": bridge.last_fy_ni,
        "years": years or cfg.projection.default_years,
        "cost_of_equity": (bridge.rim_inputs or {}).get("cost_of_equity"),
        "terminal_growth": (bridge.rim_inputs or {}).get("terminal_growth"),
        "equity_value": None if equity_value is None else (
            equity_value.get("mean") if isinstance(equity_value, dict) else equity_value
        ),
        "value_per_share": None if vps is None else (
            vps.get("mean") if isinstance(vps, dict) else vps
        ),
        "ev_bridge_applied": False,
        "ensemble": None,
        "flags": result_flags,
        "assumption_labels": list(bridge.assumption_labels),
        "industrial_fcff_disabled": industrial,
        "residual_income_eligible": bool(by_id.get("residual_income") and by_id["residual_income"].eligible),
        "investment_value": INVESTMENT_LABEL,
        "pit_complete": snap.pit_complete,
        "quality_status": report.status.value,
        "note": (
            "Engineering smoke: real PIT→RIM bridge. ke/g/NI are ASSUMPTIONs; "
            "PIT may be incomplete; not an investment conclusion."
        ),
    }
    write_artifact(out, "value_rim_summary.json", summary, stamp)
    _write_run_report(out / "RUN_REPORT.md", summary, bridge_detail=bridge.detail)
    return summary


def _write_run_report(path: Path, summary: dict[str, Any], *, bridge_detail: str) -> None:
    lines = [
        f"# Exploratory value-rim — {summary['instrument_id']}",
        "",
        f"**as_of**: `{summary['as_of']}`  ",
        f"**mode**: {summary['mode']}  ",
        f"**label**: `{summary['investment_value']}` (engineering smoke only；非投资结论)",
        "",
        "## Outcome",
        f"- profile_primary: **{summary['profile_primary']}** "
        f"(low_confidence={summary['profile_low_confidence']})",
        f"- rim_status: **{summary['rim_status']}**",
        f"- book_equity_0 / year: {summary.get('book_equity_0')} / {summary.get('book_equity_year')}",
        f"- last_fy_ni (P1 constant): {summary.get('last_fy_ni')}",
        f"- ke / g (ASSUMPTION): {summary.get('cost_of_equity')} / {summary.get('terminal_growth')}",
        f"- equity_value: {summary.get('equity_value')}",
        f"- value_per_share: {summary.get('value_per_share')}",
        f"- ev_bridge_applied: {summary.get('ev_bridge_applied')}",
        f"- ensemble: {summary.get('ensemble')}",
        f"- flags: {', '.join(summary.get('flags') or [])}",
        f"- industrial FCFF disabled: {summary.get('industrial_fcff_disabled')}",
        f"- pit_complete / quality: {summary.get('pit_complete')} / {summary.get('quality_status')}",
        "",
        "## Bridge detail",
        f"```\n{bridge_detail}\n```",
        "",
        "## Honesty",
        "- Legacy `vms project` / `vms value` remain `UNSUPPORTED_PROFILE` for industry.unsupported names.",
        "- NI / dividends / ke / g are ASSUMPTIONs; OCI/net_issuance zeros are explicit.",
        "- No returns, no ensemble, no investment-value claim.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def dump_value_rim_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
