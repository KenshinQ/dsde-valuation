"""`vms` command-line interface.

Implemented commands:
  validate-data   schema validation; with --as-of also PIT snapshot + quality gate per instrument
  build-snapshot  PIT snapshot + data_quality_report.json + data_manifest.json for one instrument
  demo            offline SYNTHETIC smoke run through the Phase-1 gate. NO valuation is computed.

Exit codes: 0 ok, 1 unexpected error, 2 invalid input/config/arguments,
            3 BLOCKED by critical data-quality errors in production mode.
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
from vms.seeding import stream_rng

EXIT_OK, EXIT_ERROR, EXIT_INVALID, EXIT_BLOCKED = 0, 1, 2, 3
SMOKE_STATUS = "PHASE1_SMOKE_NOT_A_VALUATION"
DETERMINISTIC_ARTIFACTS = ("request.json", "config_snapshot.json", "data_manifest.json",
                           "data_quality_report.json", "pit_snapshot.json", "simulation_metadata.json")


class InputError(ValueError):
    pass


def _default_config_path() -> Path:
    cwd = Path.cwd() / "config" / "default.yaml"
    if cwd.is_file():
        return cwd
    return Path(__file__).resolve().parents[3] / "config" / "default.yaml"


def dataset_hash(load: LoadResult) -> str:
    return sha256_of({"records": hash_models([*load.financial, *load.market, *load.corporate_actions]),
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
    write_directory(data_dir, fin, mkt, actions, synthetic.source_descriptors(), fmt=args.format)
    load = _load(str(data_dir))  # round-trip through the same ingestion users get
    snap, report = assess(load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, cfg=cfg.quality,
                          mode=mode, override_reason=args.override_reason)
    blocked = report.status is QualityState.BLOCKED and mode == "production"
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
    smoke = stream_rng(seed, "phase0_smoke").standard_normal(5)
    write_artifact(out, "simulation_metadata.json", {
        "status": SMOKE_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "warning": "Smoke artifact. No valuation, no paths, no return distribution was computed.",
        "data_label": "SYNTHETIC — not real market data",
        "quality_status": report.status.value,
        "metadata": meta.model_dump(mode="json"),
        "rng_smoke_check": {"stream": "phase0_smoke", "first_5_standard_normal": [round(float(x), 12) for x in smoke],
                            "purpose": "proves seed determinism only"},
    }, meta)
    write_artifact(out, "run_context.json", {"created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
                                             "deterministic_artifacts": list(DETERMINISTIC_ARTIFACTS)}, meta)
    print(json.dumps({"status": SMOKE_STATUS, "quality_status": report.status.value, "run_id": meta.run_id,
                      "schema_version": SCHEMA_VERSION, "out": str(out), "spot_price": spot, "seed": seed,
                      "paths": paths, "data_hash": data_hash[:16], "config_hash": meta.config_hash[:16],
                      "git_sha": meta.code_version["git_sha"][:12]}, indent=2))
    try:
        gate(report)
    except GateError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BLOCKED
    return EXIT_OK


# ------------------------------------------------------------------ parser
def _gate_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default=str(_default_config_path()))
    p.add_argument("--mode", choices=["production", "exploratory"], help="default: config 'mode'")
    p.add_argument("--override-reason", help="required with --mode exploratory; recorded in the report")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vms", description="VMS-0.1 valuation engine (Phase 1: PIT data & gates)")
    sub = p.add_subparsers(dest="command", required=True)
    asof_help = "YYYY-MM-DD (=> 15:00 Asia/Shanghai, rule ASOF-DATE-CLOSE-1) or ISO-8601 with offset"

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

    d = sub.add_parser("demo", help="offline SYNTHETIC smoke run (no valuation)")
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
    except (ConfigError, InputError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
