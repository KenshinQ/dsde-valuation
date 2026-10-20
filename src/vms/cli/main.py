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
  evaluate        Phase 9 chronological walk-forward evaluation
  demo            offline SYNTHETIC smoke (Phases 0–10; evaluate + optional DSDE adapter).

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
        "implemented_phase": "PHASE_8",
        "warning": "Sensitivity/attribution complete; use vms evaluate for Phase 9 walk-forward.",
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
        "implemented_phase": "PHASE_9",
        "warning": "Walk-forward evaluation only; no DSDE adapter (Phase 10).",
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




    evl = sub.add_parser("evaluate", help="chronological walk-forward evaluation (Phase 9)")
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

    vl = sub.add_parser("value", help="FCFF DCF + exit-multiple + EV-equity bridge (Phase 6)")
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

    d = sub.add_parser("demo", help="offline SYNTHETIC smoke (through returns/sensitivity)")
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
    except (ConfigError, InputError, RegimeModelNotImplemented, RandomSplitProhibitedError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
