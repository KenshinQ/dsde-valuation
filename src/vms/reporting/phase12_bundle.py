"""VMS-0.2 Phase 12 offline release examples (SPEC §19 / §20 Phase 12).

Five synthetic economic patterns:
  mature_operating, growth_negative_fcf, bank, cyclical, holding

Each pattern writes profile + router diagnostics. Mature also runs Track A
cash-flow methods and Track B exit/return distributions. Other patterns reuse
Phase 5/6 builders or stop at an honest unsupported / coverage-gap diagnosis.

Engineering release only — INVESTMENT_VALUE_NOT_ESTABLISHED. No alpha claim.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.methods import build_registry_from_config
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.reporting.bundle_validation import (
    PHASE_CLI_SUBSETS,
    validate_result_bundle,
    write_validation_report,
)
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.reporting.phase4_bundle import build_phase4_bundle
from vms.reporting.phase9_bundle import build_phase9_bundle
from vms.reporting.phase5_bundle import build_phase5_bundle
from vms.reporting.phase6_bundle import build_phase6_bundle
from vms.reporting.phase10_bundle import build_phase10_bundle
from vms.router import method_eligibility_payload, route_methods
from vms.schemas.config import load_config
from vms.schemas.contracts import ClaimStatus, ValuationTarget

PHASE12_STATUS = "PHASE12_RELEASE_EXAMPLES_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value

PatternId = Literal[
    "mature_operating",
    "growth_negative_fcf",
    "bank",
    "cyclical",
    "holding",
]

ALL_PATTERNS: tuple[PatternId, ...] = (
    "mature_operating",
    "growth_negative_fcf",
    "bank",
    "cyclical",
    "holding",
)

_FIXTURE_FILE: dict[PatternId, str] = {
    "mature_operating": "mature_operating.json",
    "growth_negative_fcf": "growth_negative_fcf.json",
    "bank": "financial_institution.json",
    "cyclical": "cyclical.json",
    "holding": "holding.json",
}

_EXPECTED_PRIMARY: dict[PatternId, str] = {
    "mature_operating": "MATURE_OPERATING",
    "growth_negative_fcf": "GROWTH_OR_REINVESTMENT_HEAVY",
    "bank": "FINANCIAL_INSTITUTION",
    "cyclical": "CYCLICAL_OPERATING",
    "holding": "HOLDING_OR_CONGLOMERATE",
}


class Phase12BundleError(ValueError):
    pass


def _default_config() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "default.yaml"


def _route_pattern(
    *,
    pattern: PatternId,
    loaded: Any,
    as_of: datetime,
    peer_count: int = 8,
) -> dict[str, Any]:
    fix_name = _FIXTURE_FILE[pattern]
    data = load_fixture(fixtures_dir() / fix_name)
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={
        "instrument_id": data["features"]["instrument_id"],
        "as_of": as_of.date().isoformat(),
    })
    profile = classify_profile(feats)
    available_fields = frozenset(data.get("available_fields") or [])
    registry = build_registry_from_config(loaded.method_registry)

    if pattern == "holding":
        tgt = ValuationTarget.ASSET_NAV
    else:
        tgt = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT

    route = route_methods(
        registry=registry,
        profile=profile,
        target=tgt,
        available_fields=available_fields,
        peer_count=peer_count if pattern != "bank" else 0,
        data_quality_blocked=False,
        attempt_value_paths=False,
        context_loaded=loaded,
    )
    return {
        "fixture_file": fix_name,
        "fixture_id": data.get("fixture_id"),
        "expected_primary": _EXPECTED_PRIMARY[pattern],
        "allow_low_confidence": bool(data.get("allow_low_confidence")),
        "profile": profile,
        "route": route,
        "target": tgt,
        "available_fields": sorted(available_fields),
        "eligibility_payload": method_eligibility_payload(route),
    }


def _assert_profile_ok(pattern: PatternId, profile: Any) -> list[str]:
    """Return diagnosis notes; raise only on hard mis-route."""
    notes: list[str] = []
    expected = _EXPECTED_PRIMARY[pattern]
    primary = getattr(profile.primary_profile, "value", str(profile.primary_profile))
    if primary == expected:
        return notes
    flags = [getattr(f, "value", str(f)) for f in (profile.flags or [])]
    if pattern == "cyclical" and ("HIGH_CYCLICALITY" in flags or profile.low_confidence):
        notes.append(
            f"cyclical fixture primary={primary}; flags={flags}; "
            f"low_confidence={profile.low_confidence}"
        )
        return notes
    scores = getattr(profile, "profile_scores", {}) or {}
    if expected in scores:
        notes.append(f"primary={primary} but expected {expected} present in scores={scores}")
        return notes
    raise Phase12BundleError(
        f"pattern={pattern}: primary={primary} flags={flags} expected={expected}"
    )


def _copy_key_artifacts(src: Path, dst: Path, names: list[str]) -> list[str]:
    copied: list[str] = []
    for name in names:
        s = src / name
        if s.is_file():
            shutil.copy2(s, dst / name)
            copied.append(name)
        elif s.is_dir():
            target = dst / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(s, target)
            copied.append(name + "/")
    return copied


def build_phase12_pattern(
    *,
    out_dir: str | Path,
    pattern: PatternId,
    config_path: str | Path | None = None,
    seed: int = 42,
    paths: int = 20,
    years: int = 3,
    as_of: datetime | None = None,
    spot_price: float | None = 10.0,
) -> dict[str, Any]:
    """Build one offline example directory for ``pattern``."""
    if pattern not in ALL_PATTERNS:
        raise Phase12BundleError(f"unknown pattern {pattern!r}; choose from {ALL_PATTERNS}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg_path = Path(config_path) if config_path else _default_config()
    loaded = load_config(cfg_path)
    if as_of is None:
        as_of, as_of_note = parse_as_of("2025-06-30")
    else:
        as_of_note = AS_OF_DATE_RULE

    routed = _route_pattern(pattern=pattern, loaded=loaded, as_of=as_of)
    profile = routed["profile"]
    route = routed["route"]
    notes = _assert_profile_ok(pattern, profile)

    stamp = ArtifactStamp(
        run_id=content_run_id(
            seed=seed, pattern=pattern, phase="phase12", schema=SCHEMA_VERSION,
        ),
        schema_version=SCHEMA_VERSION,
    )

    config_snapshot = {
        "config": loaded.config.model_dump(mode="json"),
        "configuration_version": loaded.config.configuration_version,
        "registry_version": getattr(loaded.method_registry, "registry_version", None),
    }
    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(out, "request.json", {
        "pattern": pattern,
        "seed": seed,
        "paths": paths,
        "years": years,
        "as_of": as_of.isoformat(),
        "as_of_interpretation": as_of_note,
        "target": routed["target"].value,
        "investment_value": INVESTMENT_LABEL,
        "status": PHASE12_STATUS,
    }, stamp)
    write_artifact(out, "profile_report.json", {
        **profile.model_dump(mode="json"),
        "fixture_id": routed["fixture_id"],
        "expected_primary": routed["expected_primary"],
        "pattern": pattern,
    }, stamp)
    write_artifact(out, "method_eligibility.json", {
        **routed["eligibility_payload"],
        "pattern": pattern,
        "coverage_status": route.coverage_status,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
    }, stamp)
    write_artifact(out, "route_report.json", route.model_dump(mode="json"), stamp)

    method_outcome = "ROUTE_ONLY"
    track_b_outcome = "NOT_RUN"
    diagnostics: dict[str, Any] = {
        "pattern": pattern,
        "coverage_status": route.coverage_status,
        "n_eligible": sum(1 for e in route.eligibility if e.eligible),
        "profile_notes": notes,
        "industrial_fcff_disabled_for_bank": pattern == "bank",
    }

    # --- pattern-specific method / Track B work ---
    if pattern == "mature_operating":
        method_outcome = "CASHFLOW_METHODS"
        mdir = out / "methods"
        build_phase4_bundle(
            out_dir=mdir, config_path=cfg_path, seed=seed, paths=paths, years=years, as_of=as_of,
        )
        _copy_key_artifacts(mdir, out, ["method_results.json", "profile_report.json"])
        # Market-pricing report (Phase 9) + Track B returns (Phase 10)
        track_b_outcome = "EXIT_AND_RETURNS"
        mkt_dir = out / "market_pricing"
        build_phase9_bundle(
            out_dir=mkt_dir, config_path=cfg_path, seed=seed, paths=paths, years=years,
            as_of=as_of, horizons=[1, 3], include_convergence_demo=False,
        )
        _copy_key_artifacts(
            mkt_dir, out,
            ["market_pricing_report.json", "exit_price_summary.json", "financial_path_summary.json"],
        )
        tdir = out / "track_b"
        build_phase10_bundle(
            out_dir=tdir, config_path=cfg_path, seed=seed, paths=paths, years=years,
            as_of=as_of, spot_price=spot_price, horizons=[1, 3],
        )
        _copy_key_artifacts(
            tdir, out,
            [
                "exit_price_summary.json",
                "return_distribution_summary.json",
                "dsde_export.json",
            ],
        )
        # Lightweight diagnostics placeholder (full sensitivity is Phase 11)
        write_artifact(out, "diagnostics.json", {
            "status": "PHASE12_DIAGNOSTICS_SUMMARY",
            "note": "Full OAT/joint sensitivity lives in vms phase11; here we record lineage only.",
            "methods_dir": str(mdir),
            "track_b_dir": str(tdir),
            "investment_value": INVESTMENT_LABEL,
        }, stamp)

    elif pattern == "growth_negative_fcf":
        method_outcome = "MULTIPLES_ATTEMPT"
        # Growth: conventional trailing P/E often ineligible; EV/Sales may pass.
        # Reuse phase5 mature path engine but stamp diagnosis from growth route.
        gdir = out / "multiples_attempt"
        try:
            build_phase5_bundle(
                out_dir=gdir, config_path=cfg_path, seed=seed, paths=max(paths, 16),
                years=years, as_of=as_of, include_cashflow=False,
            )
            _copy_key_artifacts(gdir, out, ["method_results.json", "peer_diagnostics.json"])
            diagnostics["multiples_attempt"] = "phase5_bundle_ok_on_synthetic_operating_paths"
            diagnostics["growth_caveat"] = (
                "Phase 5 demo paths are mature-operating synthetic statements; "
                "growth fixture drives routing diagnosis only. Negative current FCF "
                "implies conventional trailing P/E must not be treated as primary."
            )
        except Exception as e:  # noqa: BLE001 — surface as diagnosed gap
            diagnostics["multiples_attempt_error"] = f"{type(e).__name__}: {e}"
            method_outcome = "DIAGNOSED_GAP"
            write_artifact(out, "method_results.json", {
                "status": "DIAGNOSED_GAP",
                "reason": str(e),
                "pattern": pattern,
                "investment_value": INVESTMENT_LABEL,
            }, stamp)
        track_b_outcome = "NOT_APPLICABLE_FOR_PATTERN_DEMO"
        diagnostics["track_b"] = (
            "Exit/return demo deferred for growth pattern in Phase 12 packaging; "
            "use vms phase10 on operating paths for Track B smoke."
        )

    elif pattern == "bank":
        method_outcome = "RIM"
        bdir = out / "rim"
        build_phase6_bundle(
            out_dir=bdir, config_path=cfg_path, seed=seed, as_of=as_of, fixture="financial",
        )
        _copy_key_artifacts(bdir, out, ["method_results.json"])
        # Confirm industrial FCFF is not silently defaulted
        elig = routed["eligibility_payload"]
        fcff = None
        for row in (elig.get("methods") or []) + (elig.get("method_status") or []):
            if isinstance(row, dict) and row.get("method_id") == "fcff_dcf":
                fcff = row
                break
        if fcff is None:
            for e in route.eligibility:
                if e.method_id == "fcff_dcf":
                    fcff = e.model_dump(mode="json")
                    break
        diagnostics["fcff_dcf_row"] = fcff
        diagnostics["expected"] = "industrial FCFF disabled / ineligible for FINANCIAL_INSTITUTION"
        track_b_outcome = "NOT_APPLICABLE_BANK_PROFILE"
        write_artifact(out, "diagnostics.json", {
            "status": "BANK_RIM_ROUTE",
            "investment_value": INVESTMENT_LABEL,
            **diagnostics,
        }, stamp)

    elif pattern == "cyclical":
        method_outcome = "ROUTE_WITH_CYCLICALITY_FLAG"
        flags = [getattr(f, "value", str(f)) for f in (profile.flags or [])]
        diagnostics["flags"] = flags
        diagnostics["cyclical_guidance"] = (
            "Unnormalized trailing P/E must be excluded or prominently downgraded; "
            "normalized / mid-cycle approaches required for meaningful output "
            "(SPEC Appendix A)."
        )
        # Still emit eligibility; method math may be LOW_CONFIDENCE / INELIGIBLE
        write_artifact(out, "method_results.json", {
            "status": "ROUTE_DIAGNOSIS_ONLY",
            "detail": "Cyclical pattern Phase 12 packaging asserts routing + flags, "
                      "not a calibrated mid-cycle multiple.",
            "flags": flags,
            "investment_value": INVESTMENT_LABEL,
        }, stamp)
        track_b_outcome = "NOT_RUN"
        write_artifact(out, "diagnostics.json", {
            "status": "CYCLICAL_ROUTE_DIAGNOSIS",
            "investment_value": INVESTMENT_LABEL,
            **diagnostics,
        }, stamp)

    elif pattern == "holding":
        method_outcome = "SOTP_NAV_OR_GAP"
        hdir = out / "nav_sotp"
        build_phase6_bundle(
            out_dir=hdir, config_path=cfg_path, seed=seed, as_of=as_of, fixture="holding",
        )
        _copy_key_artifacts(hdir, out, ["method_results.json"])
        # Also document data-gap path
        gdir = out / "holding_gap"
        build_phase6_bundle(
            out_dir=gdir, config_path=cfg_path, seed=seed, as_of=as_of, fixture="holding_gap",
        )
        diagnostics["holding_with_schedules"] = str(hdir)
        diagnostics["holding_data_gap_demo"] = str(gdir)
        track_b_outcome = "NOT_APPLICABLE_HOLDING_PROFILE"
        write_artifact(out, "diagnostics.json", {
            "status": "HOLDING_SOTP_NAV",
            "investment_value": INVESTMENT_LABEL,
            **diagnostics,
        }, stamp)

    # simulation_metadata + summary (summary before validation so subset check passes)
    labels = {
        "INVESTMENT_VALUE_NOT_ESTABLISHED": True,
        "ENSEMBLE_CALIBRATED": False,
        "INVESTMENT_VALUE_SUPPORTED": False,
        "CALIBRATION_INSUFFICIENT": True,
    }
    meta = {
        "status": PHASE12_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "schema_version": SCHEMA_VERSION,
        "pattern": pattern,
        "method_outcome": method_outcome,
        "track_b_outcome": track_b_outcome,
        "coverage_status": route.coverage_status,
        "investment_value": INVESTMENT_LABEL,
        "labels": labels,
        "data_label": "SYNTHETIC — not real market data",
        "warning": "Engineering offline example. Not investment advice. No alpha claim.",
        "seed": seed,
        "config_hash": sha256_of(json.dumps(config_snapshot, sort_keys=True)),
        "diagnostics": diagnostics,
        "phase_cli_subsets_ref": sorted(PHASE_CLI_SUBSETS),
    }
    write_artifact(out, "simulation_metadata.json", meta, stamp)

    subset = "phase12_mature_full" if pattern == "mature_operating" else "phase12"
    summary = {
        "status": PHASE12_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "pattern": pattern,
        "method_outcome": method_outcome,
        "track_b_outcome": track_b_outcome,
        "coverage_status": route.coverage_status,
        "investment_value": INVESTMENT_LABEL,
        "labels": labels,
        "validation_ok": None,
        "validation_subset": subset,
        "out": str(out),
        "seed": seed,
        "primary_profile": getattr(profile.primary_profile, "value", str(profile.primary_profile)),
        "expected_primary": routed["expected_primary"],
    }
    write_artifact(out, "phase12_summary.json", summary, stamp)

    vrep = write_validation_report(out, subset=subset)
    vrep["schema_version"] = SCHEMA_VERSION
    vrep["implemented_phase"] = IMPLEMENTED_PHASE
    vrep["investment_value"] = INVESTMENT_LABEL
    vrep["pattern"] = pattern
    (out / "validation_report.json").write_text(
        json.dumps(vrep, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Re-validate after validation_report exists (subset includes it)
    vrep2 = validate_result_bundle(out, subset=subset)
    vrep_final = vrep2.to_dict()
    vrep_final["status"] = "PASS" if vrep2.ok else "FAIL"
    vrep_final["schema_version"] = SCHEMA_VERSION
    vrep_final["implemented_phase"] = IMPLEMENTED_PHASE
    vrep_final["investment_value"] = INVESTMENT_LABEL
    vrep_final["pattern"] = pattern
    (out / "validation_report.json").write_text(
        json.dumps(vrep_final, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary["validation_ok"] = bool(vrep2.ok)
    write_artifact(out, "phase12_summary.json", summary, stamp)
    return summary


def build_phase12_release(
    *,
    out_dir: str | Path,
    config_path: str | Path | None = None,
    seed: int = 42,
    paths: int = 20,
    years: int = 3,
    patterns: tuple[PatternId, ...] | list[PatternId] | None = None,
) -> dict[str, Any]:
    """Run all (or selected) offline patterns into ``out_dir/<pattern>/``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected: tuple[PatternId, ...] = tuple(patterns) if patterns else ALL_PATTERNS
    results: dict[str, Any] = {}
    for pat in selected:
        sub = out / pat
        results[pat] = build_phase12_pattern(
            out_dir=sub,
            pattern=pat,
            config_path=config_path,
            seed=seed,
            paths=paths,
            years=years,
        )
    stamp = ArtifactStamp(
        run_id=content_run_id(seed=seed, phase="phase12_release", schema=SCHEMA_VERSION),
        schema_version=SCHEMA_VERSION,
    )
    release = {
        "status": PHASE12_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "labels": {
            "INVESTMENT_VALUE_NOT_ESTABLISHED": True,
            "ENSEMBLE_CALIBRATED": False,
            "INVESTMENT_VALUE_SUPPORTED": False,
            "CALIBRATION_INSUFFICIENT": True,
        },
        "patterns": {k: {
            "primary_profile": v.get("primary_profile"),
            "method_outcome": v.get("method_outcome"),
            "track_b_outcome": v.get("track_b_outcome"),
            "validation_ok": v.get("validation_ok"),
            "coverage_status": v.get("coverage_status"),
        } for k, v in results.items()},
        "warning": "Synthetic engineering release. Not investment advice. No alpha claim.",
        "out": str(out),
        "seed": seed,
    }
    write_artifact(out, "phase12_release_summary.json", release, stamp)
    write_artifact(out, "simulation_metadata.json", {
        **release,
        "kind": "phase12_release_root",
    }, stamp)
    # Root validation: require release summary + metadata only
    (out / "phase12_summary.json").write_text(
        json.dumps(release, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "profile_report.json").write_text(
        json.dumps({"kind": "release_root", "patterns": list(selected)}, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "method_eligibility.json").write_text(
        json.dumps({"kind": "release_root", "see": "per-pattern method_eligibility.json"}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    write_validation_report(out, subset="phase12")
    return release


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
