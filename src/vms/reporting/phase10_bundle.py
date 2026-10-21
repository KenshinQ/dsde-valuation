"""VMS-0.2 Phase 10 offline return-distribution demo (SPEC §15 / §20 Phase 10).

Track B exit prices → entry-price-conditioned total returns + optional DSDE export.
INVESTMENT_VALUE_NOT_ESTABLISHED. No Kelly / portfolio sizing.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.adapters.dsde import (
    consumer_view_from_track_b,
    dsde_availability,
    export_return_distribution,
    try_notify_dsde,
)
from vms.data import synthetic
from vms.data.io import load_directory, write_directory
from vms.market_pricing import estimate_market_pricing_state, generate_exit_prices
from vms.pipeline import run_path_projection
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.returns.recompute import (
    exit_bundle_fingerprint,
    posterior_fingerprint,
    recompute_returns_after_market_posterior_change,
)
from vms.returns.track_b import (
    build_return_distributions_from_exit_prices,
    content_fingerprint_track_b,
    pathwise_returns_improve_at_lower_price_track_b,
)
from vms.schemas.config import load_config

PHASE10_STATUS = "PHASE10_RETURN_DISTRIBUTIONS_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = "INVESTMENT_VALUE_NOT_ESTABLISHED"


class Phase10BundleError(ValueError):
    pass


def build_phase10_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path,
    seed: int = 42,
    paths: int = 40,
    years: int = 4,
    as_of: datetime | None = None,
    policy_id: str | None = None,
    data_format: str = "csv",
    metric_id: str | None = None,
    horizons: list[int] | None = None,
    spot_price: float | None = None,
    user_entry_prices: Sequence[float] | None = None,
    notify_dsde: bool = False,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loaded = load_config(config_path)
    cfg = loaded.config
    mp_cfg = cfg.market_pricing
    if as_of is None:
        as_of, as_of_note = parse_as_of("2025-06-30")
    else:
        as_of_note = AS_OF_DATE_RULE
    if paths <= 0:
        raise Phase10BundleError(f"paths must be > 0 (got {paths})")
    horizons_years = horizons or [1, 3]
    mid = metric_id or mp_cfg.default_metric_id

    data_dir = out / "data"
    fin, mkt, actions = synthetic.generate(seed)
    write_directory(
        data_dir, fin, mkt, actions, synthetic.source_descriptors(), fmt=data_format,
        classifications=synthetic.classifications(),
    )
    load = load_directory(data_dir)

    run = run_path_projection(
        load,
        instrument_id=synthetic.SYNTHETIC_INSTRUMENT,
        as_of=as_of,
        loaded=loaded,
        seed=seed,
        n_paths=paths,
        n_years=years,
        policy_id=policy_id,
    )
    if run.financial_paths is None or run.bundle is None:
        raise Phase10BundleError(
            f"path bundle unsupported/empty: profile={run.resolution.status.value} "
            f"reason={run.resolution.reason}"
        )

    # Spot from last market close if not provided
    if spot_price is None:
        closes = [float(r.raw_close) for r in load.market if r.raw_close is not None]
        if not closes:
            raise Phase10BundleError("no market closes available for spot_price")
        spot = float(closes[-1])
    else:
        spot = float(spot_price)
    if not (spot > 0):
        raise Phase10BundleError(f"spot_price must be > 0; got {spot}")

    market_post = estimate_market_pricing_state(
        current_multiple=None,
        historical_multiples=[],
        config=mp_cfg,
        use_fallback_when_unavailable=True,
    )

    exit_bundle = generate_exit_prices(
        run.financial_paths,
        market_posterior=market_post,
        config=mp_cfg,
        horizons_years=horizons_years,
        metric_id=mid,
        seed=seed,
    )

    returns = build_return_distributions_from_exit_prices(
        exit_prices=exit_bundle,
        spot_price=spot,
        loaded=loaded,
        financial=run.financial_paths,
        horizons_years=horizons_years,
        user_entry_prices=user_entry_prices,
    )

    # AC3 smoke: recompute after an alternate posterior (history-informed) and record change
    toy_hist = [7.0, 7.5, 8.0, 8.2, 7.8, 9.0, 8.5, 8.1, 7.9, 8.3, 8.4, 8.0, 7.7, 8.6]
    alt_post = estimate_market_pricing_state(
        current_multiple=12.0,
        historical_multiples=toy_hist,
        config=mp_cfg.model_copy(update={"min_history_obs_for_estimation": 8}),
        use_fallback_when_unavailable=True,
    )
    _exit2, returns2, recompute_meta = recompute_returns_after_market_posterior_change(
        financial_paths=run.financial_paths,
        market_posterior=alt_post,
        spot_price=spot,
        loaded=loaded,
        prior_fingerprint=content_fingerprint_track_b(returns),
        horizons_years=horizons_years,
        seed=seed + 1,
        metric_id=mid,
    )

    pathwise_ok = pathwise_returns_improve_at_lower_price_track_b(returns.path_returns)

    export = export_return_distribution(returns)
    view = consumer_view_from_track_b(
        run_id="pending",
        instrument_id=synthetic.SYNTHETIC_INSTRUMENT,
        as_of=as_of.isoformat(),
        bundle=returns,
        labels={"investment_value": INVESTMENT_LABEL, "ENGINEERING_PASS": True},
    )
    dsde_avail = dsde_availability()
    notify_status = None
    if notify_dsde:
        notify_status = try_notify_dsde(view)

    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "metric_id": mid,
        "horizons_years": horizons_years,
        "paths": paths,
        "years": years,
        "spot_price": spot,
        "user_entry_prices": list(user_entry_prices) if user_entry_prices else [],
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase10",
            instrument=synthetic.SYNTHETIC_INSTRUMENT,
            as_of=as_of.isoformat(),
            seed=seed,
            metric=mid,
            config=sha256_of(config_snapshot),
        ),
    )
    # Patch run_id onto view for artifact consistency
    view = view.model_copy(update={"run_id": stamp.run_id})

    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(
        out,
        "exit_price_summary.json",
        {
            "schema_version": SCHEMA_VERSION,
            "implemented_phase": IMPLEMENTED_PHASE,
            "run_id": stamp.run_id,
            "bundle": exit_bundle.model_dump(mode="json"),
            "fingerprint": exit_bundle_fingerprint(exit_bundle),
            "investment_value": INVESTMENT_LABEL,
        },
        stamp,
    )

    # SPEC §16.3 required artifact name
    ret_payload = returns.model_dump(mode="json")
    # Cap embedded path_returns for JSON size
    full_n = len(ret_payload.get("path_returns") or [])
    ret_payload["path_returns"] = (ret_payload.get("path_returns") or [])[:200]
    ret_payload["path_returns_note"] = (
        f"JSON embeds at most 200 of {full_n} path-return rows"
    )
    ret_summary = {
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "run_id": stamp.run_id,
        "status": PHASE10_STATUS,
        "investment_value": INVESTMENT_LABEL,
        "spot_price": spot,
        "entry_prices": returns.entry_prices,
        "relative_to_spot": returns.relative_to_spot,
        "horizons_years": returns.horizons_years,
        "compounding_convention": returns.compounding_convention,
        "price_series_convention": returns.price_series_convention,
        "pathwise_higher_p0_cannot_improve": pathwise_ok,
        "content_fingerprint": returns.content_fingerprint,
        "exit_ref": returns.exit_ref,
        "mixture": ret_payload["mixture"],
        "by_market_state": ret_payload.get("by_market_state"),
        "quality_flags": returns.quality_flags,
        "flags": returns.flags,
        "notes": returns.notes,
        "assumptions": returns.assumptions,
        "path_returns_sample": ret_payload["path_returns"],
        "path_returns_note": ret_payload["path_returns_note"],
        "recompute_demo": {
            "prior_fingerprint": recompute_meta.get("prior_fingerprint"),
            "alt_posterior_fingerprint": posterior_fingerprint(alt_post),
            "alt_return_fingerprint": recompute_meta.get("return_fingerprint"),
            "changed_vs_prior": recompute_meta.get("changed_vs_prior"),
            "assumption": recompute_meta.get("assumption"),
        },
        "warning": (
            "Phase 10 Track B return distributions from market exit prices. "
            "Synthetic demo. Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            "No Kelly / portfolio sizing."
        ),
    }
    write_artifact(out, "return_distribution_summary.json", ret_summary, stamp)

    write_artifact(
        out,
        "dsde_export.json",
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": stamp.run_id,
            "availability": dsde_avail,
            "return_export": export.model_dump(mode="json"),
            "consumer_view": view.model_dump(mode="json"),
            "notify": notify_status,
            "note": "Optional public contract only; core runs with DSDE absent.",
        },
        stamp,
    )

    write_artifact(
        out,
        "simulation_metadata.json",
        {
            "status": PHASE10_STATUS,
            "implemented_phase": IMPLEMENTED_PHASE,
            "investment_value": INVESTMENT_LABEL,
            "warning": (
                "Phase 10 return distributions + DSDE-facing contract synthetic demo. "
                "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED."
            ),
            "data_label": "SYNTHETIC — not real market data",
            "seed": seed,
            "metric_id": mid,
            "spot_price": spot,
            "as_of_interpretation": as_of_note if isinstance(as_of_note, str) else AS_OF_DATE_RULE,
            "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
            "as_of_rule": AS_OF_DATE_RULE,
            "dsde_present": dsde_avail["dsde_present"],
        },
        stamp,
    )

    # Mixture cell count for summary
    n_cells = len(returns.mixture)
    n_cells_with_stats = sum(1 for c in returns.mixture if c.stats.get("n", 0) > 0)

    summary = {
        "status": PHASE10_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "metric_id": mid,
        "spot_price": spot,
        "entry_prices": returns.entry_prices,
        "horizons_years": returns.horizons_years,
        "compounding_convention": returns.compounding_convention,
        "n_exit_valid": exit_bundle.n_valid,
        "n_exit_failed": exit_bundle.n_failed,
        "n_return_cells": n_cells,
        "n_return_cells_with_stats": n_cells_with_stats,
        "pathwise_higher_p0_cannot_improve": pathwise_ok,
        "content_fingerprint": returns.content_fingerprint,
        "recompute_changed_vs_prior": bool(recompute_meta.get("changed_vs_prior")),
        "dsde_present": dsde_avail["dsde_present"],
        "dsde_required_for_core": False,
        "default_forbids_intrinsic_copy": exit_bundle.default_forbids_intrinsic_copy,
        "artifacts": [
            "return_distribution_summary.json",
            "exit_price_summary.json",
            "dsde_export.json",
            "config_snapshot.json",
            "simulation_metadata.json",
        ],
    }
    (out / "phase10_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
