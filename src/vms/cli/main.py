"""`vms` command-line interface.

Implemented commands:
  validate-data   schema validation; with --as-of also PIT snapshot + quality gate per instrument
  build-snapshot  PIT snapshot + data_quality_report.json + data_manifest.json for one instrument
  project         PIT snapshot + gate + profile + drivers + deterministic statements (Phase 2)
  estimate        PIT snapshot + gate + fundamental regimes + walk-forward + driver distributions (Phase 3)
  simulate        Phase 3 + correlated path sampler (SimulationBundle; not a valuation)
  project-paths   Phase 5 path-wise statements + capital allocation (FinancialPathBundle)
  value           Phase 6 FCFF DCF + exit-multiple + EV-equity bridge
  returns         Phase 7 entry-price-conditioned multi-horizon returns
  sensitivity     Phase 8 sensitivity & uncertainty attribution
  evaluate        Phase 11 chronological walk-forward evaluation (SPEC §17)
  phase0          VMS-0.2 Phase 0 contracts baseline (synthetic; NOT a valuation)
  phase3          VMS-0.2 Phase 3 path bundle (synthetic; NOT a valuation)
  phase4          VMS-0.2 Phase 4 FCFF/FCFE/DDM via router (synthetic; NOT investment advice)
  phase5          VMS-0.2 Phase 5 relative multiples + PIT peers (synthetic; NOT investment advice)
  phase6          VMS-0.2 Phase 6 RIM/NAV/SOTP (synthetic; NOT investment advice)
  value-rim       R1/R2 real A-share FINANCIAL_INSTITUTION → RIM (common equity + P2; NOT investment advice)
  phase7          VMS-0.2 Phase 7 router hardening + method comparison (synthetic; NOT investment advice)
  compare-methods VMS-0.2 Phase 7 method disagreement report (synthetic; NOT investment advice)
  phase8          VMS-0.2 Phase 8 ensemble + model uncertainty (synthetic; NOT investment advice)
  phase9          VMS-0.2 Phase 9 market-pricing regime + exit-price engine (synthetic; NOT investment advice)
  phase10         VMS-0.2 Phase 10 Track B return distributions + DSDE contract (synthetic; NOT investment advice)
  phase11         VMS-0.2 Phase 11 walk-forward calibration + sensitivity (synthetic; NOT investment advice)
  phase12         VMS-0.2 Phase 12 offline release examples (synthetic; NOT investment advice)
  validate-bundle Validate a result-bundle directory against a PHASE_CLI subset / §16.3
  profile         VMS-0.2 Phase 2 economic-profile classifier (NOT a valuation)
  route           VMS-0.2 Phase 7 routing log + soft suitability (no method computation by default)
  demo            offline SYNTHETIC smoke (legacy 0.1 pipeline retained; evaluate + optional DSDE adapter).

Exit codes: 0 ok, 1 unexpected error, 2 invalid input/config/arguments,
            3 BLOCKED by critical data-quality errors in production mode,
            4 UNSUPPORTED_PROFILE (raw metrics written, no projection),
            5 projection INSUFFICIENT_DATA / REJECTED, or INVALID_PATH_FRACTION_EXCEEDED in production.
            (regimes.model=hmm => exit 2: interface only, NOT IMPLEMENTED)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data import synthetic
from vms.data.io import LoadResult, load_directory, write_directory
from vms.pit.asof import AS_OF_DATE_RULE, AsOfError, parse_as_of
from vms.pit.snapshot import PITSnapshot
from vms.quality.report import DataQualityReport, GateError, QualityState, assess, gate
from vms.reporting.metadata import (ArtifactStamp, content_run_id, hash_models, make_run_metadata, sha256_of,
                                    write_artifact)
from vms.reporting.phase0_bundle import (PHASE0_STATUS, Phase0BundleError, build_phase0_bundle,
                                        dump_summary)
from vms.reporting.phase3_bundle import (PHASE3_STATUS, Phase3BundleError, build_phase3_bundle,
                                        dump_summary as dump_phase3_summary)
from vms.reporting.phase4_bundle import (PHASE4_STATUS, Phase4BundleError, build_phase4_bundle,
                                        dump_summary as dump_phase4_summary)
from vms.reporting.phase5_bundle import (PHASE5_STATUS, Phase5BundleError, build_phase5_bundle,
                                        dump_summary as dump_phase5_summary)
from vms.reporting.phase6_bundle import (PHASE6_STATUS, Phase6BundleError, build_phase6_bundle,
                                        dump_summary as dump_phase6_summary)
from vms.reporting.value_rim_bundle import (VALUE_RIM_STATUS, ValueRimBundleError, build_value_rim_bundle,
                                           dump_value_rim_summary)
from vms.reporting.phase7_bundle import (PHASE7_STATUS, Phase7BundleError, build_phase7_bundle,
                                        dump_summary as dump_phase7_summary)
from vms.reporting.phase8_bundle import (PHASE8_STATUS, Phase8BundleError, build_phase8_bundle,
                                        dump_summary as dump_phase8_summary)
from vms.reporting.phase9_bundle import (PHASE9_STATUS, Phase9BundleError, build_phase9_bundle,
                                        dump_summary as dump_phase9_summary)
from vms.reporting.phase10_bundle import (PHASE10_STATUS, Phase10BundleError, build_phase10_bundle,
                                         dump_summary as dump_phase10_summary)
from vms.reporting.phase11_bundle import (PHASE11_STATUS, Phase11BundleError, build_phase11_bundle,
                                         dump_summary as dump_phase11_summary)
from vms.reporting.phase12_bundle import (PHASE12_STATUS, Phase12BundleError, ALL_PATTERNS,
                                         build_phase12_pattern, build_phase12_release,
                                         dump_summary as dump_phase12_summary)
from vms.reporting.bundle_validation import PHASE_CLI_SUBSETS, validate_result_bundle
from vms.schemas.contracts import ValuationTarget
from vms.profiles import classify_profile, load_overrides
from vms.profiles.fixtures import FixtureError, features_from_fixture, load_fixture
from vms.methods import build_registry_from_config
from vms.router import method_eligibility_payload, route_methods
from vms.schemas import ValuationRequest, format_validation_error
from vms.schemas.config import ConfigError, LoadedConfig, load_config
from vms.schemas.fields import FIELD_REGISTRY_VERSION
from vms.capital_allocation.policies import POLICIES
from vms.diagnostics import run_diagnostics
from vms.evaluation import RandomSplitProhibitedError, run_evaluation
from vms.evaluation.universe import load_universe
from vms.pipeline import (Phase2Run, Phase3Run, Phase4Run, Phase5Run, Phase6Run, Phase7Run, run_estimation,
                          run_path_projection, run_projection, run_returns, run_simulation, run_valuation)
from vms.regimes import RegimeModelNotImplemented
from vms.sampling import SamplingGateError
from vms.statements import CentralPathError
from vms.seeding import stream_rng

EXIT_OK, EXIT_ERROR, EXIT_INVALID, EXIT_BLOCKED, EXIT_UNSUPPORTED, EXIT_PROJECTION = 0, 1, 2, 3, 4, 5
SMOKE_STATUS = "PHASE9_SMOKE_EVAL_VIA_VMS_EVALUATE"
DETERMINISTIC_ARTIFACTS = ("request.json", "config_snapshot.json", "data_manifest.json",
                           "data_quality_report.json", "pit_snapshot.json", "state_posterior.json",
                           "driver_diagnostics.json", "statement_projection.json", "simulation_bundle.json",
                           "financial_path_bundle.json", "valuation_summary.json",
                           "return_distribution_summary.json", "sensitivity_report.json",
                           "simulation_metadata.json")


class InputError(ValueError):
    pass


def _default_config_path() -> Path:
    cwd = Path.cwd() / "config" / "default.yaml"
    if cwd.is_file():
        return cwd
    return Path(__file__).resolve().parents[3] / "config" / "default.yaml"


def dataset_hash(load: LoadResult) -> str:
    return sha256_of({"records": hash_models([*load.financial, *load.market, *load.corporate_actions,
                                              *load.classifications]),
                      "sources": {k: v.model_dump(mode="json") for k, v in sorted(load.sources.items())},
                      "corporate_actions_provided": load.corporate_actions_provided})


def _as_of(text: str) -> tuple[datetime, str]:
    try:
        return parse_as_of(text)
    except AsOfError as e:
        raise InputError(str(e)) from None


def _mode(args: argparse.Namespace, cfg: LoadedConfig) -> str:
    mode = args.mode or cfg.config.mode
    if mode == "exploratory" and not (args.override_reason or "").strip():
        raise InputError("--mode exploratory requires --override-reason '<why>' (recorded in the report)")
    if mode == "production" and args.override_reason:
        raise InputError("--override-reason is only valid with --mode exploratory")
    return mode


def _load(input_dir: str) -> LoadResult:
    res = load_directory(input_dir)
    if not res.ok:
        raise InputError("schema validation failed:\n" + "\n".join(res.errors))
    return res


def _manifest(load: LoadResult, input_dir: str, as_of: datetime, note: str, snap: PITSnapshot,
              report: DataQualityReport) -> dict:
    return {
        "input_dir": str(Path(input_dir).resolve()) if input_dir else None,
        "files": load.files,
        "data_hash": dataset_hash(load),
        "data_hash_method": "sha256 over sorted canonical-JSON records + declared sources",
        "sources_declared": {k: v.model_dump(mode="json") for k, v in sorted(load.sources.items())},
        "instrument_id": snap.instrument_id,
        "as_of": as_of.isoformat(),
        "as_of_interpretation": note,
        "as_of_rule": AS_OF_DATE_RULE,
        "field_registry_version": FIELD_REGISTRY_VERSION,
        "snapshot_version": snap.snapshot_version,
        "snapshot_hash": sha256_of(snap.model_dump(mode="json")),
        "snapshot_counts": {"financials": len(snap.financials), "market": len(snap.market),
                            "corporate_actions": len(snap.corporate_actions)},
        "excluded_post_as_of": report.excluded_post_as_of,
        "quality_status": report.status.value,
        "pit_complete": report.pit_complete,
    }


def _write_snapshot_bundle(out: Path, stamp, load, input_dir, as_of, note, snap, report, blocked: bool) -> None:
    write_artifact(out, "data_manifest.json", _manifest(load, input_dir, as_of, note, snap, report), stamp)
    write_artifact(out, "data_quality_report.json", report.model_dump(mode="json"), stamp)
    if not blocked:
        write_artifact(out, "pit_snapshot.json", snap.model_dump(mode="json"), stamp)


def _summary(report: DataQualityReport) -> dict:
    return {"instrument_id": report.instrument_id, "as_of": report.as_of.isoformat(), "status": report.status.value,
            "mode": report.mode, "pit_complete": report.pit_complete,
            "issues": {i.code: i.count for i in report.issues}, "excluded_post_as_of": report.excluded_post_as_of}


def _write_phase2(out: Path, stamp, run: Phase2Run) -> None:  # noqa: ANN001
    write_artifact(out, "driver_diagnostics.json", {
        "profile_resolution": run.resolution.model_dump(mode="json"),
        "annual_history": run.history.model_dump(mode="json"),
        "drivers": None if run.drivers is None else run.drivers.model_dump(mode="json"),
        "note": ("UNSUPPORTED_PROFILE: raw annual metrics only; generic drivers/DCF not applicable"
                 if run.drivers is None else "deterministic central values (Phase 2); distributions are Phase 3"),
    }, stamp)
    write_artifact(out, "statement_projection.json", run.projection.model_dump(mode="json"), stamp)


def _projection_exit(run: Phase2Run) -> int:
    st = run.projection.status
    if st == "UNSUPPORTED_PROFILE":
        print(f"error: {run.snapshot.instrument_id}: UNSUPPORTED_PROFILE ({run.resolution.reason})", file=sys.stderr)
        return EXIT_UNSUPPORTED
    if st != "VALID":
        detail = run.projection.missing_inputs or sorted({v.code for v in run.projection.violations})
        print(f"error: projection {st}: {detail}", file=sys.stderr)
        return EXIT_PROJECTION
    return EXIT_OK


def _p2_summary(run: Phase2Run) -> dict:
    p = run.projection
    return {"profile": run.resolution.status.value, "profile_id": run.resolution.profile_id,
            "industry": run.resolution.industry, "projection_status": p.status, "base_year": p.base_year,
            "years": p.years, "policy": (p.policy or {}).get("policy_id"),
            "violations": sorted({v.code for v in p.violations}), "flags": p.flags,
            "fcff": None if p.fcff is None else [round(v) for v in p.fcff.values]}


def _write_phase3(out: Path, stamp, run: Phase3Run, run2: Phase2Run | None = None) -> None:  # noqa: ANN001
    """state_posterior.json + driver_diagnostics.json (central values + distributions + walk-forward)."""
    if run.regimes is not None:
        r = run.regimes
        write_artifact(out, "state_posterior.json", {
            "fundamental": r.current.model_dump(mode="json"),
            "fundamental_next_year": r.next_year,
            "market": r.market.model_dump(mode="json"),
            "model": {"model_id": r.current.model_id, "model_version": r.current.model_version,
                      "inputs": "PIT_FUNDAMENTALS_ONLY", "hmm_status": r.hmm_status,
                      "config": run_cfg_regimes(run)},
            "history": [{"features": f.model_dump(mode="json"), "posterior": h.model_dump(mode="json")}
                        for f, h in zip(r.features, r.history)],
            "transitions": r.transitions.model_dump(mode="json"),
            "walk_forward": {"protocol": run.walk_forward.protocol, "summary": run.walk_forward.regime,
                             "origins": [o.regime | {"origin_year": o.origin_year,
                                                     "origin_as_of": o.origin_as_of.isoformat()}
                                         for o in run.walk_forward.origins if o.regime]},
        }, stamp)
    central = run.central if run2 is None else run2.drivers
    write_artifact(out, "driver_diagnostics.json", {
        "profile_resolution": run.resolution.model_dump(mode="json"),
        "annual_history": run.history.model_dump(mode="json"),
        "drivers": None if central is None else central.model_dump(mode="json"),
        "distributions": None if run.distributions is None else run.distributions.model_dump(mode="json"),
        "walk_forward": None if run.walk_forward is None else run.walk_forward.model_dump(mode="json"),
        "note": ("UNSUPPORTED_PROFILE: raw annual metrics only; generic drivers/DCF not applicable"
                 if run.distributions is None else
                 "Phase 3: 'drivers' = deterministic central values (Phase 2 projection); 'distributions' = "
                 "regime-conditional driver distributions with parameter uncertainty; specs selected by walk-forward"),
    }, stamp)


def run_cfg_regimes(run: Phase3Run) -> dict:
    return run.regimes.transitions.model_dump(mode="json", include={"states", "prior_alpha"})


def _p3_summary(run: Phase3Run) -> dict:
    if run.regimes is None:
        return {"profile": run.resolution.status.value}
    d = run.distributions
    return {"profile": run.resolution.status.value,
            "fundamental_regime": {k: round(v, 4) for k, v in run.regimes.current.probabilities.items()},
            "fundamental_regime_period": str(run.regimes.current.period_end),
            "market_regime": run.regimes.market.status,
            "walk_forward_origins": len(run.walk_forward.origins),
            "selected_specs": {k: v.selected_spec for k, v in d.drivers.items()},
            "low_confidence_drivers": sorted(k for k, v in d.drivers.items() if v.low_confidence)}


# ------------------------------------------------------------------ commands
def cmd_validate_data(args: argparse.Namespace) -> int:
    res = load_directory(args.input)
    out: dict = {"status": "SCHEMA_VALID" if res.ok else "SCHEMA_INVALID",
                 "financial_records": len(res.financial), "market_records": len(res.market),
                 "corporate_action_records": len(res.corporate_actions), "error_count": len(res.errors)}
    for e in res.errors:
        print(e, file=sys.stderr)
    if not res.ok:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return EXIT_INVALID
    code = EXIT_OK
    if args.as_of:
        cfg = load_config(args.config)
        mode = _mode(args, cfg)
        as_of, note = _as_of(args.as_of)
        out["as_of"], out["as_of_interpretation"] = as_of.isoformat(), note
        instruments = [args.ticker] if args.ticker else sorted({o.instrument_id for o in res.financial}
                                                               | {o.instrument_id for o in res.market})
        out["instruments"] = []
        for inst in instruments:
            _, report = assess(res, instrument_id=inst, as_of=as_of, cfg=cfg.config.quality, mode=mode,
                               override_reason=args.override_reason)
            out["instruments"].append(_summary(report))
            if report.status is QualityState.BLOCKED and mode == "production":
                code = EXIT_BLOCKED
                print(f"BLOCKED: {inst} has critical data-quality errors (production mode)", file=sys.stderr)
    else:
        out["note"] = "schema validation only; pass --as-of to build PIT snapshots and run quality gates"
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return code


def cmd_build_snapshot(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    input_dir = args.input
    if getattr(args, "provider", None) == "hithink":
        from vms.providers.hithink import HiThinkFetchError, HiThinkUnavailable, fetch_bundle
        from vms.data.io import write_directory
        data_out = Path(args.out) / "data"
        prefer_local = not bool(getattr(args, "refresh", False))
        try:
            load, diag = fetch_bundle(args.ticker, prefer_local=prefer_local)
        except (HiThinkUnavailable, HiThinkFetchError) as e:
            raise InputError(str(e)) from e
        write_directory(
            data_out, load.financial, load.market,
            corporate_actions=[], sources=list(load.sources.values()),
            fmt=getattr(args, "format", "csv") or "csv",
            classifications=load.classifications or None,
        )
        (data_out / "hithink_ingest_diagnostics.json").write_text(
            json.dumps(diag.as_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        input_dir = str(data_out)
    elif not input_dir:
        raise InputError("--input is required unless --provider hithink")
    load = _load(input_dir)
    snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode,
                          override_reason=args.override_reason)
    stamp = ArtifactStamp(run_id=content_run_id(kind="build-snapshot", instrument=args.ticker,
                                                as_of=as_of.isoformat(), data=dataset_hash(load),
                                                config=sha256_of(cfg.config.model_dump(mode="json")),
                                                mode=mode, override=args.override_reason))
    blocked = report.status is QualityState.BLOCKED and mode == "production"
    out = Path(args.out)
    _write_snapshot_bundle(out, stamp, load, input_dir, as_of, note, snap, report, blocked)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out),
                      **_summary(report)}, indent=2, ensure_ascii=False))
    try:
        gate(report)
    except GateError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    return EXIT_OK


def cmd_project(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    load = _load(args.input)
    if args.years is not None and args.years <= 0:
        raise InputError(f"--years must be > 0 (got {args.years})")
    stamp = ArtifactStamp(run_id=content_run_id(kind="project", instrument=args.ticker, as_of=as_of.isoformat(),
                                                data=dataset_hash(load),
                                                config=sha256_of({"c": cfg.config.model_dump(mode="json"),
                                                                  "p": cfg.profile.model_dump(mode="json")}),
                                                mode=mode, override=args.override_reason, policy=args.policy,
                                                years=args.years))
    out = Path(args.out)
    try:
        run = run_projection(load, instrument_id=args.ticker, as_of=as_of, loaded=cfg, policy_id=args.policy,
                             years=args.years, mode=mode, override_reason=args.override_reason)
    except GateError as e:
        snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode)
        _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, snap, report, blocked=True)
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, run.snapshot, run.report, blocked=False)
    _write_phase2(out, stamp, run)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out),
                      "label": run.projection.label, **_summary(run.report), **_p2_summary(run)},
                     indent=2, ensure_ascii=False))
    return _projection_exit(run)


def cmd_estimate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    load = _load(args.input)
    seed = cfg.config.monte_carlo.default_seed if args.seed is None else args.seed
    stamp = ArtifactStamp(run_id=content_run_id(kind="estimate", instrument=args.ticker, as_of=as_of.isoformat(),
                                                data=dataset_hash(load),
                                                config=sha256_of({"c": cfg.config.model_dump(mode="json"),
                                                                  "p": cfg.profile.model_dump(mode="json")}),
                                                mode=mode, override=args.override_reason, seed=seed))
    out = Path(args.out)
    try:
        run = run_estimation(load, instrument_id=args.ticker, as_of=as_of, loaded=cfg, seed=seed, mode=mode,
                             override_reason=args.override_reason)
    except GateError as e:
        snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode)
        _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, snap, report, blocked=True)
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, run.snapshot, run.report, blocked=False)
    _write_phase3(out, stamp, run)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out), "seed": seed,
                      **_summary(run.report), **_p3_summary(run)}, indent=2, ensure_ascii=False))
    if run.regimes is None:
        print(f"error: {args.ticker}: UNSUPPORTED_PROFILE ({run.resolution.reason})", file=sys.stderr)
        return EXIT_UNSUPPORTED
    return EXIT_OK


def _write_phase4(out: Path, stamp, run: Phase4Run) -> None:  # noqa: ANN001
    """simulation_bundle.json (+ paths.parquet when many paths)."""
    from vms.sampling import SAMPLER_VERSION
    if run.bundle is None:
        write_artifact(out, "simulation_bundle.json", {"status": "UNSUPPORTED_PROFILE", "bundle": None}, stamp)
        return
    b = run.bundle
    paths = list(b.paths)
    truncated = False
    path_cap = 500
    if len(paths) > path_cap:
        try:
            import pandas as pd
            rows = []
            for pth in paths:
                for y in pth.years:
                    rows.append({"path_id": pth.path_id, "year_index": y.year_index, "state": y.state,
                                 **{f"d_{k}": v for k, v in y.drivers.items()}})
            pd.DataFrame(rows).to_parquet(out / "paths.parquet", index=False)
        except Exception as e:  # noqa: BLE001
            write_artifact(out, "paths_write_error.json", {"error": str(e)}, stamp)
        paths = paths[:path_cap]
        truncated = True
    payload = b.model_dump(mode="json")
    payload["paths"] = [p.model_dump(mode="json") for p in paths]
    payload["paths_truncated"] = truncated
    payload["paths_embedded"] = len(paths)
    payload["paths_total_valid"] = b.diagnostics.n_paths_valid
    if truncated:
        payload["paths_parquet"] = "paths.parquet"
    write_artifact(out, "simulation_bundle.json", payload, stamp)
    write_artifact(out, "simulation_metadata.json", {
        "status": "PATHS_ONLY_NOT_A_VALUATION",
        "implemented_phase": "PHASE_4",
        "sampler_version": SAMPLER_VERSION,
        "seed": b.seed, "n_paths": b.n_paths, "n_years": b.n_years,
        "n_valid": b.diagnostics.n_paths_valid, "n_invalid": b.diagnostics.n_paths_invalid,
        "invalid_fraction": b.diagnostics.invalid_fraction,
        "parameter_snapshot": b.parameter_snapshot,
        "provenance": b.provenance,
        "dependence_method": b.dependence.method,
        "diagnostics_flags": b.diagnostics.flags,
        "warning": "Correlated driver/state paths only; no statements, DCF, WACC or returns.",
    }, stamp)


def _p4_summary(run: Phase4Run) -> dict:
    if run.bundle is None:
        return {"profile": run.resolution.status.value}
    b = run.bundle
    base = _p3_summary(run)  # duck-typed Phase3 fields
    return {**base, "sampler_version": b.sampler_version, "n_paths": b.n_paths, "n_years": b.n_years,
            "n_valid": b.diagnostics.n_paths_valid, "n_invalid": b.diagnostics.n_paths_invalid,
            "invalid_fraction": round(b.diagnostics.invalid_fraction, 4),
            "dependence_overlap_years": b.dependence.n_overlap_years,
            "seed_stable": b.diagnostics.repeated_seed_stable,
            "central_year1_state": b.central.years[0].state if b.central.years else None}


def cmd_simulate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    load = _load(args.input)
    seed = cfg.config.monte_carlo.default_seed if args.seed is None else args.seed
    paths = cfg.config.monte_carlo.default_paths if args.paths is None else args.paths
    years = args.years
    stamp = ArtifactStamp(run_id=content_run_id(kind="simulate", instrument=args.ticker, as_of=as_of.isoformat(),
                                                data=dataset_hash(load),
                                                config=sha256_of({"c": cfg.config.model_dump(mode="json"),
                                                                  "p": cfg.profile.model_dump(mode="json")}),
                                                mode=mode, override=args.override_reason, seed=seed,
                                                paths=paths, years=years))
    out = Path(args.out)
    try:
        run = run_simulation(load, instrument_id=args.ticker, as_of=as_of, loaded=cfg, seed=seed, n_paths=paths,
                             n_years=years, mode=mode, override_reason=args.override_reason)
    except GateError as e:
        snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode)
        _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, snap, report, blocked=True)
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    except SamplingGateError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_PROJECTION
    _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, run.snapshot, run.report, blocked=False)
    _write_phase3(out, stamp, run)
    _write_phase4(out, stamp, run)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out), "seed": seed,
                      **_summary(run.report), **_p4_summary(run)}, indent=2, ensure_ascii=False))
    if run.bundle is None:
        print(f"error: {args.ticker}: UNSUPPORTED_PROFILE ({run.resolution.reason})", file=sys.stderr)
        return EXIT_UNSUPPORTED
    return EXIT_OK




def _write_phase5(out: Path, stamp, run: Phase5Run) -> None:  # noqa: ANN001
    if run.financial_paths is None:
        write_artifact(out, "financial_path_bundle.json", {"status": "UNSUPPORTED_PROFILE", "bundle": None}, stamp)
        return
    fp = run.financial_paths
    # PATH-LEDGER-PARQUET-v1: full path-year ledgers to parquet; JSON stays lean
    try:
        import pandas as pd
        rows = []
        for rec in fp.paths:
            if rec.projection is None:
                continue
            for y in rec.projection.years:
                row = {"path_id": rec.path_id, "kind": rec.kind, "status": rec.status, "year": y,
                       "excluded_from_aggregates": rec.excluded_from_aggregates}
                for name, tv in rec.projection.items.items():
                    if name.endswith(f"@{y}"):
                        row[name[: -(len(str(y)) + 1)]] = tv.value
                rows.append(row)
        if rows:
            pd.DataFrame(rows).to_parquet(out / "financial_path_ledgers.parquet", index=False)
    except Exception as e:  # noqa: BLE001
        write_artifact(out, "financial_path_ledgers_error.json", {"error": str(e)}, stamp)
    payload = fp.model_dump(mode="json")
    # strip full ledgers from JSON (keep series summaries already on the record)
    for rec in payload["paths"]:
        if rec.get("projection"):
            proj = rec["projection"]
            rec["projection"] = {"status": proj["status"], "violations": proj.get("violations", []),
                                 "flags": proj.get("flags", []), "years": proj.get("years", []),
                                 "label": proj.get("label"), "base_year": proj.get("base_year"),
                                 "missing_inputs": proj.get("missing_inputs", [])}
    payload["ledgers_parquet"] = "financial_path_ledgers.parquet"
    payload["note"] = "Lean JSON summary; full path-year ledgers in financial_path_ledgers.parquet (PATH-LEDGER-PARQUET-v1)"
    write_artifact(out, "financial_path_bundle.json", payload, stamp)


def _p5_summary(run: Phase5Run) -> dict:
    if run.financial_paths is None:
        return {"profile": run.resolution.status.value}
    fp = run.financial_paths
    y0 = str(fp.years[0]) if fp.years else None
    agg = fp.aggregates.get("by_year", {}).get(y0 or "", {})
    return {**_p4_summary(run),  # type: ignore[arg-type]
            "financial_n_valid": fp.n_valid, "financial_n_failed": fp.n_failed,
            "financial_flags": fp.flags,
            "year1_fcff_mean": None if not agg.get("fcff") else round(agg["fcff"]["mean"], 4),
            "year1_fcff_per_share_p50": None if not agg.get("fcff_per_share") else round(agg["fcff_per_share"]["p50"], 6),
            "valid_path_id_hash": fp.aggregates.get("valid_path_id_hash")}


def cmd_project_paths(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    load = _load(args.input)
    seed = cfg.config.monte_carlo.default_seed if args.seed is None else args.seed
    paths = cfg.config.monte_carlo.default_paths if args.paths is None else args.paths
    years = args.years
    stamp = ArtifactStamp(run_id=content_run_id(kind="project-paths", instrument=args.ticker,
                                                as_of=as_of.isoformat(), data=dataset_hash(load),
                                                config=sha256_of({"c": cfg.config.model_dump(mode="json"),
                                                                  "p": cfg.profile.model_dump(mode="json")}),
                                                mode=mode, override=args.override_reason, seed=seed,
                                                paths=paths, years=years, policy=args.policy))
    out = Path(args.out)
    try:
        run = run_path_projection(load, instrument_id=args.ticker, as_of=as_of, loaded=cfg, seed=seed,
                                  n_paths=paths, n_years=years, policy_id=args.policy, mode=mode,
                                  override_reason=args.override_reason)
    except GateError as e:
        snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode)
        _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, snap, report, blocked=True)
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    except SamplingGateError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_PROJECTION
    except CentralPathError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_PROJECTION
    _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, run.snapshot, run.report, blocked=False)
    _write_phase3(out, stamp, run)
    _write_phase4(out, stamp, run)
    _write_phase5(out, stamp, run)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out), "seed": seed,
                      **_summary(run.report), **_p5_summary(run)}, indent=2, ensure_ascii=False))
    if run.financial_paths is None:
        print(f"error: {args.ticker}: UNSUPPORTED_PROFILE ({run.resolution.reason})", file=sys.stderr)
        return EXIT_UNSUPPORTED
    return EXIT_OK



def _write_phase6(out: Path, stamp, run: Phase6Run) -> None:  # noqa: ANN001
    if run.valuation is None:
        write_artifact(out, "valuation_summary.json", {"status": "UNSUPPORTED_PROFILE", "bundle": None}, stamp)
        return
    v = run.valuation
    # path-level valuation parquet
    try:
        import pandas as pd
        rows = []
        for pth in v.paths:
            row = {"path_id": pth.path_id, "kind": pth.kind, "status": pth.status,
                   "invalid_reason": pth.invalid_reason, "excluded": pth.excluded_from_aggregates}
            if pth.wacc_inputs:
                row.update({"wacc": pth.wacc_inputs.wacc, "ke": pth.wacc_inputs.cost_of_equity,
                            "kd": pth.wacc_inputs.cost_of_debt, "beta": pth.wacc_inputs.beta,
                            "wd": pth.wacc_inputs.weight_debt, "we": pth.wacc_inputs.weight_equity})
            if pth.dcf and pth.dcf.valid:
                row.update({"pv_fcff": pth.dcf.pv_fcff, "pv_tv": pth.dcf.pv_tv, "tv": pth.dcf.tv,
                            "tv_fraction": pth.dcf.tv_fraction, "ev_dcf": pth.dcf.enterprise_value, "g": pth.dcf.g})
            if pth.bridge_dcf and pth.bridge_dcf.valid:
                row.update({"equity_dcf": pth.bridge_dcf.equity_value, "vps_dcf": pth.bridge_dcf.value_per_share,
                            "cash": pth.bridge_dcf.cash, "debt": pth.bridge_dcf.debt,
                            "minority": pth.bridge_dcf.minority_interest_book,
                            "leases": pth.bridge_dcf.lease_debt_like, "shares": pth.bridge_dcf.diluted_shares})
            if pth.exit_multiple and pth.exit_multiple.valid:
                row.update({"ev_exit": pth.exit_multiple.enterprise_value,
                            "exit_multiple": pth.exit_multiple.multiple_used,
                            "exit_metric": pth.exit_multiple.metric_value})
            if pth.bridge_exit and pth.bridge_exit.valid:
                row.update({"equity_exit": pth.bridge_exit.equity_value, "vps_exit": pth.bridge_exit.value_per_share})
            rows.append(row)
        pd.DataFrame(rows).to_parquet(out / "path_valuations.parquet", index=False)
    except Exception as e:  # noqa: BLE001
        write_artifact(out, "path_valuations_error.json", {"error": str(e)}, stamp)
    payload = v.model_dump(mode="json")
    # keep paths lean in JSON (central full; MC without nested noise)
    slim = [payload["central"]]
    for rec in payload["paths"][1:101]:
        slim.append({k: rec[k] for k in ("path_id", "kind", "status", "invalid_reason",
                                         "excluded_from_aggregates", "flags") if k in rec})
        if rec.get("dcf"):
            slim[-1]["ev_dcf"] = rec["dcf"].get("enterprise_value")
            slim[-1]["tv_fraction"] = rec["dcf"].get("tv_fraction")
        if rec.get("bridge_dcf"):
            slim[-1]["vps_dcf"] = rec["bridge_dcf"].get("value_per_share")
            slim[-1]["equity_dcf"] = rec["bridge_dcf"].get("equity_value")
    payload["paths"] = slim
    payload["path_valuations_parquet"] = "path_valuations.parquet"
    payload["note"] = "DCF and exit-multiple kept separate unless composite_weights set; not a return product"
    write_artifact(out, "valuation_summary.json", payload, stamp)
    write_artifact(out, "simulation_metadata.json", {
        "status": "VALUATION_PATHS_NO_RETURNS",
        "implemented_phase": "PHASE_6",
        "warning": "FCFF DCF + exit-multiple + EV-equity bridge only; no entry-price returns (Phase 7).",
        "n_valid_dcf": v.n_valid_dcf, "n_failed": v.n_failed,
        "wacc": v.wacc_point.wacc, "terminal_growth": v.terminal_growth,
        "aggregates": v.aggregates, "flags": v.flags,
    }, stamp)


def _p6_summary(run: Phase6Run) -> dict:
    if run.valuation is None:
        return {"profile": run.resolution.status.value}
    v = run.valuation
    c = v.central
    return {**_p5_summary(run),  # type: ignore[arg-type]
            "wacc": None if not c.wacc_inputs else round(c.wacc_inputs.wacc, 6),
            "terminal_growth": v.terminal_growth,
            "central_ev_dcf": None if not (c.dcf and c.dcf.valid) else round(c.dcf.enterprise_value, 4),
            "central_vps_dcf": None if not (c.bridge_dcf and c.bridge_dcf.valid) else round(c.bridge_dcf.value_per_share, 6),
            "central_tv_fraction": None if not (c.dcf and c.dcf.valid) else round(c.dcf.tv_fraction, 4),
            "n_valid_dcf": v.n_valid_dcf, "n_failed_valuation": v.n_failed,
            "valuation_flags": v.flags}


def cmd_value(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    load = _load(args.input)
    seed = cfg.config.monte_carlo.default_seed if args.seed is None else args.seed
    paths = cfg.config.monte_carlo.default_paths if args.paths is None else args.paths
    years = args.years
    stamp = ArtifactStamp(run_id=content_run_id(kind="value", instrument=args.ticker, as_of=as_of.isoformat(),
                                                data=dataset_hash(load),
                                                config=sha256_of({"c": cfg.config.model_dump(mode="json"),
                                                                  "p": cfg.profile.model_dump(mode="json")}),
                                                mode=mode, override=args.override_reason, seed=seed,
                                                paths=paths, years=years, policy=args.policy))
    out = Path(args.out)
    try:
        run = run_valuation(load, instrument_id=args.ticker, as_of=as_of, loaded=cfg, seed=seed, n_paths=paths,
                            n_years=years, policy_id=args.policy, mode=mode, override_reason=args.override_reason)
    except GateError as e:
        snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode)
        _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, snap, report, blocked=True)
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    except (SamplingGateError, CentralPathError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_PROJECTION
    _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, run.snapshot, run.report, blocked=False)
    _write_phase3(out, stamp, run)
    _write_phase4(out, stamp, run)
    _write_phase5(out, stamp, run)
    _write_phase6(out, stamp, run)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out), "seed": seed,
                      **_summary(run.report), **_p6_summary(run)}, indent=2, ensure_ascii=False))
    if run.valuation is None:
        print(f"error: {args.ticker}: UNSUPPORTED_PROFILE ({run.resolution.reason})", file=sys.stderr)
        return EXIT_UNSUPPORTED
    return EXIT_OK



def _write_phase7(out: Path, stamp, run: Phase7Run) -> None:  # noqa: ANN001
    if run.returns is None:
        write_artifact(out, "return_distribution_summary.json", {"status": "UNSUPPORTED_PROFILE", "bundle": None}, stamp)
        return
    r = run.returns
    # optional path-level parquet
    try:
        import pandas as pd
        rows = [pr.model_dump(mode="json") for pr in r.path_returns]
        if rows:
            pd.DataFrame(rows).to_parquet(out / "path_returns.parquet", index=False)
    except Exception as e:  # noqa: BLE001
        write_artifact(out, "path_returns_error.json", {"error": str(e)}, stamp)
    payload = r.model_dump(mode="json")
    # lean JSON: drop bulk path_returns (parquet has them)
    payload["path_returns"] = payload["path_returns"][: min(200, len(payload["path_returns"]))]
    payload["path_returns_parquet"] = "path_returns.parquet"
    payload["path_returns_note"] = "JSON embeds at most 200 path-return rows; full grid in path_returns.parquet"
    write_artifact(out, "return_distribution_summary.json", payload, stamp)
    write_artifact(out, "simulation_metadata.json", {
        "status": "ENTRY_PRICE_RETURNS",
        "implemented_phase": "PHASE_7",
        "warning": "Entry-price returns; run vms sensitivity for Phase 8 attribution.",
        "spot_price": r.spot_price,
        "entry_prices": r.entry_prices,
        "horizons_years": r.horizons_years,
        "n_valid_paths": r.n_valid_paths,
        "dividend_treatment": r.dividend_treatment,
        "flags": r.flags,
        "valuation_ref": r.valuation_ref,
    }, stamp)


def _p7_summary(run: Phase7Run) -> dict:
    if run.returns is None:
        return {**(_p6_summary(run) if run.valuation is not None else {"profile": run.resolution.status.value})}
    r = run.returns
    # spot cell @ 1y if present
    spot_cells = [c for c in r.mixture if abs(c.relative_to_spot - 1.0) < 1e-12]
    c1 = next((c for c in spot_cells if c.horizon_years == r.horizons_years[0]), spot_cells[0] if spot_cells else None)
    return {**_p6_summary(run),  # type: ignore[arg-type]
            "spot_price": r.spot_price,
            "n_entry_prices": len(r.entry_prices),
            "horizons_years": r.horizons_years,
            "n_valid_return_paths": r.n_valid_paths,
            "spot_h1_mean_return": None if c1 is None else c1.stats.get("mean"),
            "spot_h1_p_loss": None if c1 is None else c1.stats.get("p_loss"),
            "return_flags": r.flags,
            "dividend_treatment": r.dividend_treatment}


def cmd_returns(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    load = _load(args.input)
    seed = cfg.config.monte_carlo.default_seed if args.seed is None else args.seed
    paths = cfg.config.monte_carlo.default_paths if args.paths is None else args.paths
    years = args.years
    spot = args.spot_price
    horizons = None
    if args.horizons:
        try:
            horizons = [int(h) for h in args.horizons.split(",")]
        except ValueError:
            raise InputError(f"--horizons {args.horizons!r} must be comma-separated integers") from None
    if years is None and horizons:
        years = max(horizons)
    stamp = ArtifactStamp(run_id=content_run_id(kind="returns", instrument=args.ticker, as_of=as_of.isoformat(),
                                                data=dataset_hash(load),
                                                config=sha256_of({"c": cfg.config.model_dump(mode="json"),
                                                                  "p": cfg.profile.model_dump(mode="json")}),
                                                mode=mode, override=args.override_reason, seed=seed,
                                                paths=paths, years=years, policy=args.policy,
                                                spot=spot, horizons=horizons))
    out = Path(args.out)
    try:
        run = run_returns(load, instrument_id=args.ticker, as_of=as_of, loaded=cfg, seed=seed, spot_price=spot,
                          n_paths=paths, n_years=years, policy_id=args.policy, horizons_years=horizons,
                          mode=mode, override_reason=args.override_reason)
    except GateError as e:
        snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode)
        _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, snap, report, blocked=True)
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    except (SamplingGateError, CentralPathError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_PROJECTION
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID
    _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, run.snapshot, run.report, blocked=False)
    _write_phase3(out, stamp, run)
    _write_phase4(out, stamp, run)
    _write_phase5(out, stamp, run)
    _write_phase6(out, stamp, run)
    _write_phase7(out, stamp, run)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out), "seed": seed,
                      **_summary(run.report), **_p7_summary(run)}, indent=2, ensure_ascii=False))
    if run.returns is None:
        print(f"error: {args.ticker}: UNSUPPORTED_PROFILE ({run.resolution.reason})", file=sys.stderr)
        return EXIT_UNSUPPORTED
    return EXIT_OK



def _write_phase8(out: Path, stamp, report) -> None:  # noqa: ANN001
    payload = report.model_dump(mode="json")
    # lean: drop bulky per-case valuation dict details already summarized in deltas
    write_artifact(out, "sensitivity_report.json", payload, stamp)
    write_artifact(out, "simulation_metadata.json", {
        "status": "SENSITIVITY_ATTRIBUTION",
        "implemented_phase": IMPLEMENTED_PHASE,
        "warning": "Sensitivity/attribution complete; walk-forward calibration is Phase 11 under VMS-0.2.",
        "content_hash": report.content_hash,
        "n_cases": len(report.cases),
        "flags": report.flags,
        "interval_labeling": report.interval_labeling["rule"],
    }, stamp)


def _p8_summary(report) -> dict:  # noqa: ANN001
    top = report.dominant_assumptions[:3] if report.dominant_assumptions else []
    return {
        "sensitivity_content_hash": report.content_hash,
        "n_sensitivity_cases": len(report.cases),
        "top_dimensions": [t["dimension"] for t in top],
        "tail_risk_included": "TAIL_RISK_SENSITIVITY_INCLUDED" in report.flags,
        "interval_labeling": report.interval_labeling["rule"],
    }


def cmd_sensitivity(args: argparse.Namespace) -> int:
    """Run Phase 8 diagnostics into --out (often a prior returns run directory)."""
    cfg = load_config(args.config)
    if not args.mode:
        args.mode = "exploratory"
    if args.mode == "exploratory" and not (args.override_reason or "").strip():
        args.override_reason = "phase8_sensitivity_cli"
    mode = _mode(args, cfg)
    run_dir = Path(args.run_dir) if args.run_dir else None
    out = Path(args.out) if args.out else (run_dir if run_dir else None)
    if out is None:
        raise InputError("--out is required (or pass --run-dir to write into that directory)")

    # Resolve inputs from prior run directory when provided
    ticker = args.ticker
    as_of_text = args.as_of
    input_dir = args.input
    seed = args.seed
    spot = args.spot_price
    if run_dir is not None:
        req_path = run_dir / "request.json"
        meta_path = run_dir / "simulation_metadata.json"
        if req_path.is_file():
            req = json.loads(req_path.read_text())
            body = req.get("request", req)
            ticker = ticker or body.get("instrument_id")
            as_of_text = as_of_text or (body.get("as_of") or "")[:10]
            seed = seed if seed is not None else body.get("random_seed")
            spot = spot if spot is not None else body.get("spot_price")
            if args.run_id and req.get("run_id") and args.run_id not in (req.get("run_id"), req["run_id"][:16]):
                # soft check: allow prefix match
                if not str(req.get("run_id", "")).startswith(str(args.run_id)) and args.run_id != req.get("run_id"):
                    raise InputError(f"--run-id {args.run_id} does not match request.json run_id {req.get('run_id')}")
        if input_dir is None and (run_dir / "data").is_dir():
            input_dir = str(run_dir / "data")
        if seed is None and meta_path.is_file():
            meta = json.loads(meta_path.read_text())
            seed = (meta.get("metadata") or {}).get("seed")
    if not ticker or not as_of_text or not input_dir:
        raise InputError("sensitivity requires --ticker/--as-of/--input, or a --run-dir with request.json + data/")

    if "T" in str(as_of_text):
        as_of_text = str(as_of_text)[:10]
    as_of, note = _as_of(str(as_of_text))
    load = _load(input_dir)
    seed = cfg.config.monte_carlo.default_seed if seed is None else int(seed)
    paths = cfg.config.sensitivity.n_paths if args.paths is None else args.paths
    years = args.years or max(cfg.config.horizons_years)
    stamp = ArtifactStamp(run_id=content_run_id(
        kind="sensitivity", instrument=ticker, as_of=as_of.isoformat(), data=dataset_hash(load),
        config=sha256_of({"c": cfg.config.model_dump(mode="json"), "p": cfg.profile.model_dump(mode="json")}),
        mode=mode, override=args.override_reason, seed=seed, paths=paths, years=years,
        prior_run_id=args.run_id))
    try:
        report = run_diagnostics(
            load=load, instrument_id=ticker, as_of=as_of, loaded=cfg, seed=seed,
            n_paths=paths, n_years=years, spot_price=spot, mode=mode,
            override_reason=args.override_reason)
    except GateError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    except (SamplingGateError, CentralPathError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_PROJECTION if not isinstance(e, ValueError) else EXIT_INVALID
    _write_phase8(out, stamp, report)
    print(json.dumps({"run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out),
                      "seed": seed, **_p8_summary(report)}, indent=2, ensure_ascii=False))
    return EXIT_OK



def cmd_evaluate(args: argparse.Namespace) -> int:
    from datetime import date as date_cls
    cfg = load_config(args.config)
    uni_path = Path(args.universe)
    if not uni_path.is_file():
        # allow relative to config dir / repo
        alt = Path(args.config).resolve().parent / Path(args.universe).name
        if alt.is_file():
            uni_path = alt
        else:
            raise InputError(f"universe file not found: {args.universe}")
    try:
        start = date_cls.fromisoformat(args.start)
        end = date_cls.fromisoformat(args.end)
    except ValueError as e:
        raise InputError(f"--start/--end must be YYYY-MM-DD: {e}") from None
    if end < start:
        raise InputError("--end must be >= --start")
    out = Path(args.out)
    stamp = ArtifactStamp(run_id=content_run_id(
        kind="evaluate", universe=str(uni_path), start=args.start, end=args.end,
        config=sha256_of({"c": cfg.config.model_dump(mode="json")})))
    try:
        report = run_evaluation(universe=uni_path, loaded=cfg, start=start, end=end, out_dir=out,
                                split_mode=args.split_mode)
    except RandomSplitProhibitedError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID
    # stamp evaluation_report already written by run_evaluation; add run_id
    rep_path = out / "evaluation_report.json"
    body = json.loads(rep_path.read_text())
    body = {"run_id": stamp.run_id, **body}
    rep_path.write_text(json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_artifact(out, "simulation_metadata.json", {
        "status": "WALK_FORWARD_EVALUATION",
        "implemented_phase": IMPLEMENTED_PHASE,
        "warning": "Walk-forward evaluation (Phase 11); synthetic => CALIBRATION_INSUFFICIENT / INVESTMENT_VALUE_NOT_ESTABLISHED.",
        "labels": report.labels,
        "content_hash": report.content_hash,
        "n_scored": report.n_scored,
    }, stamp)
    print(json.dumps({
        "run_id": stamp.run_id, "schema_version": SCHEMA_VERSION, "out": str(out),
        "universe_id": report.universe_id, "n_forecasts_persisted": report.n_forecasts_persisted,
        "n_scored": report.n_scored, "n_excluded_pit_incomplete": report.n_excluded_pit_incomplete,
        "labels": report.labels, "content_hash": report.content_hash,
        "baselines_present": report.baselines_present,
    }, indent=2, ensure_ascii=False))
    return EXIT_OK



def cmd_profile(args: argparse.Namespace) -> int:
    """Classify economic profile from a Phase-2 fixture (or JSON features file).

    Engineering diagnostic only — INVESTMENT_VALUE_NOT_ESTABLISHED.
    """
    data = load_fixture(args.fixture)
    features = features_from_fixture(data)
    overrides = None
    if args.overrides:
        overrides = load_overrides(args.overrides)
    elif args.config:
        ov_path = Path(args.config).resolve().parent / "profile_overrides.yaml"
        if ov_path.is_file():
            overrides = load_overrides(ov_path)
    report = classify_profile(features, overrides=overrides)
    payload = report.model_dump(mode="json")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "profile_report.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "instrument_id": report.instrument_id,
        "primary_profile": report.primary_profile.value,
        "confidence": report.confidence,
        "low_confidence": report.low_confidence,
        "flags": [f.value for f in report.flags],
        "rule_hit_ids": [h.rule_id for h in report.rule_hits],
        "missing_fields": report.missing_fields,
        "manual_override_applied": report.manual_override.applied,
        "classifier_version": report.classifier_version,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": report.investment_value,
        "out": str(args.out) if args.out else None,
    }, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_route(args: argparse.Namespace) -> int:
    """List method candidates and hard-gate outcomes without computing values."""
    try:
        target = ValuationTarget(args.target)
    except ValueError as e:
        allowed = ", ".join(t.value for t in ValuationTarget)
        raise InputError(f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}") from e
    data = load_fixture(args.fixture)
    features = features_from_fixture(data)
    overrides = None
    ov_path = Path(args.config).resolve().parent / "profile_overrides.yaml"
    if ov_path.is_file():
        overrides = load_overrides(ov_path)
    profile = classify_profile(features, overrides=overrides)
    loaded = load_config(args.config)
    registry = build_registry_from_config(loaded.method_registry)
    available = frozenset(data.get("available_fields") or [])
    report = route_methods(
        registry=registry,
        profile=profile,
        target=target,
        available_fields=available,
        attempt_value_paths=bool(args.attempt_stubs),
    )
    payload = report.model_dump(mode="json")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "route_report.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (out / "profile_report.json").write_text(
            json.dumps(profile.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        elig = method_eligibility_payload(report)
        elig["schema_version"] = SCHEMA_VERSION
        elig["implemented_phase"] = IMPLEMENTED_PHASE
        (out / "method_eligibility.json").write_text(
            json.dumps(elig, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Prove no fabricated values
    for run in report.attempted_runs:
        if run.values:
            raise RuntimeError(f"router produced values for {run.method_id}; forbidden in Phase 2")
    print(json.dumps({
        "instrument_id": report.instrument_id,
        "target": report.target.value,
        "profile_primary": report.profile_primary,
        "profile_low_confidence": report.profile_low_confidence,
        "coverage_status": report.coverage_status,
        "candidates": report.candidates,
        "eligible_count": sum(1 for e in report.eligibility if e.eligible),
        "considerations": len(report.considerations),
        "routing_deterministic": report.routing_deterministic,
        "method_status": [
            {"method_id": m.method_id, "status": m.status.value, "reason": m.reason}
            for m in report.method_status
        ],
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": report.investment_value,
        "notes": report.notes,
        "out": str(args.out) if args.out else None,
    }, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_phase0(args: argparse.Namespace) -> int:
    """VMS-0.2 Phase 0 offline demo: validate contracts and emit a provenance bundle.

    Does not classify profiles, route methods, or run DCF/returns.
    """
    try:
        horizons = None if args.horizons is None else [int(h) for h in args.horizons.split(",")]
    except ValueError:
        raise InputError(f"--horizons {args.horizons!r} must be comma-separated integers, e.g. 1,3,5") from None
    try:
        target = ValuationTarget(args.target)
    except ValueError as e:
        allowed = ", ".join(t.value for t in ValuationTarget)
        raise InputError(f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}") from e
    as_of = None
    if args.as_of:
        as_of, _ = _as_of(args.as_of)
    seed = args.seed
    paths = args.paths
    loaded = load_config(args.config)
    if seed is None:
        seed = loaded.config.monte_carlo.default_seed
    if paths is None:
        paths = min(100, loaded.config.monte_carlo.default_paths)
    summary = build_phase0_bundle(
        out_dir=args.out,
        config_path=args.config,
        seed=seed,
        paths=paths,
        as_of=as_of,
        target=target,
        horizons_years=horizons,
        data_format=args.format,
    )
    print(dump_summary(summary), end="")
    assert summary["status"] == PHASE0_STATUS
    return EXIT_OK



def cmd_phase3(args: argparse.Namespace) -> int:
    """Synthetic mature-operating path bundle (drivers/regimes/statements). NOT a valuation."""
    as_of = None
    if args.as_of:
        as_of, _ = _as_of(args.as_of)
    seed = args.seed
    paths = args.paths
    loaded = load_config(args.config)
    if seed is None:
        seed = loaded.config.monte_carlo.default_seed
    if paths is None:
        paths = min(80, loaded.config.monte_carlo.default_paths)
    years = 4 if args.years is None else args.years
    summary = build_phase3_bundle(
        out_dir=args.out,
        config_path=args.config,
        seed=seed,
        paths=paths,
        years=years,
        as_of=as_of,
        policy_id=args.policy,
        data_format=args.format,
    )
    print(dump_phase3_summary(summary), end="")
    assert summary["status"] == PHASE3_STATUS
    return EXIT_OK


def cmd_phase4(args: argparse.Namespace) -> int:
    """Synthetic mature-operating FCFF/FCFE/DDM via router. NOT investment advice."""
    as_of = None
    if args.as_of:
        as_of, _ = _as_of(args.as_of)
    seed = args.seed
    paths = args.paths
    loaded = load_config(args.config)
    if seed is None:
        seed = loaded.config.monte_carlo.default_seed
    if paths is None:
        paths = min(40, loaded.config.monte_carlo.default_paths)
    years = 4 if args.years is None else args.years
    try:
        target = ValuationTarget(args.target)
    except ValueError as e:
        allowed = ", ".join(t.value for t in ValuationTarget)
        raise InputError(f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}") from e
    try:
        summary = build_phase4_bundle(
            out_dir=args.out,
            config_path=args.config,
            seed=seed,
            paths=paths,
            years=years,
            as_of=as_of,
            policy_id=args.policy,
            data_format=args.format,
            target=target,
        )
    except Phase4BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID
    print(dump_phase4_summary(summary), end="")
    assert summary["status"] == PHASE4_STATUS
    return EXIT_OK


def cmd_phase5(args: argparse.Namespace) -> int:
    """Synthetic relative multiples (P/E, P/B, EV/*) via router. NOT investment advice."""
    as_of = None
    if args.as_of:
        as_of, _ = _as_of(args.as_of)
    seed = args.seed
    paths = args.paths
    loaded = load_config(args.config)
    if seed is None:
        seed = loaded.config.monte_carlo.default_seed
    if paths is None:
        paths = min(20, loaded.config.monte_carlo.default_paths)
    years = 3 if args.years is None else args.years
    try:
        target = ValuationTarget(args.target)
    except ValueError as e:
        allowed = ", ".join(t.value for t in ValuationTarget)
        raise InputError(f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}") from e
    try:
        summary = build_phase5_bundle(
            out_dir=args.out,
            config_path=args.config,
            seed=seed,
            paths=paths,
            years=years,
            as_of=as_of,
            policy_id=args.policy,
            data_format=args.format,
            target=target,
            include_cashflow=not args.multiples_only,
        )
    except Phase5BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID
    print(dump_phase5_summary(summary), end="")
    assert summary["status"] == PHASE5_STATUS
    return EXIT_OK



def cmd_value_rim(args: argparse.Namespace) -> int:
    """Real PIT → residual income (R1/R2 FINANCIAL_INSTITUTION bridge). NOT investment advice."""
    cfg = load_config(args.config)
    mode = _mode(args, cfg)
    as_of, note = _as_of(args.as_of)
    load = _load(args.input)
    years = args.years
    zeros_explicit = bool(getattr(args, "zeros_explicit", True))
    if getattr(args, "no_zeros_explicit", False):
        zeros_explicit = False
    equity_basis = getattr(args, "equity_basis", "common") or "common"
    run_distribution = not bool(getattr(args, "no_distribution", False))
    n_paths = getattr(args, "paths", None)
    seed = getattr(args, "seed", None)
    ke_grid = None
    if getattr(args, "ke_grid", None):
        try:
            ke_grid = [float(x) for x in str(args.ke_grid).split(",") if str(x).strip()]
        except ValueError as e:
            raise InputError(f"--ke-grid must be comma-separated floats: {args.ke_grid!r}") from e
    target = None
    if args.target:
        try:
            target = ValuationTarget(args.target)
        except ValueError as e:
            allowed = ", ".join(t.value for t in ValuationTarget)
            raise InputError(
                f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}"
            ) from e
    try:
        summary = build_value_rim_bundle(
            out_dir=args.out,
            load=load,
            input_dir=args.input,
            instrument_id=args.ticker,
            as_of=as_of,
            as_of_note=note,
            loaded=cfg,
            mode=mode,
            override_reason=args.override_reason,
            years=years,
            zeros_explicit=zeros_explicit,
            target=target,
            equity_basis=equity_basis,
            run_distribution=run_distribution,
            n_paths=n_paths,
            seed=seed,
            ke_grid=ke_grid,
            auto_fi_peers=not bool(getattr(args, "no_auto_fi_peers", False)),
        )
    except GateError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    except ValueRimBundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID
    print(dump_value_rim_summary(summary), end="")
    assert summary["status"] == VALUE_RIM_STATUS
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    return EXIT_OK


def cmd_phase6(args: argparse.Namespace) -> int:
    """Synthetic RIM/NAV/SOTP via router. NOT investment advice."""
    as_of = None
    if args.as_of:
        as_of, _ = _as_of(args.as_of)
    seed = args.seed
    loaded = load_config(args.config)
    if seed is None:
        seed = loaded.config.monte_carlo.default_seed
    target = None
    if args.target:
        try:
            target = ValuationTarget(args.target)
        except ValueError as e:
            allowed = ", ".join(t.value for t in ValuationTarget)
            raise InputError(
                f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}"
            ) from e
    try:
        summary = build_phase6_bundle(
            out_dir=args.out,
            config_path=args.config,
            seed=seed,
            as_of=as_of,
            fixture=args.fixture,
            target=target,
        )
    except Phase6BundleError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID
    print(dump_phase6_summary(summary), end="")
    assert summary["status"] == PHASE6_STATUS
    return EXIT_OK


def cmd_phase7(args: argparse.Namespace) -> int:
    """Synthetic router hardening + method comparison. NOT investment advice."""
    try:
        target = ValuationTarget(args.target) if args.target else None
    except ValueError as e:
        allowed = ", ".join(tv.value for tv in ValuationTarget)
        raise InputError(f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}") from e
    out = Path(args.out)
    seed = 42 if args.seed is None else int(args.seed)
    try:
        summary = build_phase7_bundle(
            out,
            config_path=args.config,
            seed=seed,
            as_of=args.as_of,
            fixture=args.fixture,
            target=target,
            force_no_eligible=bool(args.force_no_eligible),
            request_blend=bool(args.request_blend),
        )
    except Phase7BundleError as e:
        raise InputError(str(e)) from e
    print(dump_phase7_summary(summary), end="")
    assert summary["status"] == PHASE7_STATUS
    return EXIT_OK


def cmd_compare_methods(args: argparse.Namespace) -> int:
    """Emit method_comparison.json (disagreement; no calibrated blend)."""
    try:
        target = ValuationTarget(args.target) if args.target else None
    except ValueError as e:
        allowed = ", ".join(tv.value for tv in ValuationTarget)
        raise InputError(f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}") from e
    out = Path(args.out)
    seed = 42 if args.seed is None else int(args.seed)
    try:
        summary = build_phase7_bundle(
            out,
            config_path=args.config,
            seed=seed,
            as_of=args.as_of,
            fixture=args.fixture,
            target=target,
            force_no_eligible=False,
            request_blend=bool(args.request_blend),
        )
    except Phase7BundleError as e:
        raise InputError(str(e)) from e
    print(json.dumps({
        "status": PHASE7_STATUS,
        "schema_version": summary["schema_version"],
        "implemented_phase": summary["implemented_phase"],
        "investment_value": summary["investment_value"],
        "run_id": summary["run_id"],
        "out": summary["out"],
        "coverage_status": summary["coverage_status"],
        "disagreement": summary["disagreement"],
        "ensemble_status": summary["ensemble_status"],
        "combined_value": summary["combined_value"],
        "incompatible_demo_compatible": summary["incompatible_demo_compatible"],
    }, indent=2, sort_keys=True))
    return EXIT_OK


def cmd_phase8(args: argparse.Namespace) -> int:
    """Synthetic ensemble + model uncertainty. NOT investment advice."""
    try:
        target = ValuationTarget(args.target) if args.target else None
    except ValueError as e:
        allowed = ", ".join(tv.value for tv in ValuationTarget)
        raise InputError(f"--target {args.target!r} is not a ValuationTarget; expected one of: {allowed}") from e
    out = Path(args.out)
    seed = 42 if args.seed is None else int(args.seed)
    n_draws = 1000 if args.n_draws is None else int(args.n_draws)
    try:
        summary = build_phase8_bundle(
            out,
            config_path=args.config,
            seed=seed,
            as_of=args.as_of,
            fixture=args.fixture,
            target=target,
            n_draws=n_draws,
        )
    except Phase8BundleError as e:
        raise InputError(str(e)) from e
    print(dump_phase8_summary(summary), end="")
    assert summary["status"] == PHASE8_STATUS
    assert summary["calibrated_claim"] is False
    return EXIT_OK



def cmd_phase9(args: argparse.Namespace) -> int:
    """Synthetic market-pricing + exit prices. NOT investment advice."""
    out = Path(args.out)
    seed = 42 if args.seed is None else int(args.seed)
    paths = 40 if args.paths is None else int(args.paths)
    years = 4 if args.years is None else int(args.years)
    horizons = None
    if args.horizons is not None:
        try:
            horizons = [int(h) for h in args.horizons.split(",")]
        except ValueError:
            raise InputError(f"--horizons {args.horizons!r} must be comma-separated integers") from None
    as_of = None
    if args.as_of:
        as_of, _ = parse_as_of(args.as_of)
    try:
        summary = build_phase9_bundle(
            out_dir=out,
            config_path=args.config,
            seed=seed,
            paths=paths,
            years=years,
            as_of=as_of,
            metric_id=args.metric,
            horizons=horizons,
            include_convergence_demo=not args.no_convergence_demo,
        )
    except Phase9BundleError as e:
        raise InputError(str(e)) from e
    print(dump_phase9_summary(summary), end="")
    assert summary["status"] == PHASE9_STATUS
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["default_silent_intrinsic_copy_detected"] is False
    return EXIT_OK




def cmd_phase10(args: argparse.Namespace) -> int:
    """Synthetic Track B returns from exit prices. NOT investment advice."""
    out = Path(args.out)
    seed = 42 if args.seed is None else int(args.seed)
    paths = 40 if args.paths is None else int(args.paths)
    years = 4 if args.years is None else int(args.years)
    horizons = None
    if args.horizons is not None:
        try:
            horizons = [int(h) for h in args.horizons.split(",")]
        except ValueError:
            raise InputError(f"--horizons {args.horizons!r} must be comma-separated integers") from None
    user_prices = None
    if getattr(args, "entry_prices", None):
        try:
            user_prices = [float(x) for x in args.entry_prices.split(",")]
        except ValueError:
            raise InputError(f"--entry-prices {args.entry_prices!r} must be comma-separated floats") from None
    as_of = None
    if args.as_of:
        as_of, _ = parse_as_of(args.as_of)
    spot = None if args.spot is None else float(args.spot)
    try:
        summary = build_phase10_bundle(
            out_dir=out,
            config_path=args.config,
            seed=seed,
            paths=paths,
            years=years,
            as_of=as_of,
            metric_id=args.metric,
            horizons=horizons,
            spot_price=spot,
            user_entry_prices=user_prices,
            notify_dsde=bool(getattr(args, "notify_dsde", False)),
        )
    except Phase10BundleError as e:
        raise InputError(str(e)) from e
    print(dump_phase10_summary(summary), end="")
    assert summary["status"] == PHASE10_STATUS
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["dsde_required_for_core"] is False
    assert summary["pathwise_higher_p0_cannot_improve"] is True
    return EXIT_OK


def cmd_phase11(args: argparse.Namespace) -> int:
    """Synthetic walk-forward + sensitivity. NOT investment advice."""
    from datetime import date as date_cls
    out = Path(args.out)
    seed = 42 if args.seed is None else int(args.seed)
    start = date_cls.fromisoformat(args.start) if args.start else date_cls(2018, 1, 1)
    end = date_cls.fromisoformat(args.end) if args.end else date_cls(2022, 12, 31)
    if end < start:
        raise InputError("--end must be >= --start")
    uni = args.universe
    sens_paths = 20 if args.paths is None else int(args.paths)
    try:
        summary = build_phase11_bundle(
            out_dir=out,
            config_path=args.config,
            universe_path=uni,
            start=start,
            end=end,
            seed=seed,
            sensitivity_paths=sens_paths,
            sensitivity_years=int(args.years) if args.years is not None else 3,
            skip_sensitivity=bool(getattr(args, "skip_sensitivity", False)),
        )
    except Phase11BundleError as e:
        raise InputError(str(e)) from e
    print(dump_phase11_summary(summary), end="")
    assert summary["status"] == PHASE11_STATUS
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert (out / "evaluation_report.json").is_file()
    if not getattr(args, "skip_sensitivity", False):
        assert (out / "sensitivity_report.json").is_file()
    return EXIT_OK


def cmd_phase12(args: argparse.Namespace) -> int:
    """Five-pattern offline release examples. NOT investment advice."""
    out = Path(args.out)
    seed = 42 if args.seed is None else int(args.seed)
    paths = 20 if args.paths is None else int(args.paths)
    years = 3 if args.years is None else int(args.years)
    pattern = getattr(args, "pattern", None)
    try:
        if pattern:
            if pattern not in ALL_PATTERNS:
                raise InputError(f"--pattern must be one of {ALL_PATTERNS}")
            summary = build_phase12_pattern(
                out_dir=out,
                pattern=pattern,
                config_path=args.config,
                seed=seed,
                paths=paths,
                years=years,
                spot_price=None if args.spot is None else float(args.spot),
            )
        else:
            selected = None
            if getattr(args, "patterns", None):
                selected = [p.strip() for p in args.patterns.split(",") if p.strip()]
                bad = [p for p in selected if p not in ALL_PATTERNS]
                if bad:
                    raise InputError(f"unknown patterns {bad}; choose from {ALL_PATTERNS}")
            summary = build_phase12_release(
                out_dir=out,
                config_path=args.config,
                seed=seed,
                paths=paths,
                years=years,
                patterns=selected,
            )
    except Phase12BundleError as e:
        raise InputError(str(e)) from e
    print(dump_phase12_summary(summary), end="")
    assert summary["status"] == PHASE12_STATUS
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert summary["labels"]["INVESTMENT_VALUE_SUPPORTED"] is False
    return EXIT_OK


def cmd_validate_bundle(args: argparse.Namespace) -> int:
    """Validate a result-bundle directory (SPEC §16.3 subsets)."""
    root = Path(args.path)
    subset = args.subset or "phase12"
    if subset != "section_16_3" and subset not in PHASE_CLI_SUBSETS:
        raise InputError(
            f"unknown --subset {subset!r}; known={sorted(PHASE_CLI_SUBSETS)} or section_16_3"
        )
    res = validate_result_bundle(root, subset=subset)
    print(json.dumps(res.to_dict(), indent=2, sort_keys=True))
    return EXIT_OK if res.ok else EXIT_INVALID


def cmd_demo(args: argparse.Namespace) -> int:
    loaded = load_config(args.config)
    cfg = loaded.config
    mode = _mode(args, loaded)
    seed = cfg.monte_carlo.default_seed if args.seed is None else args.seed
    paths = cfg.monte_carlo.default_paths if args.paths is None else args.paths
    try:
        horizons = cfg.horizons_years if args.horizons is None else [int(h) for h in args.horizons.split(",")]
    except ValueError:
        raise InputError(f"--horizons {args.horizons!r} must be comma-separated integers, e.g. 1,3,5") from None
    as_of, as_of_note = _as_of(args.as_of)
    if paths <= 0:
        raise InputError(f"request: monte_carlo_paths: must be > 0 (got {paths})")

    out = Path(args.out)
    data_dir = out / "data"
    fin, mkt, actions = synthetic.generate(seed)
    write_directory(data_dir, fin, mkt, actions, synthetic.source_descriptors(), fmt=args.format,
                    classifications=synthetic.classifications())
    load = _load(str(data_dir))  # round-trip through the same ingestion users get
    snap, report = assess(load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, cfg=cfg.quality,
                          mode=mode, override_reason=args.override_reason)
    blocked = report.status is QualityState.BLOCKED and mode == "production"
    run = None if blocked else run_projection(load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of,
                                              loaded=loaded, policy_id=args.policy, years=max(horizons), mode=mode,
                                              override_reason=args.override_reason)
    if not snap.market:
        raise InputError(f"no synthetic market observation at or before as_of={as_of.isoformat()}")
    spot = snap.market[-1].raw_close
    try:
        request = ValuationRequest(instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, spot_price=spot,
                                   horizons_years=horizons, monte_carlo_paths=paths, random_seed=seed,
                                   configuration_version=cfg.configuration_version)
    except ValidationError as e:
        raise InputError(format_validation_error(e, "request")) from None

    data_hash = dataset_hash(load)
    config_snapshot = {"config": cfg.model_dump(mode="json"), "driver_profile": loaded.profile.model_dump(mode="json")}
    meta = make_run_metadata(request=request, config_snapshot=config_snapshot, data_hash=data_hash,
                             seed=seed, paths=paths)
    write_artifact(out, "request.json", {"request": request.model_dump(mode="json"),
                                         "as_of_interpretation": as_of_note, "as_of_rule": AS_OF_DATE_RULE}, meta)
    write_artifact(out, "config_snapshot.json", config_snapshot, meta)
    _write_snapshot_bundle(out, meta, load, None, as_of, as_of_note, snap, report, blocked)
    run3 = None
    run_sens = None
    if run is not None:
        _write_phase2(out, meta, run)
        run7 = run_returns(load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, loaded=loaded,
                             seed=seed, n_paths=min(paths, 100), n_years=max(horizons), spot_price=spot,
                             policy_id=args.policy, horizons_years=horizons, mode=mode,
                             override_reason=args.override_reason)
        _write_phase3(out, meta, run7, run)
        _write_phase4(out, meta, run7)
        _write_phase5(out, meta, run7)
        _write_phase6(out, meta, run7)
        _write_phase7(out, meta, run7)
        # Phase 8 smoke: small-path sensitivity into the same out dir
        sens = run_diagnostics(
            load=load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, loaded=loaded,
            seed=seed, n_paths=min(paths, 40), n_years=max(horizons), spot_price=spot,
            baseline=run7, mode=mode,
            override_reason=args.override_reason or "phase8_demo_smoke")
        _write_phase8(out, meta, sens)
        run3 = run7
        run4 = run7
        run5 = run7
        run_sens = sens
    else:
        run4 = None
    smoke = stream_rng(seed, "phase0_smoke").standard_normal(5)
    write_artifact(out, "simulation_metadata.json", {
        "status": SMOKE_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "warning": "Smoke artifact through Phase 8; run vms evaluate for Phase 9 walk-forward.",
        "data_label": "SYNTHETIC — not real market data",
        "quality_status": report.status.value,
        "metadata": meta.model_dump(mode="json"),
        "rng_smoke_check": {"stream": "phase0_smoke", "first_5_standard_normal": [round(float(x), 12) for x in smoke],
                            "purpose": "proves seed determinism only"},
        **({} if run4 is None or run4.bundle is None else {
            "sampler_version": run4.bundle.sampler_version,
            "n_paths_simulated": run4.bundle.n_paths,
            "n_valid": run4.bundle.diagnostics.n_paths_valid,
        }),
    }, meta)
    write_artifact(out, "run_context.json", {"created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
                                             "deterministic_artifacts": list(DETERMINISTIC_ARTIFACTS)}, meta)
    print(json.dumps({"status": SMOKE_STATUS, "quality_status": report.status.value,
                      **({} if run is None else _p2_summary(run)),
                      **({} if run3 is None else {"phase3": _p3_summary(run3)}),
                      **({} if run4 is None else {"phase4": _p4_summary(run4)}),
                      **({} if run4 is None or not isinstance(run4, (Phase5Run, Phase6Run, Phase7Run)) else {"phase5": _p5_summary(run4)}),
                      **({} if not isinstance(run4, (Phase6Run, Phase7Run)) else {"phase6": _p6_summary(run4)}),
                      **({} if not isinstance(run4, Phase7Run) else {"phase7": _p7_summary(run4)}),
                      **({} if run_sens is None else {"phase8": _p8_summary(run_sens)}),
                      "run_id": meta.run_id,
                      "schema_version": SCHEMA_VERSION, "out": str(out), "spot_price": spot, "seed": seed,
                      "paths": paths, "data_hash": data_hash[:16], "config_hash": meta.config_hash[:16],
                      "git_sha": meta.code_version["git_sha"][:12]}, indent=2))
    try:
        gate(report)
    except GateError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    return _projection_exit(run)


# ------------------------------------------------------------------ parser
def _gate_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default=str(_default_config_path()))
    p.add_argument("--mode", choices=["production", "exploratory"], help="default: config 'mode'")
    p.add_argument("--override-reason", help="required with --mode exploratory; recorded in the report")



def cmd_ingest_hithink(args: argparse.Namespace) -> int:
    """Fetch HiThink+EM NOTICE bundle and write canonical CSV/Parquet + sources.yaml."""
    from vms.providers.hithink import HiThinkFetchError, HiThinkUnavailable, fetch_bundle
    from vms.data.io import write_directory

    prefer_local = not bool(getattr(args, "refresh", False))
    if getattr(args, "prefer_local", None) is True:
        prefer_local = True
    if getattr(args, "prefer_local", None) is False and getattr(args, "refresh", False):
        prefer_local = False
    # argparse: --prefer-local / --refresh mutually
    if getattr(args, "refresh", False):
        prefer_local = False
    try:
        load, diag = fetch_bundle(
            args.ticker,
            prefer_local=prefer_local,
            min_local=args.min_local,
            start=None if not args.start else __import__("datetime").date.fromisoformat(args.start),
            end=None if not args.end else __import__("datetime").date.fromisoformat(args.end),
        )
    except (HiThinkUnavailable, HiThinkFetchError) as e:
        raise InputError(str(e)) from e
    out = Path(args.out)
    write_directory(
        out, load.financial, load.market,
        corporate_actions=load.corporate_actions if load.corporate_actions_provided else [],
        sources=list(load.sources.values()),
        fmt=args.format,
        classifications=load.classifications or None,
    )
    # Always write empty CA file marker? write_directory with empty list still writes file.
    # Write diagnostics (redacted)
    (out / "hithink_ingest_diagnostics.json").write_text(
        json.dumps(diag.as_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ticker": args.ticker,
        "out": str(out),
        "n_financial": len(load.financial),
        "n_market": len(load.market),
        "n_corporate_actions": len(load.corporate_actions),
        "n_classifications": len(load.classifications),
        "n_market_with_shares": sum(1 for m in load.market if m.shares_outstanding is not None),
        "n_sources": len(load.sources),
        "prefer_local": prefer_local,
        "pit_complete_expected": False,
        "source_id": "hithink_em_notice",
        "versioning": "LATEST_ONLY",
        "notice_joined": diag.notice_joined,
        "notice_fallback": diag.notice_fallback,
        "industry": diag.industry,
        "corporate_actions": diag.corporate_actions,
        "shares_outstanding": diag.shares_outstanding,
        "assumptions": diag.assumptions,
    }, indent=2, ensure_ascii=False, sort_keys=True))
    return EXIT_OK



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vms", description="VMS-0.1 valuation engine (Phases 0–10 + HiThink A-share ingest)")
    sub = p.add_subparsers(dest="command", required=True)
    asof_help = "YYYY-MM-DD (=> 15:00 Asia/Shanghai, rule ASOF-DATE-CLOSE-v1) or ISO-8601 with offset"

    v = sub.add_parser("validate-data", help="schema validation; with --as-of also PIT + quality gates")
    v.add_argument("--input", required=True, help="directory with canonical CSV/Parquet tables")
    v.add_argument("--as-of", help=asof_help)
    v.add_argument("--ticker", help="limit to one instrument_id (default: all)")
    _gate_args(v)
    v.set_defaults(func=cmd_validate_data)

    b = sub.add_parser("build-snapshot", help="PIT snapshot + quality report for one instrument")
    b.add_argument("--input", help="directory with canonical CSV/Parquet (required unless --provider hithink)")
    b.add_argument("--provider", choices=["hithink"], help="optional: ingest via provider then snapshot")
    b.add_argument("--ticker", required=True, help="instrument_id, e.g. 000001.SZ or 600519.SH")
    b.add_argument("--as-of", required=True, help=asof_help)
    b.add_argument("--out", required=True)
    b.add_argument("--refresh", action="store_true", help="with --provider hithink: allow Recipe E REST")
    b.add_argument("--format", choices=["csv", "parquet"], default="csv",
                   help="when --provider hithink writes data under <out>/data")
    _gate_args(b)
    b.set_defaults(func=cmd_build_snapshot)

    pj = sub.add_parser("project", help="deterministic central-case statements (Phase 2; not a valuation)")
    pj.add_argument("--input", required=True)
    pj.add_argument("--ticker", required=True)
    pj.add_argument("--as-of", required=True, help=asof_help)
    pj.add_argument("--out", required=True)
    pj.add_argument("--years", type=int, help="projection years (default: config projection.default_years)")
    pj.add_argument("--policy", choices=sorted(POLICIES), help="capital-allocation policy (default: config)")
    _gate_args(pj)
    pj.set_defaults(func=cmd_project)

    es = sub.add_parser("estimate", help="fundamental regimes + driver distributions (Phase 3; not a valuation)")
    es.add_argument("--input", required=True)
    es.add_argument("--ticker", required=True)
    es.add_argument("--as-of", required=True, help=asof_help)
    es.add_argument("--out", required=True)
    es.add_argument("--seed", type=int, help="parameter-bootstrap seed (default: config monte_carlo.default_seed)")
    _gate_args(es)
    es.set_defaults(func=cmd_estimate)

    sm = sub.add_parser("simulate", help="correlated driver/state paths (Phase 4; not a valuation)")
    sm.add_argument("--input", required=True)
    sm.add_argument("--ticker", required=True)
    sm.add_argument("--as-of", required=True, help=asof_help)
    sm.add_argument("--out", required=True)
    sm.add_argument("--seed", type=int)
    sm.add_argument("--paths", type=int, help="Monte Carlo paths (default: config monte_carlo.default_paths)")
    sm.add_argument("--years", type=int, help="projection years (default: max horizons_years)")
    _gate_args(sm)
    sm.set_defaults(func=cmd_simulate)

    pp = sub.add_parser("project-paths", help="path-wise statements + capital allocation (Phase 5; not a valuation)")
    pp.add_argument("--input", required=True)
    pp.add_argument("--ticker", required=True)
    pp.add_argument("--as-of", required=True, help=asof_help)
    pp.add_argument("--out", required=True)
    pp.add_argument("--seed", type=int)
    pp.add_argument("--paths", type=int)
    pp.add_argument("--years", type=int)
    pp.add_argument("--policy", choices=sorted(POLICIES), help="capital-allocation policy")
    _gate_args(pp)
    pp.set_defaults(func=cmd_project_paths)




    evl = sub.add_parser("evaluate", help="chronological walk-forward evaluation (Phase 11 / SPEC §17)")
    evl.add_argument("--universe", required=True, help="universe YAML (e.g. config/universe.synthetic.yaml)")
    evl.add_argument("--start", required=True, help="YYYY-MM-DD")
    evl.add_argument("--end", required=True, help="YYYY-MM-DD")
    evl.add_argument("--out", required=True)
    evl.add_argument("--split-mode", default=None,
                     help="must be chronological if set; random splits are rejected")
    _gate_args(evl)
    evl.set_defaults(func=cmd_evaluate)

    sen = sub.add_parser("sensitivity", help="sensitivity & uncertainty attribution (Phase 8)")
    sen.add_argument("--run-dir", help="prior run directory (request.json + data/); writes sensitivity_report.json here if --out omitted")
    sen.add_argument("--run-id", help="optional: verify against request.json run_id")
    sen.add_argument("--input", help="data directory (default: <run-dir>/data)")
    sen.add_argument("--ticker")
    sen.add_argument("--as-of", help=asof_help)
    sen.add_argument("--out", help="output directory (default: --run-dir)")
    sen.add_argument("--seed", type=int)
    sen.add_argument("--paths", type=int, help="paths per sensitivity case (default: config sensitivity.n_paths)")
    sen.add_argument("--years", type=int)
    sen.add_argument("--spot-price", type=float)
    _gate_args(sen)
    sen.set_defaults(func=cmd_sensitivity)

    rt = sub.add_parser("returns", help="entry-price-conditioned multi-horizon returns (Phase 7)")
    rt.add_argument("--input", required=True)
    rt.add_argument("--ticker", required=True)
    rt.add_argument("--as-of", required=True, help=asof_help)
    rt.add_argument("--out", required=True)
    rt.add_argument("--seed", type=int)
    rt.add_argument("--paths", type=int)
    rt.add_argument("--years", type=int, help="forecast years (default: max horizons)")
    rt.add_argument("--horizons", help="comma-separated horizons, e.g. 1,3,5")
    rt.add_argument("--spot-price", type=float, help="override spot; default last PIT close")
    rt.add_argument("--policy", choices=sorted(POLICIES))
    _gate_args(rt)
    rt.set_defaults(func=cmd_returns)

    vl = sub.add_parser("value", help="Legacy 0.1 FCFF pipeline (not VMS-0.2 router; prefer phase4)")
    vl.add_argument("--input", required=True)
    vl.add_argument("--ticker", required=True)
    vl.add_argument("--as-of", required=True, help=asof_help)
    vl.add_argument("--out", required=True)
    vl.add_argument("--seed", type=int)
    vl.add_argument("--paths", type=int)
    vl.add_argument("--years", type=int)
    vl.add_argument("--policy", choices=sorted(POLICIES))
    _gate_args(vl)
    vl.set_defaults(func=cmd_value)


    ih = sub.add_parser("ingest-hithink", help="HiThink+EM NOTICE → canonical LoadResult files (real A-share)")
    ih.add_argument("--ticker", required=True, help="thscode e.g. 600519.SH")
    ih.add_argument("--out", required=True, help="output directory for financial/market/sources.yaml")
    ih.add_argument("--format", choices=["csv", "parquet"], default="csv")
    ih.add_argument("--prefer-local", dest="prefer_local", action="store_true", default=True)
    ih.add_argument("--refresh", action="store_true", help="allow Recipe E REST upsert on miss (not silent vendor swap)")
    ih.add_argument("--min-local", type=int, default=4, help="local statement rows to skip REST")
    ih.add_argument("--start", help="optional YYYY-MM-DD filter / price window start")
    ih.add_argument("--end", help="optional YYYY-MM-DD filter / price window end")
    ih.set_defaults(func=cmd_ingest_hithink)

    
    pr = sub.add_parser("profile", help="VMS-0.2 Phase 2 economic-profile classifier (NOT a valuation)")
    pr.add_argument("--fixture", required=True, help="path to profile fixture JSON")
    pr.add_argument("--out", help="optional directory for profile_report.json")
    pr.add_argument("--overrides", help="optional profile_overrides.yaml")
    pr.add_argument("--config", default=str(_default_config_path()),
                    help="config path (used to locate sibling profile_overrides.yaml)")
    pr.set_defaults(func=cmd_profile)

    rt = sub.add_parser("route", help="VMS-0.2 Phase 7 routing log + soft suitability (no method math by default)")
    rt.add_argument("--fixture", required=True, help="path to profile fixture JSON")
    rt.add_argument("--target", default=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT.value)
    rt.add_argument("--out", help="optional directory for route_report.json + method_eligibility.json")
    rt.add_argument("--attempt-stubs", action="store_true",
                    help="invoke stub value_paths to prove hard refusal (still no values)")
    rt.add_argument("--config", default=str(_default_config_path()))
    rt.set_defaults(func=cmd_route)

    p0 = sub.add_parser("phase0", help="VMS-0.2 Phase 0 contracts baseline (synthetic; NOT a valuation)")
    p0.add_argument("--out", required=True)
    p0.add_argument("--seed", type=int)
    p0.add_argument("--paths", type=int, help="recorded in request; no MC valuation in Phase 0")
    p0.add_argument("--horizons", help="comma-separated years, e.g. 1,3,5")
    p0.add_argument("--as-of", default="2025-06-30", help=asof_help)
    p0.add_argument("--target", default=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT.value,
                    help="ValuationTarget enum value (SPEC §10.1)")
    p0.add_argument("--format", choices=["csv", "parquet"], default="csv")
    p0.add_argument("--config", default=str(_default_config_path()))
    p0.set_defaults(func=cmd_phase0)

    p3 = sub.add_parser("phase3", help="VMS-0.2 Phase 3 path bundle (synthetic; NOT a valuation)")
    p3.add_argument("--out", required=True)
    p3.add_argument("--seed", type=int)
    p3.add_argument("--paths", type=int, help="Monte Carlo paths (default: min(80, config))")
    p3.add_argument("--years", type=int, help="projection years (default: 4)")
    p3.add_argument("--policy", choices=sorted(POLICIES), help="capital-allocation policy")
    p3.add_argument("--as-of", default="2025-06-30", help=asof_help)
    p3.add_argument("--format", choices=["csv", "parquet"], default="csv")
    p3.add_argument("--config", default=str(_default_config_path()))
    p3.set_defaults(func=cmd_phase3)

    p4 = sub.add_parser("phase4", help="VMS-0.2 Phase 4 FCFF/FCFE/DDM via router (synthetic; NOT investment advice)")
    p4.add_argument("--out", required=True)
    p4.add_argument("--seed", type=int)
    p4.add_argument("--paths", type=int, help="Monte Carlo paths (default: min(40, config))")
    p4.add_argument("--years", type=int, help="projection years (default: 4)")
    p4.add_argument("--policy", choices=sorted(POLICIES), help="capital-allocation policy")
    p4.add_argument("--as-of", default="2025-06-30", help=asof_help)
    p4.add_argument("--format", choices=["csv", "parquet"], default="csv")
    p4.add_argument("--config", default=str(_default_config_path()))
    p4.add_argument("--target", default="FUNDAMENTAL_VALUE_CURRENT",
                    help="ValuationTarget (default FUNDAMENTAL_VALUE_CURRENT)")
    p4.set_defaults(func=cmd_phase4)

    p5 = sub.add_parser("phase5", help="VMS-0.2 Phase 5 relative multiples + PIT peers (synthetic; NOT investment advice)")
    p5.add_argument("--out", required=True)
    p5.add_argument("--config", default=str(_default_config_path()))
    p5.add_argument("--seed", type=int, default=None)
    p5.add_argument("--paths", type=int, default=None)
    p5.add_argument("--years", type=int, default=None)
    p5.add_argument("--as-of", dest="as_of", default=None)
    p5.add_argument("--policy", default=None)
    p5.add_argument("--format", default="csv", choices=["csv", "parquet"])
    p5.add_argument("--target", default="RELATIVE_VALUE_CURRENT")
    p5.add_argument("--multiples-only", action="store_true",
                    help="skip Phase-4 cash-flow companion run")
    p5.set_defaults(func=cmd_phase5)

    p6 = sub.add_parser("phase6", help="VMS-0.2 Phase 6 RIM/NAV/SOTP (synthetic; NOT investment advice)")
    p6.add_argument("--out", required=True)
    p6.add_argument("--config", default=str(_default_config_path()))
    p6.add_argument("--seed", type=int, default=None)
    p6.add_argument("--as-of", dest="as_of", default=None)
    p6.add_argument(
        "--fixture",
        default="financial",
        choices=["financial", "holding", "holding_gap"],
        help="synthetic profile fixture: financial (RIM), holding (NAV+SOTP), holding_gap (data-gap)",
    )
    p6.add_argument(
        "--target",
        default=None,
        help="ValuationTarget override (default depends on fixture)",
    )
    p6.set_defaults(func=cmd_phase6)

    vr = sub.add_parser(
        "value-rim",
        help="R1–R3 real A-share FINANCIAL_INSTITUTION → RIM via PIT bridge (NOT investment advice; leaves industrial UNSUPPORTED)",
    )
    vr.add_argument("--input", required=True, help="directory with canonical CSV/Parquet tables")
    vr.add_argument("--ticker", required=True, help="instrument_id, e.g. 000001.SZ")
    vr.add_argument("--as-of", required=True, help=asof_help)
    vr.add_argument("--out", required=True, help="output directory for rim artifacts + RUN_REPORT.md")
    vr.add_argument("--years", type=int, default=None, help="forecast horizon (default: config projection.default_years)")
    vr.add_argument("--zeros-explicit", action="store_true", default=True,
                    help="allow explicit zero OCI/net_issuance (flag CLEAN_SURPLUS_ZEROS_ASSUMED); default on")
    vr.add_argument("--no-zeros-explicit", action="store_true",
                    help="refuse missing OCI/net_issuance (structured error; never silent zeros)")
    vr.add_argument("--equity-basis", choices=["common", "total"], default="common",
                    help="R2 default common equity; total = R1 legacy total_equity book")
    vr.add_argument("--paths", type=int, default=None, help="P2 ROE bootstrap paths (default: config monte_carlo.default_paths)")
    vr.add_argument("--seed", type=int, default=None, help="P2 bootstrap seed (default: config monte_carlo.default_seed)")
    vr.add_argument("--ke-grid", default=None, help="comma-separated ke grid, default 0.08,0.09,0.10")
    vr.add_argument("--no-distribution", action="store_true",
                    help="skip R2b P2 distribution / ke grid (P1 point only)")
    vr.add_argument("--no-auto-fi-peers", action="store_true",
                    help="disable R3 auto-build of deposit-taking FI peer_observations when load.peers empty")
    vr.add_argument("--target", default=None, help="ValuationTarget (default FUNDAMENTAL_VALUE_CURRENT)")
    _gate_args(vr)
    vr.set_defaults(func=cmd_value_rim)

    p7 = sub.add_parser("phase7", help="VMS-0.2 Phase 7 router hardening + method comparison (synthetic; NOT investment advice)")
    p7.add_argument("--out", required=True)
    p7.add_argument("--config", default=str(_default_config_path()))
    p7.add_argument("--seed", type=int, default=None)
    p7.add_argument("--as-of", dest="as_of", default=None)
    p7.add_argument(
        "--fixture",
        default="mature",
        choices=["mature", "financial", "holding", "hybrid_gap"],
        help="synthetic profile fixture for routing log",
    )
    p7.add_argument("--target", default=None, help="ValuationTarget override")
    p7.add_argument("--force-no-eligible", action="store_true",
                    help="strip available fields to demonstrate INSUFFICIENT_METHOD_COVERAGE")
    p7.add_argument("--request-blend", action="store_true",
                    help="request a blend; still returns ENSEMBLE_UNCALIBRATED (no combined value)")
    p7.set_defaults(func=cmd_phase7)

    cm = sub.add_parser("compare-methods", help="VMS-0.2 Phase 7 method disagreement (synthetic; NOT investment advice)")
    cm.add_argument("--out", required=True)
    cm.add_argument("--config", default=str(_default_config_path()))
    cm.add_argument("--seed", type=int, default=None)
    cm.add_argument("--as-of", dest="as_of", default=None)
    cm.add_argument(
        "--fixture",
        default="mature",
        choices=["mature", "financial", "holding", "hybrid_gap"],
    )
    cm.add_argument("--target", default=None)
    cm.add_argument("--request-blend", action="store_true")
    cm.set_defaults(func=cmd_compare_methods)

    p8 = sub.add_parser("phase8", help="VMS-0.2 Phase 8 ensemble + model uncertainty (synthetic; NOT investment advice)")
    p8.add_argument("--out", required=True)
    p8.add_argument("--config", default=str(_default_config_path()))
    p8.add_argument("--seed", type=int, default=None)
    p8.add_argument("--as-of", dest="as_of", default=None)
    p8.add_argument(
        "--fixture",
        default="mature",
        choices=["mature", "financial", "holding"],
        help="synthetic profile fixture",
    )
    p8.add_argument("--target", default=None, help="ValuationTarget override")
    p8.add_argument("--n-draws", dest="n_draws", type=int, default=None,
                    help="mixture Monte Carlo draws for PRIOR_ONLY research path")
    p8.set_defaults(func=cmd_phase8)


    p9 = sub.add_parser("phase9", help="VMS-0.2 Phase 9 market-pricing + exit-price engine (synthetic; NOT investment advice)")
    p9.add_argument("--out", required=True)
    p9.add_argument("--config", default=str(_default_config_path()))
    p9.add_argument("--seed", type=int, default=None)
    p9.add_argument("--as-of", dest="as_of", default=None)
    p9.add_argument("--paths", type=int, default=None)
    p9.add_argument("--years", type=int, default=None)
    p9.add_argument("--horizons", default=None, help="comma-separated years, e.g. 1,3")
    p9.add_argument("--metric", default=None, choices=["pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"],
                    help="terminal-multiple family (default: config market_pricing.default_metric_id)")
    p9.add_argument("--no-convergence-demo", dest="no_convergence_demo", action="store_true",
                    help="skip explicit CONVERGENCE_TO_INTRINSIC demo artifact")
    p9.set_defaults(func=cmd_phase9)

    p10 = sub.add_parser("phase10", help="VMS-0.2 Phase 10 Track B returns + DSDE contract (synthetic; NOT investment advice)")
    p10.add_argument("--out", required=True)
    p10.add_argument("--config", default=str(_default_config_path()))
    p10.add_argument("--seed", type=int, default=None)
    p10.add_argument("--as-of", dest="as_of", default=None)
    p10.add_argument("--paths", type=int, default=None)
    p10.add_argument("--years", type=int, default=None)
    p10.add_argument("--horizons", default=None, help="comma-separated years, e.g. 1,3")
    p10.add_argument("--metric", default=None, choices=["pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"],
                    help="terminal-multiple family (default: config market_pricing.default_metric_id)")
    p10.add_argument("--spot", type=float, default=None, help="entry spot price (default: last synthetic close)")
    p10.add_argument("--entry-prices", dest="entry_prices", default=None,
                    help="optional extra absolute entry prices, comma-separated")
    p10.add_argument("--notify-dsde", dest="notify_dsde", action="store_true",
                    help="attempt optional DSDE notify (no-op when DSDE absent)")
    p10.set_defaults(func=cmd_phase10)

    p11 = sub.add_parser("phase11", help="VMS-0.2 Phase 11 walk-forward + sensitivity (synthetic; NOT investment advice)")
    p11.add_argument("--out", required=True)
    p11.add_argument("--config", default=str(_default_config_path()))
    p11.add_argument("--universe", default=None, help="universe YAML (default: config/universe.synthetic.yaml)")
    p11.add_argument("--start", default="2018-01-01")
    p11.add_argument("--end", default="2022-12-31")
    p11.add_argument("--seed", type=int, default=None)
    p11.add_argument("--paths", type=int, default=None, help="sensitivity MC paths (default 20)")
    p11.add_argument("--years", type=int, default=None, help="sensitivity projection years (default 3)")
    p11.add_argument("--skip-sensitivity", dest="skip_sensitivity", action="store_true",
                    help="write evaluation_report only (skip sensitivity_report)")
    p11.set_defaults(func=cmd_phase11)

    p12 = sub.add_parser("phase12", help="VMS-0.2 Phase 12 offline release examples (synthetic; NOT investment advice)")
    p12.add_argument("--out", required=True)
    p12.add_argument("--config", default=str(_default_config_path()))
    p12.add_argument("--seed", type=int, default=None)
    p12.add_argument("--paths", type=int, default=None, help="MC paths for mature Track A/B (default 20)")
    p12.add_argument("--years", type=int, default=None, help="projection years (default 3)")
    p12.add_argument("--pattern", default=None, choices=list(ALL_PATTERNS),
                    help="run a single pattern; default runs all five into out/<pattern>/")
    p12.add_argument("--patterns", default=None,
                    help="comma-separated subset of patterns when running the release layout")
    p12.add_argument("--spot", type=float, default=None, help="entry spot for mature Track B (optional)")
    p12.set_defaults(func=cmd_phase12)

    vb = sub.add_parser("validate-bundle", help="Validate result-bundle against PHASE_CLI subset / §16.3")
    vb.add_argument("--path", required=True, help="run directory to validate")
    vb.add_argument("--subset", default="phase12",
                    help=f"one of {sorted(PHASE_CLI_SUBSETS)} or section_16_3")
    vb.set_defaults(func=cmd_validate_bundle)

    d = sub.add_parser("demo", help="offline SYNTHETIC smoke (legacy 0.1 pipeline; through returns/sensitivity)")
    d.add_argument("--policy", choices=sorted(POLICIES))
    d.add_argument("--out", required=True)
    d.add_argument("--seed", type=int)
    d.add_argument("--paths", type=int)
    d.add_argument("--horizons", help="comma-separated years, e.g. 1,3,5")
    d.add_argument("--as-of", default="2025-06-30", help=asof_help)
    d.add_argument("--format", choices=["csv", "parquet"], default="csv")
    _gate_args(d)
    d.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, InputError, Phase0BundleError, Phase3BundleError, Phase8BundleError, Phase9BundleError, Phase10BundleError, Phase11BundleError, Phase12BundleError, ValueRimBundleError, FixtureError, RegimeModelNotImplemented, RandomSplitProhibitedError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
