"""`vms` command-line interface (Phase 0).

Implemented commands:
  validate-data  schema-validate a data directory (no PIT/integrity gates yet)
  demo           offline SYNTHETIC Phase-0 smoke run: writes request/config/metadata
                 artifacts. It performs NO valuation.

Exit codes: 0 ok, 2 invalid input/config, 1 unexpected error.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data import synthetic
from vms.data.io import FINANCIAL_FILE, MARKET_FILE, load_directory, write_directory
from vms.reporting.metadata import (
    hash_models,
    make_run_metadata,
    write_artifact,
)
from vms.schemas import ValuationRequest, format_validation_error
from vms.schemas.config import ConfigError, load_config
from vms.seeding import stream_rng

EXIT_OK, EXIT_ERROR, EXIT_INVALID = 0, 1, 2
SMOKE_STATUS = "PHASE0_SMOKE_NOT_A_VALUATION"
DETERMINISTIC_ARTIFACTS = ("request.json", "config_snapshot.json", "data_manifest.json",
                           "simulation_metadata.json")


class InputError(ValueError):
    pass


def _default_config_path() -> Path:
    cwd = Path.cwd() / "config" / "default.yaml"
    if cwd.is_file():
        return cwd
    return Path(__file__).resolve().parents[3] / "config" / "default.yaml"


def parse_as_of(text: str, tz_name: str) -> tuple[datetime, str]:
    """ISO datetime with offset, or a bare date = end of that day in the config timezone."""
    try:
        d = date.fromisoformat(text)
        if len(text) == 10:
            dt = datetime.combine(d, time(23, 59, 59), ZoneInfo(tz_name))
            return dt, f"bare date interpreted as end of day {tz_name}"
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise InputError(f"--as-of {text!r} is not ISO-8601; use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS+08:00") from None
    if dt.tzinfo is None:
        raise InputError(f"--as-of {text!r} is timezone-naive; append an offset such as +08:00")
    return dt, "explicit timezone-aware timestamp"


def cmd_validate_data(args: argparse.Namespace) -> int:
    res = load_directory(args.input)
    as_of_note = None
    if args.as_of:
        as_of, _ = parse_as_of(args.as_of, "Asia/Shanghai")
        after = sum(1 for o in res.financial if o.published_at > as_of)
        as_of_note = (f"{after} financial records published after as_of={as_of.isoformat()} "
                      "(informational only; PIT filtering is Phase 1, not applied)")
    report = {
        "status": "SCHEMA_VALID" if res.ok else "SCHEMA_INVALID",
        "scope": "Phase 0 schema validation only; no PIT/integrity/accounting gates",
        "financial_records": len(res.financial),
        "market_records": len(res.market),
        "error_count": len(res.errors),
    }
    if as_of_note:
        report["as_of_note"] = as_of_note
    print(json.dumps(report, indent=2, ensure_ascii=False))
    for e in res.errors:
        print(e, file=sys.stderr)
    return EXIT_OK if res.ok else EXIT_INVALID


def cmd_demo(args: argparse.Namespace) -> int:
    loaded = load_config(args.config)
    cfg = loaded.config
    seed = cfg.monte_carlo.default_seed if args.seed is None else args.seed
    paths = cfg.monte_carlo.default_paths if args.paths is None else args.paths
    try:
        horizons = cfg.horizons_years if args.horizons is None else [int(h) for h in args.horizons.split(",")]
    except ValueError:
        raise InputError(f"--horizons {args.horizons!r} must be comma-separated integers, e.g. 1,3,5") from None
    as_of, as_of_note = parse_as_of(args.as_of, cfg.timezone)

    out = Path(args.out)
    data_dir = out / "data"
    fin, mkt = synthetic.generate(seed)
    write_directory(data_dir, fin, mkt)
    res = load_directory(data_dir)  # round-trip through the same validation path users get
    if not res.ok:
        raise InputError("synthetic data failed validation:\n" + "\n".join(res.errors))
    closes = [m for m in res.market if m.timestamp <= as_of]
    if not closes:
        raise InputError(f"no synthetic market observation at or before as_of={as_of.isoformat()}")
    spot = closes[-1].raw_close

    try:
        request = ValuationRequest(instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of,
                                   spot_price=spot, horizons_years=horizons, monte_carlo_paths=paths,
                                   random_seed=seed, configuration_version=cfg.configuration_version)
    except ValidationError as e:
        raise InputError(format_validation_error(e, "request")) from None

    data_hash = hash_models([*res.financial, *res.market])
    config_snapshot = {"config": cfg.model_dump(mode="json"), "driver_profile": loaded.profile.model_dump(mode="json")}
    meta = make_run_metadata(request=request, config_snapshot=config_snapshot, data_hash=data_hash,
                             seed=seed, paths=paths)

    write_artifact(out, "request.json", {"request": request.model_dump(mode="json"),
                                         "as_of_interpretation": as_of_note}, meta)
    write_artifact(out, "config_snapshot.json", config_snapshot, meta)
    write_artifact(out, "data_manifest.json", {
        "data_label": "SYNTHETIC — not real market data",
        "source_id": synthetic.SYNTHETIC_SOURCE,
        "files": {FINANCIAL_FILE: len(res.financial), MARKET_FILE: len(res.market)},
        "data_hash": data_hash,
        "data_hash_method": "sha256 over sorted canonical-JSON records (order-independent)",
        "pit_status": "NOT_EVALUATED (Phase 1)",
    }, meta)
    smoke = stream_rng(seed, "phase0_smoke").standard_normal(5)
    write_artifact(out, "simulation_metadata.json", {
        "status": SMOKE_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "warning": "Phase 0 smoke artifact. No valuation, no paths, no return distribution was computed.",
        "metadata": meta.model_dump(mode="json"),
        "rng_smoke_check": {"stream": "phase0_smoke", "first_5_standard_normal": [round(float(x), 12) for x in smoke],
                            "purpose": "proves seed determinism only"},
    }, meta)
    # Non-deterministic context kept out of the reproducibility hash set.
    write_artifact(out, "run_context.json", {"created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
                                             "deterministic_artifacts": list(DETERMINISTIC_ARTIFACTS)}, meta)
    print(json.dumps({"status": SMOKE_STATUS, "run_id": meta.run_id, "schema_version": SCHEMA_VERSION,
                      "out": str(out), "spot_price": spot, "seed": seed, "paths": paths,
                      "data_hash": data_hash[:16], "config_hash": meta.config_hash[:16],
                      "git_sha": meta.code_version["git_sha"][:12]}, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vms", description="VMS-0.1 valuation engine (Phase 0: contracts only)")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate-data", help="schema-validate a data directory")
    v.add_argument("--input", required=True, help=f"directory with {FINANCIAL_FILE} and {MARKET_FILE}")
    v.add_argument("--as-of", help="optional decision timestamp (informational in Phase 0)")
    v.set_defaults(func=cmd_validate_data)

    d = sub.add_parser("demo", help="offline SYNTHETIC Phase-0 smoke run (no valuation)")
    d.add_argument("--out", required=True, help="output directory for artifacts")
    d.add_argument("--config", default=str(_default_config_path()))
    d.add_argument("--seed", type=int)
    d.add_argument("--paths", type=int)
    d.add_argument("--horizons", help="comma-separated years, e.g. 1,3,5")
    d.add_argument("--as-of", default="2025-06-30T15:00:00+08:00")
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
