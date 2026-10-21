"""VMS-0.2 Phase 7 offline router / comparison demo (SPEC §20 Phase 7).

Deterministic routing log + soft suitability + method disagreement.
No calibrated ensemble, no exit-price estimator.
INVESTMENT_VALUE_NOT_ESTABLISHED.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.market_pricing import unavailable_market_pricing
from vms.methods import MethodResult, build_registry_from_config
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.router import (
    compare_methods,
    method_eligibility_payload,
    refuse_uncalibrated_blend,
    route_methods,
)
from vms.schemas.config import load_config
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)

PHASE7_STATUS = "PHASE7_ROUTER_COMPARE_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
CST = timezone(timedelta(hours=8))

FixtureKind = Literal["mature", "financial", "holding", "hybrid_gap"]


class Phase7BundleError(ValueError):
    pass


def _fixture_file(kind: FixtureKind) -> str:
    return {
        "mature": "mature_operating.json",
        "financial": "financial_institution.json",
        "holding": "holding.json",
        "hybrid_gap": "growth_negative_fcf.json",  # may still have methods; see force_gap
    }[kind]


def _synthetic_method_results_for_compare() -> list[MethodResult]:
    """Hand medians for disagreement demo — not investment estimates."""
    return [
        MethodResult(
            method_id="fcff_dcf",
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail="phase7 synthetic compare fixture",
            output_basis=[OutputBasis.EV, OutputBasis.EQUITY, OutputBasis.PER_SHARE],
            values={
                "enterprise_value": {"p50": 1200.0, "mean": 1250.0},
                "equity_value": {"p50": 1000.0, "mean": 1040.0},
                "value_per_share": {"p50": 10.0, "mean": 10.4},
            },
        ),
        MethodResult(
            method_id="fcfe_dcf",
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail="phase7 synthetic compare fixture",
            output_basis=[OutputBasis.EQUITY, OutputBasis.PER_SHARE],
            values={
                "equity_value": {"p50": 900.0, "mean": 920.0},
                "value_per_share": {"p50": 9.0, "mean": 9.2},
            },
        ),
        MethodResult(
            method_id="ddm",
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail="phase7 synthetic compare fixture",
            output_basis=[OutputBasis.EQUITY, OutputBasis.PER_SHARE],
            values={
                "equity_value": {"p50": 700.0, "mean": 710.0},
                "value_per_share": {"p50": 7.0, "mean": 7.1},
            },
        ),
    ]


def _incompatible_pair_for_tests() -> list[MethodResult]:
    """EV-only vs EQUITY without bridge — must fail compatibility."""
    return [
        MethodResult(
            method_id="ev_only_stub",
            status=MethodEligibilityStatus.VALID,
            output_basis=[OutputBasis.EV],
            values={"enterprise_value": {"p50": 500.0}},
        ),
        MethodResult(
            method_id="equity_stub",
            status=MethodEligibilityStatus.VALID,
            output_basis=[OutputBasis.EQUITY],
            values={"equity_value": {"p50": 400.0}},
        ),
    ]


def build_phase7_bundle(
    out: Path,
    *,
    config_path: str | Path | None = None,
    seed: int = 42,
    as_of: str | None = None,
    fixture: FixtureKind = "mature",
    target: ValuationTarget | None = None,
    force_no_eligible: bool = False,
    request_blend: bool = False,
) -> dict[str, Any]:
    """Write Phase 7 artifacts: method_eligibility.json + method_comparison.json."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cfg_path = Path(config_path) if config_path else Path(__file__).resolve().parents[3] / "config" / "default.yaml"
    loaded = load_config(cfg_path)
    cfg = loaded.config

    if as_of:
        as_of_dt, as_of_note = parse_as_of(as_of)
    else:
        as_of_dt, as_of_note = parse_as_of("2025-06-30")
    as_of = as_of_dt

    fix_name = _fixture_file(fixture)
    data = load_fixture(fixtures_dir() / fix_name)
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={
        "instrument_id": data["features"]["instrument_id"],
        "as_of": as_of.date().isoformat(),
    })
    profile = classify_profile(feats)
    available_fields = frozenset(data.get("available_fields") or [])
    if force_no_eligible:
        # Strip all fields so every hard gate fails → INSUFFICIENT_METHOD_COVERAGE
        available_fields = frozenset()

    registry = build_registry_from_config(loaded.method_registry)
    tgt = target or ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    if fixture == "holding" and target is None:
        tgt = ValuationTarget.ASSET_NAV

    route = route_methods(
        registry=registry,
        profile=profile,
        target=tgt,
        available_fields=available_fields,
        peer_count=0 if force_no_eligible else 8,
        data_quality_blocked=False,
        attempt_value_paths=False,
        context_loaded=loaded,
    )

    # Comparison uses hand medians when coverage exists; empty when forced gap
    if force_no_eligible or route.coverage_status == "INSUFFICIENT_METHOD_COVERAGE":
        method_results: list[MethodResult] = []
    else:
        method_results = _synthetic_method_results_for_compare()

    comparison = compare_methods(
        method_results,
        target=tgt,
        horizon=None,
        requested_output_basis=OutputBasis.EQUITY,
        request_blend=request_blend,
    )
    blend_refusal = refuse_uncalibrated_blend(
        method_results,
        target=tgt,
        horizon=None,
        requested_output_basis=OutputBasis.EQUITY,
    )

    # Side demonstration of incompatible combination (always recorded)
    incompat = compare_methods(
        _incompatible_pair_for_tests(),
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        horizon=None,
        requested_output_basis=OutputBasis.EQUITY,
    )

    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "method_registry_version": loaded.method_registry.registry_version,
        "router_version": loaded.router.router_version if hasattr(loaded, "router") else None,
        "fixture": fixture,
        "force_no_eligible": force_no_eligible,
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase7", instrument=profile.instrument_id, as_of=as_of.isoformat(),
            seed=seed, fixture=fixture, target=tgt.value,
            config=sha256_of(config_snapshot),
            force_gap=force_no_eligible,
        ),
    )
    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(out, "profile_report.json", profile.model_dump(mode="json"), stamp)
    write_artifact(out, "route_report.json", route.model_dump(mode="json"), stamp)

    eligibility_payload = method_eligibility_payload(route, run_id=stamp.run_id)
    eligibility_payload["schema_version"] = SCHEMA_VERSION
    eligibility_payload["implemented_phase"] = IMPLEMENTED_PHASE
    write_artifact(out, "method_eligibility.json", eligibility_payload, stamp)

    comparison_payload = comparison.model_dump(mode="json")
    comparison_payload["schema_version"] = SCHEMA_VERSION
    comparison_payload["implemented_phase"] = IMPLEMENTED_PHASE
    comparison_payload["run_id"] = stamp.run_id
    comparison_payload["incompatible_demo"] = incompat.model_dump(mode="json")
    comparison_payload["blend_refusal"] = blend_refusal
    write_artifact(out, "method_comparison.json", comparison_payload, stamp)

    mp = unavailable_market_pricing()
    write_artifact(out, "simulation_metadata.json", {
        "status": PHASE7_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Phase 7 router hardening + method comparison synthetic demo. "
            "No calibrated ensemble, no exit-price estimator. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED."
        ),
        "data_label": "SYNTHETIC — not real market data",
        "seed": seed,
        "fixture": fixture,
        "coverage_status": route.coverage_status,
        "market_pricing_status": mp.status,
        "as_of_interpretation": as_of_note if isinstance(as_of_note, str) else AS_OF_DATE_RULE,
        "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
        "as_of_rule": AS_OF_DATE_RULE,
    }, stamp)

    summary = {
        "status": PHASE7_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "fixture": fixture,
        "target": tgt.value,
        "profile_primary": profile.primary_profile.value,
        "coverage_status": route.coverage_status,
        "candidates": list(route.candidates),
        "eligible_count": sum(1 for e in route.eligibility if e.eligible),
        "considerations": len(route.considerations),
        "disagreement": comparison.disagreement.model_dump(mode="json"),
        "ensemble_status": comparison.ensemble.get("status"),
        "combined_value": comparison.ensemble.get("combined_value"),
        "incompatible_demo_compatible": incompat.compatibility.compatible,
        "market_pricing_status": mp.status,
        "routing_deterministic": route.routing_deterministic,
        "force_no_eligible": force_no_eligible,
    }
    (out / "phase7_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
