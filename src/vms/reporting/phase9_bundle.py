"""VMS-0.2 Phase 9 offline market-pricing / exit-price demo (SPEC §20 Phase 9).

Independent market-state estimator, terminal-multiple exit prices, persistence vs
mean-reversion sensitivity. Default never copies intrinsic → exit.
INVESTMENT_VALUE_NOT_ESTABLISHED.
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
from vms.market_pricing import (
    compare_persistence_vs_mean_reversion,
    estimate_market_pricing_state,
    generate_exit_prices,
    run_convergence_scenario,
)
from vms.market_pricing.config import default_market_pricing_config
from vms.pipeline import run_path_projection
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.schemas.config import load_config

PHASE9_STATUS = "PHASE9_MARKET_PRICING_EXIT_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = "INVESTMENT_VALUE_NOT_ESTABLISHED"


class Phase9BundleError(ValueError):
    pass


def build_phase9_bundle(
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
    include_convergence_demo: bool = True,
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
        raise Phase9BundleError(f"paths must be > 0 (got {paths})")
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
        raise Phase9BundleError(
            f"path bundle unsupported/empty: profile={run.resolution.status.value} "
            f"reason={run.resolution.reason}"
        )

    # Independent market-pricing estimator: no fundamental-regime input.
    # Synthetic demos usually lack long multiple history → fallback prior (AC2).
    market_post = estimate_market_pricing_state(
        current_multiple=None,
        historical_multiples=[],
        config=mp_cfg,
        use_fallback_when_unavailable=True,
    )
    # Also demonstrate z-score path when history is supplied (offline toy series).
    toy_hist = [7.0, 7.5, 8.0, 8.2, 7.8, 9.0, 8.5, 8.1, 7.9, 8.3, 8.4, 8.0, 7.7, 8.6]
    market_post_with_hist = estimate_market_pricing_state(
        current_multiple=8.0,
        historical_multiples=toy_hist,
        config=mp_cfg.model_copy(update={"min_history_obs_for_estimation": 8}),
        use_fallback_when_unavailable=True,
    )

    sens_report, sens_bundles = compare_persistence_vs_mean_reversion(
        run.financial_paths,
        market_posterior=market_post,
        config=mp_cfg,
        horizons_years=horizons_years,
        metric_id=mid,
        seed=seed,
    )
    default_bundle = sens_bundles["CONSTANT_STATE_PERSISTENCE"]

    convergence_payload = None
    if include_convergence_demo:
        # Build a labeled intrinsic map that is INTENTIONALLY different from market exits
        intrinsic_map: dict[tuple[str, int], float] = {}
        for p in default_bundle.paths:
            if p.valid and p.exit_price_per_share is not None:
                # Distinct from exit: 1.5x exit so equality would be detectable
                intrinsic_map[(p.path_id, p.horizon_years)] = float(p.exit_price_per_share) * 1.5
        conv = run_convergence_scenario(
            run.financial_paths,
            market_posterior=market_post,
            intrinsic_by_path_horizon=intrinsic_map,
            config=mp_cfg,
            horizons_years=horizons_years,
            metric_id=mid,
            seed=seed + 7,
            stochastic_rate=0.5,
            blend_weight=0.4,
        )
        convergence_payload = conv.model_dump(mode="json")

    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "metric_id": mid,
        "horizons_years": horizons_years,
        "paths": paths,
        "years": years,
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase9",
            instrument=synthetic.SYNTHETIC_INSTRUMENT,
            as_of=as_of.isoformat(),
            seed=seed,
            metric=mid,
            config=sha256_of(config_snapshot),
        ),
    )
    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(
        out,
        "financial_path_summary.json",
        {
            "n_valid": run.financial_paths.n_valid,
            "n_failed": run.financial_paths.n_failed,
            "years": run.financial_paths.years,
            "schema_version": SCHEMA_VERSION,
            "implemented_phase": IMPLEMENTED_PHASE,
        },
        stamp,
    )

    market_pricing_report = {
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "run_id": stamp.run_id,
        "posterior_fallback": market_post.model_dump(mode="json"),
        "posterior_with_history_demo": market_post_with_hist.model_dump(mode="json"),
        "dependence_mode": mp_cfg.dependence.mode,
        "fundamental_regimes_used_for_estimation": False,
        "persistence_sensitivity": sens_report.model_dump(mode="json"),
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Phase 9 market-pricing / exit-price synthetic demo. "
            "Default exit prices use terminal multiples — NOT intrinsic value. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED."
        ),
    }
    write_artifact(out, "market_pricing_report.json", market_pricing_report, stamp)

    exit_summary = {
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "run_id": stamp.run_id,
        "default_scenario": default_bundle.model_dump(mode="json"),
        "slow_mr_scenario": sens_bundles["CONFIGURED_SLOW_MEAN_REVERSION"].model_dump(mode="json"),
        "fast_mr_scenario": sens_bundles["CONFIGURED_FAST_MEAN_REVERSION"].model_dump(mode="json"),
        "convergence_scenario": convergence_payload,
        "default_forbids_intrinsic_copy": default_bundle.default_forbids_intrinsic_copy,
        "investment_value": INVESTMENT_LABEL,
    }
    write_artifact(out, "exit_price_summary.json", exit_summary, stamp)

    # Path lineage sample (capped)
    lineage_rows = []
    for p in default_bundle.paths:
        if not p.valid:
            continue
        lineage_rows.append(
            {
                "path_id": p.path_id,
                "horizon_years": p.horizon_years,
                "metric_id": p.metric_id,
                "terminal_multiple": p.terminal_multiple,
                "terminal_market_state": p.terminal_market_state,
                "denominator_field": p.denominator_field,
                "denominator_value": p.denominator_value,
                "diluted_shares": p.diluted_shares,
                "claim_object": p.claim_object,
                "enterprise_value": p.enterprise_value,
                "equity_value": p.equity_value,
                "exit_price_per_share": p.exit_price_per_share,
                "bridge": p.bridge,
                "scenario_kind": p.scenario_kind,
                "intrinsic_value_used": p.intrinsic_value_used,
                "reason_codes": p.reason_codes,
                "lineage": p.lineage,
            }
        )
        if len(lineage_rows) >= 80:
            break
    write_artifact(
        out,
        "exit_price_path_lineage.json",
        {
            "schema_version": SCHEMA_VERSION,
            "n_rows": len(lineage_rows),
            "rows": lineage_rows,
            "note": "Lineage preserves metric/multiple/bridge/share-count (SPEC §14.4 / Phase 9 AC4).",
        },
        stamp,
    )

    write_artifact(
        out,
        "simulation_metadata.json",
        {
            "status": PHASE9_STATUS,
            "implemented_phase": IMPLEMENTED_PHASE,
            "investment_value": INVESTMENT_LABEL,
            "warning": (
                "Phase 9 market-pricing regime + exit-price engine synthetic demo. "
                "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED."
            ),
            "data_label": "SYNTHETIC — not real market data",
            "seed": seed,
            "metric_id": mid,
            "market_pricing_status": market_post.status,
            "market_pricing_confidence": market_post.confidence,
            "as_of_interpretation": as_of_note if isinstance(as_of_note, str) else AS_OF_DATE_RULE,
            "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
            "as_of_rule": AS_OF_DATE_RULE,
        },
        stamp,
    )

    # Quick check: default paths must not mark intrinsic_value_used
    silent_copy = any(
        p.intrinsic_value_used for p in default_bundle.paths if p.scenario_kind == "TERMINAL_MULTIPLE_DEFAULT"
    )

    summary = {
        "status": PHASE9_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "metric_id": mid,
        "horizons_years": horizons_years,
        "n_paths_input": default_bundle.n_input_paths,
        "n_exit_valid": default_bundle.n_valid,
        "n_exit_failed": default_bundle.n_failed,
        "market_pricing_status": market_post.status,
        "market_pricing_confidence": market_post.confidence,
        "market_pricing_fallback": "MARKET_PRICING_FALLBACK_PRIOR" in market_post.flags,
        "fundamental_regimes_used_for_estimation": False,
        "dependence_mode": mp_cfg.dependence.mode,
        "persistence_baseline_model": sens_report.baseline_model_id,
        "mean_reversion_estimation_status": sens_report.mean_reversion_estimation_status,
        "default_forbids_intrinsic_copy": default_bundle.default_forbids_intrinsic_copy,
        "default_silent_intrinsic_copy_detected": silent_copy,
        "convergence_demo_included": convergence_payload is not None,
        "exit_summaries_persistence": default_bundle.summaries,
        "artifacts": [
            "market_pricing_report.json",
            "exit_price_summary.json",
            "exit_price_path_lineage.json",
            "financial_path_summary.json",
        ],
    }
    (out / "phase9_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
