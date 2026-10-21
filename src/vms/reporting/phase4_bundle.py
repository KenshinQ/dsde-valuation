"""VMS-0.2 Phase 4 offline cash-flow methods demo (SPEC §20 Phase 4).

Runs synthetic mature-operating paths through router → FCFF/FCFE/DDM.
No multiples, RIM/NAV, ensemble, or exit-price estimator.
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
from vms.market_pricing import unavailable_market_pricing
from vms.methods import build_registry_from_config
from vms.methods.cash_flow import run_eligible_cashflow_methods
from vms.pipeline import run_path_projection
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.reporting.metadata import ArtifactStamp, content_run_id, hash_models, sha256_of, write_artifact
from vms.schemas.config import load_config
from vms.schemas.contracts import ValuationTarget

PHASE4_STATUS = "PHASE4_CASHFLOW_METHODS_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = "INVESTMENT_VALUE_NOT_ESTABLISHED"


class Phase4BundleError(ValueError):
    pass


def _profile_for_synthetic(as_of_iso: str) -> Any:
    """Classify using mature_operating fixture features, stamped with synthetic id/as_of."""
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    # Override identity to match synthetic instrument / as_of
    feats = feats.model_copy(update={
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT,
        "as_of": as_of_iso[:10] if "T" not in as_of_iso else as_of_iso[:10],
    })
    return classify_profile(feats), frozenset(data.get("available_fields") or [])


def build_phase4_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path,
    seed: int = 42,
    paths: int = 40,
    years: int = 4,
    as_of: datetime | None = None,
    policy_id: str | None = None,
    data_format: str = "csv",
    target: ValuationTarget = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loaded = load_config(config_path)
    cfg = loaded.config
    if as_of is None:
        as_of, as_of_note = parse_as_of("2025-06-30")
    else:
        as_of_note = AS_OF_DATE_RULE
    if paths <= 0:
        raise Phase4BundleError(f"paths must be > 0 (got {paths})")

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
        raise Phase4BundleError(
            f"path bundle unsupported/empty: profile={run.resolution.status.value} "
            f"reason={run.resolution.reason}"
        )

    profile, available_fields = _profile_for_synthetic(as_of.isoformat())
    registry = build_registry_from_config(loaded.method_registry)
    method_run = run_eligible_cashflow_methods(
        registry=registry,
        profile=profile,
        target=target,
        financial_paths=run.financial_paths,
        loaded=loaded,
        available_fields=available_fields,
    )

    data_hash = sha256_of({
        "records": hash_models([*load.financial, *load.market, *load.corporate_actions, *load.classifications]),
        "sources": {k: v.model_dump(mode="json") for k, v in sorted(load.sources.items())},
    })
    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "driver_profile": loaded.profile.model_dump(mode="json"),
        "method_registry_version": loaded.method_registry.registry_version,
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase4", instrument=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of.isoformat(),
            seed=seed, paths=paths, years=years, data=data_hash,
            config=sha256_of(config_snapshot), policy=policy_id, target=target.value,
        ),
    )

    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(out, "data_manifest.json", {
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT,
        "as_of": as_of.isoformat(),
        "as_of_interpretation": as_of_note,
        "data_label": "SYNTHETIC — not real market data",
        "n_financial": len(load.financial),
        "data_hash": data_hash,
    }, stamp)
    write_artifact(out, "profile_report.json", profile.model_dump(mode="json"), stamp)
    write_artifact(out, "route_report.json", method_run.route.model_dump(mode="json"), stamp)
    write_artifact(out, "method_results.json", {
        "results": [r.model_dump(mode="json") for r in method_run.results],
        "eligible_run": method_run.eligible_run,
        "skipped": method_run.skipped,
        "ensemble": None,
        "notes": method_run.notes,
        "investment_value": INVESTMENT_LABEL,
    }, stamp)

    mp = unavailable_market_pricing()
    write_artifact(out, "simulation_metadata.json", {
        "status": PHASE4_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Phase 4 cash-flow methods only (FCFF/FCFE/DDM). No multiples/RIM/NAV/SOTP, "
            "no calibrated ensemble, no exit-price estimator. Not investment advice."
        ),
        "data_label": "SYNTHETIC — not real market data",
        "seed": seed,
        "n_paths": paths,
        "n_years": years,
        "financial_n_valid": run.financial_paths.n_valid,
        "eligible_run": method_run.eligible_run,
        "market_pricing_status": mp.status,
        "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
    }, stamp)

    summary = {
        "status": PHASE4_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "paths": paths,
        "years": years,
        "target": target.value,
        "profile_primary": profile.primary_profile.value,
        "coverage_status": method_run.route.coverage_status,
        "eligible_run": method_run.eligible_run,
        "method_statuses": [
            {"method_id": r.method_id, "status": r.status.value, "reason_codes": r.reason_codes}
            for r in method_run.results
        ],
        "financial_n_valid": run.financial_paths.n_valid,
        "market_pricing_status": mp.status,
        "ensemble": None,
        "data_hash": data_hash[:16],
    }
    (out / "phase4_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
