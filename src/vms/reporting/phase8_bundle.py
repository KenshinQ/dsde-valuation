"""VMS-0.2 Phase 8 offline ensemble / model-uncertainty demo (SPEC §20 Phase 8).

PRIOR_ONLY research mixture + production refusal. Saves method_results/ and
ensemble_report.json. No ENSEMBLE_CALIBRATED. INVESTMENT_VALUE_NOT_ESTABLISHED.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.ensemble import (
    MethodDistribution,
    build_ensemble,
    samples_from_point,
)
from vms.ensemble.protocols import EnsembleMode
from vms.market_pricing import unavailable_market_pricing
from vms.methods import MethodResult, build_registry_from_config
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.router import method_eligibility_payload, route_methods
from vms.schemas.config import load_config
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)

PHASE8_STATUS = "PHASE8_ENSEMBLE_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
CST = timezone(timedelta(hours=8))

FixtureKind = Literal["mature", "financial", "holding"]


class Phase8BundleError(ValueError):
    pass


def _fixture_file(kind: FixtureKind) -> str:
    return {
        "mature": "mature_operating.json",
        "financial": "financial_institution.json",
        "holding": "holding.json",
    }[kind]


def _synthetic_components(
    target: ValuationTarget,
    *,
    basis: OutputBasis = OutputBasis.EQUITY,
    seed: int = 42,
) -> list[MethodDistribution]:
    """Hand centers → local samples for offline disagreement / mixture demos."""
    centers = {
        "fcff_dcf": 1000.0,
        "fcfe_dcf": 900.0,
        "ddm": 700.0,
    }
    out: list[MethodDistribution] = []
    for i, (mid, center) in enumerate(sorted(centers.items())):
        out.append(
            MethodDistribution(
                method_id=mid,
                samples=samples_from_point(center, n=96, seed=seed + i * 17),
                status=MethodEligibilityStatus.VALID,
                target=target,
                output_basis=basis,
                eligible=True,
                diagnostics={"center": center, "synthetic": True},
            )
        )
    return out


def _incompatible_components(target: ValuationTarget) -> list[MethodDistribution]:
    """EV-only vs EQUITY-only — must fail compatibility when basis=EQUITY."""
    return [
        MethodDistribution(
            method_id="ev_only_stub",
            samples=samples_from_point(500.0, n=32, seed=1),
            status=MethodEligibilityStatus.VALID,
            target=target,
            output_basis=OutputBasis.EV,
            eligible=True,
        ),
        MethodDistribution(
            method_id="equity_stub",
            samples=samples_from_point(400.0, n=32, seed=2),
            status=MethodEligibilityStatus.VALID,
            target=target,
            output_basis=OutputBasis.EQUITY,
            eligible=True,
        ),
    ]


def _method_results_from_components(
    components: list[MethodDistribution],
) -> list[MethodResult]:
    results: list[MethodResult] = []
    for c in components:
        field = {
            OutputBasis.EQUITY: "equity_value",
            OutputBasis.EV: "enterprise_value",
            OutputBasis.NAV: "nav",
            OutputBasis.PER_SHARE: "value_per_share",
            OutputBasis.MARKET_PRICE: "market_price",
        }[c.output_basis]
        results.append(
            MethodResult(
                method_id=c.method_id,
                status=c.status,
                detail="phase8 synthetic distribution",
                output_basis=[c.output_basis],
                values={field: {"p50": c.median, "mean": c.mean}},
                diagnostics=dict(c.diagnostics),
            )
        )
    return results


def build_phase8_bundle(
    out: Path,
    *,
    config_path: str | Path | None = None,
    seed: int = 42,
    as_of: str | None = None,
    fixture: FixtureKind = "mature",
    target: ValuationTarget | None = None,
    n_draws: int = 1000,
) -> dict[str, Any]:
    """Write Phase 8 artifacts: method_results/, ensemble_report, weight artifacts."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    cfg_path = (
        Path(config_path)
        if config_path
        else Path(__file__).resolve().parents[3] / "config" / "default.yaml"
    )
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

    registry = build_registry_from_config(loaded.method_registry)
    tgt = target or ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    if fixture == "holding" and target is None:
        tgt = ValuationTarget.ASSET_NAV

    route = route_methods(
        registry=registry,
        profile=profile,
        target=tgt,
        available_fields=available_fields,
        peer_count=8,
        data_quality_blocked=False,
        attempt_value_paths=False,
        context_loaded=loaded,
    )

    components = _synthetic_components(tgt, seed=seed)
    method_results = _method_results_from_components(components)

    # Production refusal (default)
    prod = build_ensemble(
        components,
        target=tgt,
        requested_output_basis=OutputBasis.EQUITY,
        intent="production",
        n_draws=n_draws,
        seed=seed,
        method_results_for_compat=method_results,
        market_outcome_weights={
            "fcff_dcf": 0.5,
            "fcfe_dcf": 0.3,
            "ddm": 0.2,
        },
    )

    # PRIOR_ONLY research mixture (labeled exploratory)
    research = build_ensemble(
        components,
        target=tgt,
        requested_output_basis=OutputBasis.EQUITY,
        intent="research_prior",
        n_draws=n_draws,
        seed=seed,
        method_results_for_compat=method_results,
        market_outcome_weights={
            "fcff_dcf": 0.5,
            "fcfe_dcf": 0.3,
            "ddm": 0.2,
        },
    )

    incompat = build_ensemble(
        _incompatible_components(tgt),
        target=tgt,
        requested_output_basis=OutputBasis.EQUITY,
        intent="research_prior",
        n_draws=200,
        seed=seed,
        compute_l1o=False,
    )

    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "method_registry_version": loaded.method_registry.registry_version,
        "router_version": loaded.router.router_version if hasattr(loaded, "router") else None,
        "fixture": fixture,
        "n_draws": n_draws,
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase8",
            instrument=profile.instrument_id,
            as_of=as_of.isoformat(),
            seed=seed,
            fixture=fixture,
            target=tgt.value,
            config=sha256_of(config_snapshot),
        ),
    )
    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(out, "profile_report.json", profile.model_dump(mode="json"), stamp)
    write_artifact(out, "route_report.json", route.model_dump(mode="json"), stamp)

    eligibility_payload = method_eligibility_payload(route, run_id=stamp.run_id)
    eligibility_payload["schema_version"] = SCHEMA_VERSION
    eligibility_payload["implemented_phase"] = IMPLEMENTED_PHASE
    write_artifact(out, "method_eligibility.json", eligibility_payload, stamp)

    # method_results/ — method-specific distributions always saved (AC4)
    mr_dir = out / "method_results"
    mr_dir.mkdir(parents=True, exist_ok=True)
    for c in components:
        write_artifact(
            mr_dir,
            f"{c.method_id}.json",
            {
                **c.model_dump(mode="json"),
                # Persist summary without dumping entire sample vector twice in summary
                "n_samples": len(c.samples),
                "schema_version": SCHEMA_VERSION,
                "implemented_phase": IMPLEMENTED_PHASE,
            },
            stamp,
        )

    # Intrinsic vs market weight artifacts as separate files (AC5)
    if research.weight_artifact is not None:
        write_artifact(
            out,
            "intrinsic_value_weights.json",
            research.weight_artifact.model_dump(mode="json"),
            stamp,
        )
    if research.market_outcome_weight_artifact is not None:
        write_artifact(
            out,
            "market_outcome_weights.json",
            research.market_outcome_weight_artifact.model_dump(mode="json"),
            stamp,
        )

    ensemble_payload = {
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "run_id": stamp.run_id,
        "production_refusal": prod.model_dump(mode="json"),
        "research_prior": research.model_dump(mode="json"),
        "incompatible_demo": incompat.model_dump(mode="json"),
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Phase 8 ensemble subsystem synthetic demo. "
            "PRIOR_ONLY equal-weight is exploratory only — NOT ENSEMBLE_CALIBRATED. "
            "No walk-forward calibration sample (Phase 11). "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED."
        ),
    }
    write_artifact(out, "ensemble_report.json", ensemble_payload, stamp)

    mp = unavailable_market_pricing()
    write_artifact(out, "simulation_metadata.json", {
        "status": PHASE8_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Phase 8 ensemble + model uncertainty synthetic demo. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED."
        ),
        "data_label": "SYNTHETIC — not real market data",
        "seed": seed,
        "fixture": fixture,
        "market_pricing_status": mp.status,
        "as_of_interpretation": as_of_note if isinstance(as_of_note, str) else AS_OF_DATE_RULE,
        "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
        "as_of_rule": AS_OF_DATE_RULE,
    }, stamp)

    summary = {
        "status": PHASE8_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "fixture": fixture,
        "target": tgt.value,
        "profile_primary": profile.primary_profile.value,
        "production_ensemble_status": prod.ensemble_status,
        "production_calibration_status": prod.calibration_status,
        "production_mixture": prod.mixture is not None,
        "research_ensemble_status": research.ensemble_status,
        "research_mode": research.mode.value if isinstance(research.mode, EnsembleMode) else str(research.mode),
        "research_mixture": research.mixture is not None,
        "research_protocol": (
            research.weight_artifact.protocol.protocol_id.value
            if research.weight_artifact
            else None
        ),
        "equal_weight_labeled_prior_only": True,
        "calibrated_claim": False,
        "disagreement_range": research.disagreement.range,
        "l1o_max_abs_delta_median": (
            research.leave_one_out.max_abs_delta_median if research.leave_one_out else None
        ),
        "incompatible_demo_status": incompat.ensemble_status,
        "market_pricing_status": mp.status,
        "artifacts": [
            "ensemble_report.json",
            "intrinsic_value_weights.json",
            "market_outcome_weights.json",
            "method_results/",
        ],
    }
    (out / "phase8_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
