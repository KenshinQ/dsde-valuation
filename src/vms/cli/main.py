"""`vms` command-line interface.

Implemented commands:
  validate-data   schema validation; with --as-of also PIT snapshot + quality gate per instrument
  build-snapshot  PIT snapshot + data_quality_report.json + data_manifest.json for one instrument
  project         PIT snapshot + gate + profile + drivers + deterministic statements (Phase 2)
  estimate        PIT snapshot + gate + fundamental regimes + walk-forward + driver distributions (Phase 3)
  demo            offline SYNTHETIC smoke run (snapshot, gate, statements, regimes, distributions). NO valuation.

Exit codes: 0 ok, 1 unexpected error, 2 invalid input/config/arguments,
            3 BLOCKED by critical data-quality errors in production mode,
            4 UNSUPPORTED_PROFILE (raw metrics written, no projection),
            5 projection INSUFFICIENT_DATA or REJECTED (accounting invariant violated).
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
from vms.pipeline import Phase2Run, Phase3Run, run_estimation, run_projection
from vms.regimes import RegimeModelNotImplemented
from vms.seeding import stream_rng

EXIT_OK, EXIT_ERROR, EXIT_INVALID, EXIT_BLOCKED, EXIT_UNSUPPORTED, EXIT_PROJECTION = 0, 1, 2, 3, 4, 5
SMOKE_STATUS = "PHASE3_SMOKE_NOT_A_VALUATION"
DETERMINISTIC_ARTIFACTS = ("request.json", "config_snapshot.json", "data_manifest.json",
                           "data_quality_report.json", "pit_snapshot.json", "state_posterior.json",
                           "driver_diagnostics.json", "statement_projection.json", "simulation_metadata.json")


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
    load = _load(args.input)
    snap, report = assess(load, instrument_id=args.ticker, as_of=as_of, cfg=cfg.config.quality, mode=mode,
                          override_reason=args.override_reason)
    stamp = ArtifactStamp(run_id=content_run_id(kind="build-snapshot", instrument=args.ticker,
                                                as_of=as_of.isoformat(), data=dataset_hash(load),
                                                config=sha256_of(cfg.config.model_dump(mode="json")),
                                                mode=mode, override=args.override_reason))
    blocked = report.status is QualityState.BLOCKED and mode == "production"
    out = Path(args.out)
    _write_snapshot_bundle(out, stamp, load, args.input, as_of, note, snap, report, blocked)
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
    if run is not None:
        _write_phase2(out, meta, run)
        run3 = run_estimation(load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, loaded=loaded,
                              seed=seed, mode=mode, override_reason=args.override_reason)
        _write_phase3(out, meta, run3, run)
    smoke = stream_rng(seed, "phase0_smoke").standard_normal(5)
    write_artifact(out, "simulation_metadata.json", {
        "status": SMOKE_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "warning": "Smoke artifact. Deterministic central-case statements, fundamental regimes and driver "
                   "distributions only; no valuation, no paths, no return distribution was computed.",
        "data_label": "SYNTHETIC — not real market data",
        "quality_status": report.status.value,
        "metadata": meta.model_dump(mode="json"),
        "rng_smoke_check": {"stream": "phase0_smoke", "first_5_standard_normal": [round(float(x), 12) for x in smoke],
                            "purpose": "proves seed determinism only"},
    }, meta)
    write_artifact(out, "run_context.json", {"created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
                                             "deterministic_artifacts": list(DETERMINISTIC_ARTIFACTS)}, meta)
    print(json.dumps({"status": SMOKE_STATUS, "quality_status": report.status.value,
                      **({} if run is None else _p2_summary(run)),
                      **({} if run3 is None else {"phase3": _p3_summary(run3)}), "run_id": meta.run_id,
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vms", description="VMS-0.1 valuation engine (Phase 3: regimes & driver distributions; no valuation yet)")
    sub = p.add_subparsers(dest="command", required=True)
    asof_help = "YYYY-MM-DD (=> 15:00 Asia/Shanghai, rule ASOF-DATE-CLOSE-v1) or ISO-8601 with offset"

    v = sub.add_parser("validate-data", help="schema validation; with --as-of also PIT + quality gates")
    v.add_argument("--input", required=True, help="directory with canonical CSV/Parquet tables")
    v.add_argument("--as-of", help=asof_help)
    v.add_argument("--ticker", help="limit to one instrument_id (default: all)")
    _gate_args(v)
    v.set_defaults(func=cmd_validate_data)

    b = sub.add_parser("build-snapshot", help="PIT snapshot + quality report for one instrument")
    b.add_argument("--input", required=True)
    b.add_argument("--ticker", required=True, help="instrument_id, e.g. 000001.SZ")
    b.add_argument("--as-of", required=True, help=asof_help)
    b.add_argument("--out", required=True)
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

    d = sub.add_parser("demo", help="offline SYNTHETIC smoke run (no valuation)")
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
    except (ConfigError, InputError, RegimeModelNotImplemented) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
