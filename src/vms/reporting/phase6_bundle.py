"""VMS-0.2 Phase 6 offline RIM / NAV / SOTP demo (SPEC §20 Phase 6).

Synthetic financial-institution → residual_income (clean-surplus gated); industrial FCFF disabled.
Synthetic holding → SOTP/NAV with schedules, or visible data-gap without them.
No ensemble, no exit-price estimator. INVESTMENT_VALUE_NOT_ESTABLISHED.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.market_pricing import unavailable_market_pricing
from vms.methods import build_registry_from_config
from vms.methods.asset_based import run_eligible_phase6_methods
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.schemas.config import load_config
from vms.schemas.contracts import ValuationTarget

PHASE6_STATUS = "PHASE6_RIM_NAV_SOTP_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = "INVESTMENT_VALUE_NOT_ESTABLISHED"
CST = timezone(timedelta(hours=8))

FixtureKind = Literal["financial", "holding", "holding_gap"]


class Phase6BundleError(ValueError):
    pass


def _financial_rim_inputs() -> dict[str, Any]:
    """Hand fixture: meaningful book equity + ROE/NI path with explicit CS zeros."""
    return {
        "book_equity_0": 200.0,
        "net_income": [24.0, 25.0, 26.0],
        "dividends": [8.0, 8.5, 9.0],
        "net_issuance": [0.0, 0.0, 0.0],
        "oci": [0.0, 0.0, 0.0],
        "zeros_explicit": True,
        "cost_of_equity": 0.10,
        "terminal_growth": 0.02,
        "diluted_shares": 10.0,
        "years": [2025, 2026, 2027],
    }


def _holding_nav_inputs() -> dict[str, Any]:
    return {
        "assets": [
            {
                "line_id": "listed_sub_a",
                "kind": "asset",
                "book_value": 80.0,
                "fair_value": 120.0,
                "haircut": 0.10,
                "justification": "observable market value of listed subsidiary A (PIT close)",
                "basis": "market",
            },
            {
                "line_id": "property",
                "kind": "asset",
                "book_value": 50.0,
                "fair_value": 55.0,
                "haircut": 0.05,
                "justification": "independent appraisal dated before as_of",
                "basis": "appraisal",
            },
            {
                "line_id": "cash",
                "kind": "asset",
                "book_value": 20.0,
                "fair_value": 20.0,
                "haircut": 0.0,
                "justification": "cash at amortized cost equals fair value",
                "basis": "market",
            },
        ],
        "claims": [
            {
                "line_id": "parent_debt",
                "kind": "claim",
                "book_value": 40.0,
                "fair_value": 40.0,
                "haircut": 0.0,
                "justification": "interest-bearing debt at par (no distress)",
                "basis": "configured",
            },
            {
                "line_id": "minority",
                "kind": "claim",
                "book_value": 10.0,
                "fair_value": 10.0,
                "haircut": 0.0,
                "justification": "minority interest at book pending segment fair look-through",
                "basis": "configured",
            },
        ],
        "corporate_overhead_pv": 5.0,
        "disposal_tax": 2.0,
        "diluted_shares": 10.0,
    }


def _holding_sotp_inputs() -> dict[str, Any]:
    return {
        "segments": [
            {
                "segment_id": "listed_a",
                "equity_value": 108.0,  # 120*(1-0.1) from NAV line conceptual
                "method": "configured",
                "inter_segment_receivable": 5.0,
                "inter_segment_payable": 0.0,
                "notes": "listed sub look-through",
            },
            {
                "segment_id": "ops_b",
                "equity_value": 40.0,
                "method": "configured",
                "inter_segment_receivable": 0.0,
                "inter_segment_payable": 5.0,
                "notes": "unlisted ops",
            },
        ],
        "inter_segment_elimination": 0.0,  # recv 5 - pay 5 = 0
        "group_costs_pv": 5.0,
        "parent_debt": 40.0,
        "minority_interest": 10.0,
        "non_operating_assets": 20.0,
        "holding_discount": {
            "rate": 0.15,
            "uncertain": True,
            "low": 0.05,
            "high": 0.25,
            "rationale": "conglomerate discount prior; explicit uncertain parameter",
        },
        "diluted_shares": 10.0,
    }


def build_phase6_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path,
    seed: int = 42,
    as_of: datetime | None = None,
    fixture: FixtureKind = "financial",
    target: ValuationTarget | None = None,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loaded = load_config(config_path)
    cfg = loaded.config
    if as_of is None:
        as_of, as_of_note = parse_as_of("2025-06-30")
    else:
        as_of_note = AS_OF_DATE_RULE

    if fixture == "financial":
        fix_name = "financial_institution.json"
        rim_inputs = _financial_rim_inputs()
        nav_inputs: dict[str, Any] = {}
        sotp_inputs: dict[str, Any] = {}
        default_target = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
        subject = {
            "total_equity": rim_inputs["book_equity_0"],
            "parent_net_income": rim_inputs["net_income"][0],
        }
    elif fixture == "holding":
        fix_name = "holding.json"
        rim_inputs = {}
        nav_inputs = _holding_nav_inputs()
        sotp_inputs = _holding_sotp_inputs()
        default_target = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
        subject = {
            "total_equity": 100.0,
            "interest_bearing_debt": 40.0,
            "total_assets": 200.0,
            "total_liabilities": 100.0,
        }
    elif fixture == "holding_gap":
        fix_name = "holding.json"
        rim_inputs = {}
        nav_inputs = {
            "total_assets": 200.0,
            "total_liabilities": 100.0,
            # deliberately no assets/claims schedule
        }
        sotp_inputs = {
            # deliberately no segments
            "parent_debt": 40.0,
        }
        default_target = ValuationTarget.ASSET_NAV
        subject = {
            "total_equity": 100.0,
            "interest_bearing_debt": 40.0,
            "total_assets": 200.0,
            "total_liabilities": 100.0,
        }
    else:
        raise Phase6BundleError(f"unknown fixture kind {fixture!r}")

    data = load_fixture(fixtures_dir() / fix_name)
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={
        "instrument_id": data["features"]["instrument_id"],
        "as_of": as_of.date().isoformat(),
    })
    profile = classify_profile(feats)
    available_fields = frozenset(data.get("available_fields") or [])
    registry = build_registry_from_config(loaded.method_registry)
    tgt = target or default_target

    run = run_eligible_phase6_methods(
        registry=registry,
        profile=profile,
        target=tgt,
        loaded=loaded,
        available_fields=available_fields,
        rim_inputs=rim_inputs,
        nav_inputs=nav_inputs,
        sotp_inputs=sotp_inputs,
        subject_metrics=subject,
        as_of=as_of.isoformat(),
        method_assumptions={
            "residual_income": dict(rim_inputs),
            "nav": dict(nav_inputs),
            "sotp": dict(sotp_inputs),
        },
    )

    # Also show industrial FCFF disability on financial-institution via a side route note
    industrial_note = None
    if fixture == "financial":
        from vms.router.route import route_methods
        r_fcff = route_methods(
            registry=registry, profile=profile,
            target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
            available_fields=available_fields | frozenset({
                "revenue", "ebit", "cash_flow_from_operations", "capex",
                "total_equity", "interest_bearing_debt", "cash",
            }),
            attempt_value_paths=False, context_loaded=loaded,
        )
        fcff_elig = next((e for e in r_fcff.eligibility if e.method_id == "fcff_dcf"), None)
        ev_elig = next((e for e in r_fcff.eligibility if e.method_id == "ev_ebitda"), None)
        industrial_note = {
            "fcff_dcf_eligible": bool(fcff_elig and fcff_elig.eligible),
            "ev_ebitda_eligible": bool(ev_elig and ev_elig.eligible),
            "note": "industrial FCFF/EV EBITDA remain disabled for FINANCIAL_INSTITUTION",
        }

    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "method_registry_version": loaded.method_registry.registry_version,
        "fixture": fixture,
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase6", instrument=profile.instrument_id, as_of=as_of.isoformat(),
            seed=seed, fixture=fixture, target=tgt.value,
            config=sha256_of(config_snapshot),
        ),
    )
    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(out, "profile_report.json", profile.model_dump(mode="json"), stamp)
    write_artifact(out, "route_report.json", run.route.model_dump(mode="json"), stamp)
    write_artifact(out, "method_results.json", {
        "results": [r.model_dump(mode="json") for r in run.results],
        "eligible_run": list(run.eligible_run),
        "skipped": list(run.skipped),
        "ensemble": None,
        "notes": run.notes,
        "investment_value": INVESTMENT_LABEL,
        "industrial_fcff_disabled": industrial_note,
    }, stamp)

    mp = unavailable_market_pricing()
    write_artifact(out, "simulation_metadata.json", {
        "status": PHASE6_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Phase 6 RIM/NAV/SOTP synthetic demo. No calibrated ensemble, no exit-price "
            "estimator. Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED."
        ),
        "data_label": "SYNTHETIC — not real market data",
        "seed": seed,
        "fixture": fixture,
        "eligible_run": list(run.eligible_run),
        "market_pricing_status": mp.status,
        "as_of_interpretation": as_of_note,
        "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
    }, stamp)

    summary = {
        "status": PHASE6_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "fixture": fixture,
        "target": tgt.value,
        "profile_primary": profile.primary_profile.value,
        "coverage_status": run.route.coverage_status,
        "eligible_run": list(run.eligible_run),
        "method_statuses": [
            {
                "method_id": r.method_id,
                "status": r.status.value,
                "reason_codes": r.reason_codes,
                "unsupported": bool((r.diagnostics or {}).get("unsupported")),
                "data_gap": (r.diagnostics or {}).get("data_gap"),
            }
            for r in run.results
        ],
        "industrial_fcff_disabled": industrial_note,
        "market_pricing_status": mp.status,
        "ensemble": None,
    }
    (out / "phase6_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
