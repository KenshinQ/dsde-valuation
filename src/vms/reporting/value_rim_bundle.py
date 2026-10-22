"""R1/R2: real A-share FINANCIAL_INSTITUTION → residual income via PIT bridge.

Leaves legacy industrial FCFF ``industry.unsupported`` intact.
R2a: common-equity basis + sharebonus DPS + EPS common NI.
R2b: P2 ROE distribution + ke grid (no ensemble).
R2c: P/B-ROE relative sidecar (pb_common, raw close; PEER_SCARCITY ok).
R2d: Track B returns via own-hist common P/B exit (UNAVAILABLE if hist < 12).
Label always INVESTMENT_VALUE_NOT_ESTABLISHED.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data.io import LoadResult
from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.protocol import ValuationContext
from vms.methods.rim.distribution import DEFAULT_KE_GRID, run_rim_distribution
from vms.methods.rim.pb_roe import run_pb_roe_relative
from vms.methods.rim.track_b_exit import run_rim_track_b
from vms.methods.rim.from_snapshot import (
    BOOK_EQUITY_COMMON_RULE,
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
    equity_basis: Literal["common", "total"] = "common",
    run_distribution: bool = True,
    n_paths: int | None = None,
    seed: int | None = None,
    ke_grid: Sequence[float] | None = None,
    run_pb_roe: bool = True,
    run_track_b: bool = True,
    peer_min_count: int = 5,
    track_b_horizons: Sequence[int] | None = None,
    track_b_paths: int | None = None,
) -> dict[str, Any]:
    """Assess PIT → classify → bridge rim_inputs → route → residual_income (+ optional P2 grid)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = loaded.config
    tgt = target or ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    if n_paths is None:
        n_paths = int(getattr(cfg.monte_carlo, "default_paths", 200) or 200)
    if seed is None:
        seed = int(getattr(cfg.monte_carlo, "default_seed", 42) or 42)
    kes = list(ke_grid) if ke_grid is not None else list(DEFAULT_KE_GRID)

    snap, report = assess(
        load, instrument_id=instrument_id, as_of=as_of, cfg=cfg.quality,
        mode=mode, override_reason=override_reason,
    )
    try:
        gate(report)
    except GateError:
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
            equity_basis=equity_basis,
        )
    except RimBridgeError as e:
        raise ValueRimBundleError(str(e)) from e

    registry = build_registry_from_config(loaded.method_registry)
    available = frozenset({
        "total_equity", "parent_net_income", "dividends_paid", "revenue",
        "total_assets", "total_liabilities", "ebit", "cash_flow_from_operations",
        "capex", "interest_bearing_debt", "cash",
        "other_equity_instruments", "minority_interest", "basic_eps",
        "other_comprehensive_income", "goodwill", "interest_income",
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

    dist_payload: dict[str, Any] | None = None
    if bridge.ok and run_distribution and equity_basis == "common":
        dps = bridge.last_fy_dps
        shares = bridge.rim_inputs.get("diluted_shares")
        if dps is None or shares is None:
            result_flags = sorted(set(result_flags) | {"DISTRIBUTION_SKIPPED_MISSING_DPS_OR_SHARES"})
        else:
            oci_const = None
            oci_seq = bridge.rim_inputs.get("oci")
            if isinstance(oci_seq, list) and oci_seq:
                oci_const = float(oci_seq[0])
            dist = run_rim_distribution(
                snap,
                loaded=loaded,
                book_equity_0=float(bridge.rim_inputs["book_equity_0"]),
                book_equity_year=int(bridge.book_equity_year or 0),
                dps=float(dps),
                diluted_shares=float(shares),
                years=years or cfg.projection.default_years,
                n_paths=int(n_paths),
                seed=int(seed),
                ke_grid=kes,
                zeros_explicit=zeros_explicit,
                oci_constant=oci_const,
                p1_common_ni=bridge.last_fy_ni,
                goodwill=bridge.goodwill_0,
            )
            dist_payload = {
                "ok": dist.ok,
                "ineligible_reason": dist.ineligible_reason,
                "flags": dist.flags,
                "assumption_ids": dist.assumption_ids,
                "seed": dist.seed,
                "n_paths": dist.n_paths,
                "years": dist.years,
                "roe_history_years": None if dist.roe_history is None else dist.roe_history.years,
                "roe_history": None if dist.roe_history is None else dist.roe_history.roe,
                "ke_grid": [
                    {
                        "cost_of_equity": c.cost_of_equity,
                        "n_valid": c.n_valid,
                        "n_invalid": c.n_invalid,
                        "equity_p05": c.equity_p05,
                        "equity_p50": c.equity_p50,
                        "equity_p95": c.equity_p95,
                        "vps_p05": c.vps_p05,
                        "vps_p50": c.vps_p50,
                        "vps_p95": c.vps_p95,
                        "vps_mean": c.vps_mean,
                    }
                    for c in dist.ke_grid
                ],
                "p1_control": dist.p1_control,
                "detail": dist.detail,
                "ni_policy_primary": "P2_CONSTANT_ROE_TIMES_BEGINNING_COMMON_EQUITY",
                "ensemble": None,
            }
            result_flags = sorted(set(result_flags) | set(dist.flags))

    pb_roe_payload: dict[str, Any] | None = None
    track_b_payload: dict[str, Any] | None = None
    if bridge.ok and equity_basis == "common":
        rim_xcheck = None
        if dist_payload and dist_payload.get("ke_grid"):
            rim_xcheck = (dist_payload["ke_grid"][0] or {}).get("vps_p50")
        elif vps is not None:
            rim_xcheck = vps.get("mean") if isinstance(vps, dict) else vps
        if run_pb_roe:
            pb_rep = run_pb_roe_relative(
                snap,
                bridge=bridge,
                peer_observations=list(load.peers or []),
                rim_vps_crosscheck=None if rim_xcheck is None else float(rim_xcheck),
                peer_min_count=int(peer_min_count),
                zeros_explicit=zeros_explicit,
            )
            pb_roe_payload = pb_rep.as_dict()
            result_flags = sorted(set(result_flags) | set(pb_rep.flags))
            if pb_rep.assumption_ids:
                # assumption_labels stay bridge-primary; ids recorded in sidecar
                pass
        if run_track_b:
            tb_paths = int(track_b_paths) if track_b_paths is not None else int(n_paths)
            tb_h = list(track_b_horizons) if track_b_horizons is not None else [1, 3]
            oci_const = None
            oci_seq = (bridge.rim_inputs or {}).get("oci")
            if isinstance(oci_seq, list) and oci_seq:
                oci_const = float(oci_seq[0])
            tb = run_rim_track_b(
                snap,
                bridge=bridge,
                loaded=loaded,
                years=years or cfg.projection.default_years,
                n_paths=tb_paths,
                seed=int(seed),
                horizons_years=tb_h,
                zeros_explicit=zeros_explicit,
                oci_constant=oci_const,
            )
            track_b_payload = tb.as_dict()
            result_flags = sorted(set(result_flags) | set(tb.flags))

    stamp = ArtifactStamp(run_id=content_run_id(
        kind="value-rim", instrument=instrument_id, as_of=as_of.isoformat(),
        data=sha256_of({"n_fin": len(load.financial), "n_mkt": len(load.market)}),
        config=sha256_of(cfg.model_dump(mode="json")),
        mode=mode, override=override_reason, years=years or cfg.projection.default_years,
        zeros_explicit=zeros_explicit, equity_basis=equity_basis, seed=seed, n_paths=n_paths,
    ))

    te_rule = BOOK_EQUITY_COMMON_RULE if equity_basis == "common" else BOOK_EQUITY_TE_RULE
    write_artifact(out, "data_manifest.json", {
        "input_dir": str(Path(input_dir).resolve()),
        "instrument_id": instrument_id,
        "as_of": as_of.isoformat(),
        "as_of_interpretation": as_of_note,
        "mode": mode,
        "override_reason": override_reason,
        "pit_complete": snap.pit_complete,
        "quality_status": report.status.value,
        "te_rule": te_rule,
        "equity_basis": equity_basis,
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
    if dist_payload is not None:
        write_artifact(out, "rim_distribution.json", dist_payload, stamp)
    if pb_roe_payload is not None:
        write_artifact(out, "rim_pb_roe.json", pb_roe_payload, stamp)
    if track_b_payload is not None:
        write_artifact(out, "rim_track_b.json", track_b_payload, stamp)

    primary_cell = None
    if dist_payload and dist_payload.get("ke_grid"):
        primary_cell = dist_payload["ke_grid"][0]

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
        "equity_basis": equity_basis,
        "book_equity_0": (bridge.rim_inputs or {}).get("book_equity_0"),
        "common_equity_0": bridge.common_equity_0,
        "total_equity_0": bridge.total_equity_0,
        "goodwill_0": bridge.goodwill_0,
        "tangible_common_equity_0": bridge.tangible_common_equity_0,
        "book_equity_year": bridge.book_equity_year,
        "te_rule": te_rule,
        "ni_policy": bridge.ni_policy,
        "last_fy_ni": bridge.last_fy_ni,
        "last_fy_dps": bridge.last_fy_dps,
        "last_fy_dividends": bridge.last_fy_dividends,
        "years": years or cfg.projection.default_years,
        "cost_of_equity": (bridge.rim_inputs or {}).get("cost_of_equity"),
        "terminal_growth": (bridge.rim_inputs or {}).get("terminal_growth"),
        "equity_value_p1_point": None if equity_value is None else (
            equity_value.get("mean") if isinstance(equity_value, dict) else equity_value
        ),
        "value_per_share_p1_point": None if vps is None else (
            vps.get("mean") if isinstance(vps, dict) else vps
        ),
        "distribution": {
            "seed": seed,
            "n_paths": n_paths,
            "ke_grid": None if dist_payload is None else dist_payload.get("ke_grid"),
            "vps_p05": None if primary_cell is None else primary_cell.get("vps_p05"),
            "vps_p50": None if primary_cell is None else primary_cell.get("vps_p50"),
            "vps_p95": None if primary_cell is None else primary_cell.get("vps_p95"),
            "p1_control_vps": None if dist_payload is None else (dist_payload.get("p1_control") or {}).get("value_per_share"),
            "ni_policy_primary": "P2" if dist_payload else None,
        } if run_distribution else None,
        "ev_bridge_applied": False,
        "ensemble": None,
        "pb_roe": None if pb_roe_payload is None else {
            "status": pb_roe_payload.get("status"),
            "ok": pb_roe_payload.get("ok"),
            "ineligible_reason": pb_roe_payload.get("ineligible_reason"),
            "subject_pb": pb_roe_payload.get("subject_pb"),
            "subject_roe": pb_roe_payload.get("subject_roe"),
            "peer_n_included": pb_roe_payload.get("peer_n_included"),
            "peer_median_pb": pb_roe_payload.get("peer_median_pb"),
            "relative_vps": pb_roe_payload.get("relative_vps"),
            "rim_vps_crosscheck": pb_roe_payload.get("rim_vps_crosscheck"),
            "shared_book_math_note": pb_roe_payload.get("shared_book_math_note"),
        },
        "track_b": None if track_b_payload is None else {
            "status": track_b_payload.get("status"),
            "ok": track_b_payload.get("ok"),
            "ineligible_reason": track_b_payload.get("ineligible_reason"),
            "hist_pb_n": (track_b_payload.get("hist_pb") or {}).get("n"),
            "pb_center_used": track_b_payload.get("pb_center_used"),
            "spot_price": track_b_payload.get("spot_price"),
            "n_book_paths": track_b_payload.get("n_book_paths"),
            "exit_n_valid": None if not track_b_payload.get("exit_prices") else track_b_payload["exit_prices"].get("n_valid"),
        },
        "flags": result_flags,
        "assumption_labels": list(bridge.assumption_labels),
        "industrial_fcff_disabled": industrial,
        "residual_income_eligible": bool(by_id.get("residual_income") and by_id["residual_income"].eligible),
        "investment_value": INVESTMENT_LABEL,
        "pit_complete": snap.pit_complete,
        "quality_status": report.status.value,
        "note": (
            "Engineering smoke: real PIT→RIM bridge (R2a/b + R2c P/B-ROE sidecar + R2d Track B). "
            "ke/g/NI/ROE are ASSUMPTIONs; PIT may be incomplete; not an investment conclusion."
        ),
    }
    # backward-compatible aliases used by R1 reports
    summary["equity_value"] = summary["equity_value_p1_point"]
    summary["value_per_share"] = (
        summary["distribution"]["vps_p50"]
        if summary.get("distribution") and summary["distribution"].get("vps_p50") is not None
        else summary["value_per_share_p1_point"]
    )
    write_artifact(out, "value_rim_summary.json", summary, stamp)
    _write_run_report(out / "RUN_REPORT.md", summary, bridge_detail=bridge.detail)
    return summary


def _write_run_report(path: Path, summary: dict[str, Any], *, bridge_detail: str) -> None:
    dist = summary.get("distribution") or {}
    lines = [
        f"# Exploratory value-rim — {summary['instrument_id']}（R2a–d）",
        "",
        f"**as_of**: `{summary['as_of']}`  ",
        f"**mode**: {summary['mode']}  ",
        f"**label**: `{summary['investment_value']}` (engineering smoke only；非投资结论)",
        "",
        "## Outcome",
        f"- profile_primary: **{summary['profile_primary']}** "
        f"(low_confidence={summary['profile_low_confidence']})",
        f"- rim_status: **{summary['rim_status']}**",
        f"- equity_basis: **{summary.get('equity_basis')}**",
        f"- common_equity_0 / total_equity_0 / year: "
        f"{summary.get('common_equity_0')} / {summary.get('total_equity_0')} / "
        f"{summary.get('book_equity_year')}",
        f"- goodwill_0 (sensitivity only): {summary.get('goodwill_0')}",
        f"- last_fy_ni (P1 common / EPS×shares): {summary.get('last_fy_ni')}",
        f"- last_fy_dps (sharebonus): {summary.get('last_fy_dps')}",
        f"- ke / g (ASSUMPTION point): {summary.get('cost_of_equity')} / {summary.get('terminal_growth')}",
        f"- P1 point VPS: {summary.get('value_per_share_p1_point')}",
        f"- P2 dist VPS p05/p50/p95 (ke={((dist.get('ke_grid') or [{}])[0] or {}).get('cost_of_equity')}): "
        f"{dist.get('vps_p05')} / {dist.get('vps_p50')} / {dist.get('vps_p95')}",
        f"- ke_grid: {json.dumps(dist.get('ke_grid'), ensure_ascii=False) if dist.get('ke_grid') else None}",
        f"- ev_bridge_applied: {summary.get('ev_bridge_applied')}",
        f"- ensemble: {summary.get('ensemble')}",
        f"- pb_roe: {json.dumps(summary.get('pb_roe'), ensure_ascii=False)}",
        f"- track_b: {json.dumps(summary.get('track_b'), ensure_ascii=False)}",
        f"- flags: {', '.join(summary.get('flags') or [])}",
        f"- industrial FCFF disabled: {summary.get('industrial_fcff_disabled')}",
        f"- pit_complete / quality: {summary.get('pit_complete')} / {summary.get('quality_status')}",
        "",
        "## Bridge detail",
        f"```\n{bridge_detail}\n```",
        "",
        "## Honesty",
        "- Legacy `vms project` / `vms value` remain `UNSUPPORTED_PROFILE` for industry.unsupported names.",
        "- Common equity / DPS / P2 ROE / ke grid are ASSUMPTIONs; OCI zeros explicit when used.",
        "- R2c P/B-ROE sidecar + R2d Track B when eligible; PEER_SCARCITY / hist<12 → explicit UNAVAILABLE; no ensemble.",
        "- `INVESTMENT_VALUE_NOT_ESTABLISHED`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def dump_value_rim_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
