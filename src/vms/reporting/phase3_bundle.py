"""VMS-0.2 Phase 3 offline path-bundle demo (SPEC §20 Phase 3).

Runs synthetic mature-operating data through estimation → correlated sampling →
financial-statement path projection. Does **not** invoke valuation methods
(FCFF/FCFE/DDM/multiples), ensemble, or exit-price models.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data import synthetic
from vms.data.io import load_directory, write_directory
from vms.market_pricing import MARKET_PRICING_STATES, unavailable_market_pricing
from vms.pipeline import run_path_projection
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.reporting.metadata import ArtifactStamp, content_run_id, hash_models, sha256_of, write_artifact
from vms.schemas.config import load_config

PHASE3_STATUS = "PHASE3_PATH_BUNDLE_NOT_A_VALUATION"
INVESTMENT_LABEL = "INVESTMENT_VALUE_NOT_ESTABLISHED"


class Phase3BundleError(ValueError):
    pass


def build_phase3_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path,
    seed: int = 42,
    paths: int = 80,
    years: int = 4,
    as_of: datetime | None = None,
    policy_id: str | None = None,
    data_format: str = "csv",
) -> dict[str, Any]:
    """Generate synthetic data and write a Phase-3 financial path bundle (no valuation)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loaded = load_config(config_path)
    cfg = loaded.config
    if as_of is None:
        as_of, as_of_note = parse_as_of("2025-06-30")
    else:
        as_of_note = AS_OF_DATE_RULE
    if paths <= 0:
        raise Phase3BundleError(f"paths must be > 0 (got {paths})")

    data_dir = out / "data"
    fin, mkt, actions = synthetic.generate(seed)
    write_directory(
        data_dir, fin, mkt, actions, synthetic.source_descriptors(), fmt=data_format,
        classifications=synthetic.classifications(),
    )
    load = load_directory(data_dir)

    run = run_path_projection(
        load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, loaded=loaded,
        seed=seed, n_paths=paths, n_years=years, policy_id=policy_id,
    )
    if run.financial_paths is None or run.bundle is None:
        raise Phase3BundleError(
            f"path bundle unsupported/empty: profile={run.resolution.status.value} "
            f"reason={run.resolution.reason}"
        )

    data_hash = sha256_of({
        "records": hash_models([*load.financial, *load.market, *load.corporate_actions, *load.classifications]),
        "sources": {k: v.model_dump(mode="json") for k, v in sorted(load.sources.items())},
    })
    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "driver_profile": loaded.profile.model_dump(mode="json"),
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase3", instrument=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of.isoformat(),
            seed=seed, paths=paths, years=years, data=data_hash,
            config=sha256_of(config_snapshot), policy=policy_id,
        ),
    )

    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(out, "data_manifest.json", {
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT,
        "as_of": as_of.isoformat(),
        "as_of_interpretation": as_of_note,
        "data_label": "SYNTHETIC — not real market data",
        "n_financial": len(load.financial),
        "n_market": len(load.market),
        "profile_resolution": run.resolution.model_dump(mode="json"),
        "data_hash": data_hash,
    }, stamp)

    mp = unavailable_market_pricing()
    regimes_payload: dict[str, Any] = {
        "fundamental": None if run.regimes is None else {
            "kind": run.regimes.current.kind,
            "states": run.regimes.current.states,
            "probabilities": run.regimes.current.probabilities,
            "flags": run.regimes.current.flags,
            "model_id": run.regimes.current.model_id,
            "inputs": run.regimes.current.inputs,
        },
        "market_regime_carrier": None if run.regimes is None else run.regimes.market.model_dump(mode="json"),
        "market_pricing_schema": mp.model_dump(mode="json"),
        "market_pricing_state_vocabulary": list(MARKET_PRICING_STATES),
        "fundamental_state_vocabulary_note": (
            "GROWTH/STABLE/DETERIORATING/RECOVERY (+ optional DISTRESS); "
            "must not equal market-pricing vocabulary"
        ),
    }
    write_artifact(out, "state_posterior.json", regimes_payload, stamp)

    b = run.bundle
    sim_payload = b.model_dump(mode="json")
    path_cap = min(len(sim_payload.get("paths", [])), 50)
    sim_payload["paths"] = sim_payload.get("paths", [])[:path_cap]
    sim_payload["paths_truncated"] = len(b.paths) > path_cap
    sim_payload["paths_embedded"] = path_cap
    write_artifact(out, "simulation_bundle.json", sim_payload, stamp)

    fp = run.financial_paths
    fp_payload = fp.model_dump(mode="json")
    for rec in fp_payload.get("paths", []):
        if rec.get("projection"):
            proj = rec["projection"]
            rec["projection"] = {
                "status": proj.get("status"),
                "years": proj.get("years"),
                "flags": proj.get("flags"),
                "violations": proj.get("violations"),
                "label": proj.get("label"),
                "items_omitted": True,
            }
    write_artifact(out, "financial_path_bundle.json", fp_payload, stamp)

    write_artifact(out, "simulation_metadata.json", {
        "status": PHASE3_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Path/driver/statement bundle only. No FCFF/FCFE/DDM/multiples method engines, "
            "no ensemble, no exit-price model (Phases 4–9)."
        ),
        "data_label": "SYNTHETIC — not real market data",
        "sampler_version": b.sampler_version,
        "seed": seed,
        "n_paths": b.n_paths,
        "n_years": b.n_years,
        "n_valid_sim": b.diagnostics.n_paths_valid,
        "n_invalid_sim": b.diagnostics.n_paths_invalid,
        "financial_n_valid": fp.n_valid,
        "financial_n_failed": fp.n_failed,
        "policy": fp.policy,
        "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
    }, stamp)

    summary = {
        "status": PHASE3_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "paths": paths,
        "years": years,
        "sampler_version": b.sampler_version,
        "n_valid_sim": b.diagnostics.n_paths_valid,
        "n_invalid_sim": b.diagnostics.n_paths_invalid,
        "financial_n_valid": fp.n_valid,
        "financial_n_failed": fp.n_failed,
        "profile": run.resolution.status.value,
        "profile_id": run.resolution.profile_id,
        "market_pricing_status": mp.status,
        "data_hash": data_hash[:16],
    }
    (out / "phase3_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
