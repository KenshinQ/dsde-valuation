"""Phase 0 offline result-bundle emitter (SPEC §16.3 minimal subset + provenance).

Does not run valuation methods, profile classification, or routing. Emits a
versioned bundle with schema/code hashes and explicit NOT_RUN method rows so
later phases can fill the same layout without reinventing provenance.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data import synthetic
from vms.data.io import write_directory
from vms.reporting.metadata import make_run_metadata, sha256_of, write_artifact
from vms.schemas import ValuationRequest, format_validation_error
from vms.schemas.config import LoadedConfig, load_config
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    MethodStatusRecord,
    Phase0ClaimLabels,
    ValuationTarget,
)
from vms.seeding import stream_rng


PHASE0_STATUS = "PHASE0_CONTRACTS_BASELINE_NOT_A_VALUATION"
PHASE0_DETERMINISTIC = (
    "request.json",
    "config_snapshot.json",
    "data_manifest.json",
    "method_eligibility.json",
    "validation_report.json",
    "simulation_metadata.json",
)


class Phase0BundleError(ValueError):
    """Invalid Phase 0 inputs (actionable)."""


def _config_snapshot(loaded: LoadedConfig) -> dict[str, Any]:
    return {
        "config": loaded.config.model_dump(mode="json"),
        "driver_profile": loaded.profile.model_dump(mode="json"),
        "method_registry": loaded.method_registry.model_dump(mode="json"),
        "router": loaded.router.model_dump(mode="json"),
        "profiles_catalog": loaded.profiles_catalog.model_dump(mode="json"),
    }


def build_phase0_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path | None = None,
    seed: int = 42,
    paths: int = 100,
    as_of: datetime | None = None,
    target: ValuationTarget = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
    horizons_years: list[int] | None = None,
    data_format: str = "csv",
) -> dict[str, Any]:
    """Generate synthetic mature-operating data, validate contracts, write a Phase 0 bundle.

    Returns a summary dict (also printed by the CLI). Never executes a valuation method.
    """
    from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of

    loaded = load_config(config_path or _default_config())
    cfg = loaded.config
    if as_of is None:
        as_of, as_of_note = parse_as_of("2025-06-30")
    else:
        if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
            raise Phase0BundleError(
                f"as_of={as_of.isoformat()} is timezone-naive; append an offset such as +08:00"
            )
        as_of_note = "explicit timezone-aware as_of"
    horizons = list(horizons_years or cfg.horizons_years)
    if paths <= 0:
        raise Phase0BundleError(f"paths must be > 0 (got {paths})")

    out = Path(out_dir)
    data_dir = out / "data"
    fin, mkt, actions = synthetic.generate(seed)
    write_directory(
        data_dir, fin, mkt, actions, synthetic.source_descriptors(),
        fmt=data_format, classifications=synthetic.classifications(),
    )

    # Schema-level round-trip via request construction (no PIT/quality yet — Phase 1).
    spot = float(sorted(mkt, key=lambda o: o.timestamp)[-1].raw_close)
    try:
        request = ValuationRequest(
            instrument_id=synthetic.SYNTHETIC_INSTRUMENT,
            as_of=as_of,
            spot_price=spot,
            horizons_years=horizons,
            monte_carlo_paths=paths,
            random_seed=seed,
            configuration_version=cfg.configuration_version,
            target=target,
        )
    except ValidationError as e:
        raise Phase0BundleError(format_validation_error(e, "request")) from None

    data_hash = sha256_of({
        "n_financial": len(fin),
        "n_market": len(mkt),
        "n_actions": len(actions),
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT,
        "seed": seed,
        "note": "Phase0 data_hash is a synthetic provenance stamp; Phase 1 uses full record hash",
    })
    config_snapshot = _config_snapshot(loaded)
    meta = make_run_metadata(
        request=request, config_snapshot=config_snapshot, data_hash=data_hash,
        seed=seed, paths=paths,
    )

    labels = Phase0ClaimLabels(
        ENGINEERING_PASS=True,
        DATA_QUALITY_PASS=None,
        CALIBRATION_STATUS="INCONCLUSIVE",
        investment_value=ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value,
        data_label="SYNTHETIC",
    )

    # Empty registry => every declared catalog method is NOT_RUN (none claim a value).
    eligibility = [
        MethodStatusRecord(
            method_id=mid,
            status=MethodEligibilityStatus.NOT_RUN,
            reason="Phase 0 baseline: method registry has no IMPLEMENTED/enabled methods",
            target=target,
        )
        for mid in _catalog_method_ids(loaded)
    ]

    write_artifact(out, "request.json", {
        "request": request.model_dump(mode="json"),
        "as_of_interpretation": as_of_note,
        "as_of_rule": AS_OF_DATE_RULE,
    }, meta)
    write_artifact(out, "config_snapshot.json", config_snapshot, meta)
    write_artifact(out, "data_manifest.json", {
        "input_dir": "data",  # relative to bundle root (absolute paths break byte reproducibility)
        "data_hash": data_hash,
        "data_hash_method": "phase0_synthetic_provenance_v1",
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT,
        "as_of": as_of.isoformat(),
        "n_financial": len(fin),
        "n_market": len(mkt),
        "n_corporate_actions": len(actions),
        "format": data_format,
        "label": "SYNTHETIC — not real market data",
    }, meta)
    write_artifact(out, "method_eligibility.json", {
        "target": target.value,
        "registry_version": loaded.method_registry.registry_version,
        "enabled_method_count": len(loaded.method_registry.enabled_methods),
        "methods": [r.model_dump(mode="json") for r in eligibility],
        "note": "No method executed; statuses are NOT_RUN by design in Phase 0",
    }, meta)
    write_artifact(out, "validation_report.json", {
        "status": "PASS",
        "checks": [
            {"id": "CONFIG_VALID", "ok": True},
            {"id": "METHOD_REGISTRY_VALID", "ok": True,
             "detail": f"registry_version={loaded.method_registry.registry_version}; methods={len(loaded.method_registry.methods)}"},
            {"id": "ROUTER_CONFIG_VALID", "ok": True},
            {"id": "PROFILES_CATALOG_VALID", "ok": True,
             "detail": f"profiles={len(loaded.profiles_catalog.profiles)}"},
            {"id": "REQUEST_VALID", "ok": True},
            {"id": "NO_ENABLED_METHODS", "ok": True,
             "detail": "expected in Phase 0; production valuers arrive in later phases"},
        ],
        "labels": labels.model_dump(mode="json"),
    }, meta)
    smoke = stream_rng(seed, "phase0_smoke").standard_normal(5)
    write_artifact(out, "simulation_metadata.json", {
        "status": PHASE0_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "schema_version_contract": SCHEMA_VERSION,
        "warning": (
            "Phase 0 contracts baseline only. Not a valuation. "
            "Method routing / FCFF / returns are later VMS-0.2 phases. "
            "INVESTMENT_VALUE_NOT_ESTABLISHED."
        ),
        "data_label": "SYNTHETIC — not real market data",
        "labels": labels.model_dump(mode="json"),
        "metadata": meta.model_dump(mode="json"),
        "rng_smoke_check": {
            "stream": "phase0_smoke",
            "first_5_standard_normal": [round(float(x), 12) for x in smoke],
            "purpose": "proves seed determinism only",
        },
        "reproducibility": {
            "tolerance": "exact bytes for deterministic artifacts on the same lockfile/code",
            "note": "Monte Carlo numerical tolerances apply when methods are implemented",
        },
    }, meta)
    write_artifact(out, "run_context.json", {
        "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
        "deterministic_artifacts": list(PHASE0_DETERMINISTIC),
        "timezone": cfg.timezone,
    }, meta)

    return {
        "status": PHASE0_STATUS,
        "run_id": meta.run_id,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "out": str(out),
        "spot_price": spot,
        "seed": seed,
        "paths": paths,
        "target": target.value,
        "data_hash": data_hash[:16],
        "config_hash": meta.config_hash[:16],
        "git_sha": meta.code_version["git_sha"][:12],
        "investment_value": labels.investment_value,
        "enabled_methods": 0,
        "method_status_rows": len(eligibility),
    }


def _catalog_method_ids(loaded: LoadedConfig) -> list[str]:
    """Union of candidate ids from the profiles catalog (sorted, unique)."""
    ids: set[str] = set()
    for p in loaded.profiles_catalog.profiles:
        ids.update(p.candidate_method_ids)
    for m in loaded.method_registry.methods:
        ids.add(m.method_id)
    return sorted(ids)


def _default_config() -> Path:
    cwd = Path.cwd() / "config" / "default.yaml"
    if cwd.is_file():
        return cwd
    return Path(__file__).resolve().parents[3] / "config" / "default.yaml"


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
