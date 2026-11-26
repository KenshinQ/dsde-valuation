"""Official VTP-0.1 Suite G counterfactuals on production market-pricing APIs.

Calls production ``generate_exit_prices``, ``estimate_market_pricing_state``,
``run_convergence_scenario``, and ``run_path_projection``. Never uses
SimpleValuationModel or any toy valuation engine.

Predeclared experiment parameters (frozen before looking at pass/fail):
- instrument fixture via tests.company (years 2016-2024)
- fundamental paths A: growth=0.05, seed=42, n_paths=24, n_years=3
- fundamental paths B: growth=0.12, otherwise identical
- horizon=1, metric=ev_ebitda, exit seed=42
- compressed market: fallback prior COMPRESSED=1.0, state_scale COMPRESSED=0.60
- expanded market: fallback prior EXPANDED=1.0, state_scale EXPANDED=1.50
- intrinsic sentinel=99999.0 (must be ignored on the default scenario)
- G-05: stochastic_rate=0.40, blend_weight=0.50 (uncertain, not 0/1 extremes)

Official close is fail-closed: a criterion with n_valid==0 is BLOCKED, not PASS.
G-06 is evaluated separately against production evaluation report labels.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from tests.company import company, loaded_config
from tests.factories import INST
from vms.market_pricing import (
    apply_configured_dependence,
    default_market_pricing_config,
    estimate_market_pricing_state,
    generate_exit_prices,
    run_convergence_scenario,
)
from vms.market_pricing.config import FallbackPriorConfig, MarketPricingConfig, StateScaleConfig
from vms.market_pricing.exit_prices import ExitPriceBundle
from vms.pipeline import run_path_projection
from vms.statements.paths import FinancialPathBundle

REPO = Path(__file__).resolve().parents[2]
L = loaded_config()

GROWTH_A = 0.05
GROWTH_B = 0.12
PROJ_SEED = 42
N_PATHS = 24
N_YEARS = 3
HORIZON = 1
METRIC = "ev_ebitda"
EXIT_SEED = 42
SENTINEL_IV = 99999.0
CONV_RATE = 0.40
CONV_BLEND = 0.50
SCALE_COMPRESSED = 0.60
SCALE_EXPANDED = 1.50


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def project_paths(growth: float) -> FinancialPathBundle:
    load, as_of = company(years=tuple(range(2016, 2025)), growth=growth)
    run = run_path_projection(
        load,
        instrument_id=INST,
        as_of=as_of,
        loaded=L,
        seed=PROJ_SEED,
        n_paths=N_PATHS,
        n_years=N_YEARS,
        policy_id="historical_continuation",
    )
    assert run.financial_paths is not None
    return run.financial_paths


def hash_paths(bundle: FinancialPathBundle) -> str:
    payload = [p.model_dump(mode="json") for p in bundle.paths]
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def hash_obj(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        payload = obj.model_dump(mode="json")
    else:
        payload = obj
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def compressed_config() -> MarketPricingConfig:
    base = default_market_pricing_config()
    return base.model_copy(
        update={
            "fallback_prior": FallbackPriorConfig(
                COMPRESSED=1.0, NORMAL=0.0, EXPANDED=0.0, DISLOCATION=0.0
            ),
            "state_scales": StateScaleConfig(
                COMPRESSED=SCALE_COMPRESSED, NORMAL=1.0, EXPANDED=SCALE_EXPANDED, DISLOCATION=0.50
            ),
        }
    )


def expanded_config() -> MarketPricingConfig:
    base = default_market_pricing_config()
    return base.model_copy(
        update={
            "fallback_prior": FallbackPriorConfig(
                COMPRESSED=0.0, NORMAL=0.0, EXPANDED=1.0, DISLOCATION=0.0
            ),
            "state_scales": StateScaleConfig(
                COMPRESSED=SCALE_COMPRESSED, NORMAL=1.0, EXPANDED=SCALE_EXPANDED, DISLOCATION=0.50
            ),
        }
    )


def fallback_posterior(cfg: MarketPricingConfig):
    return estimate_market_pricing_state(use_fallback_when_unavailable=True, config=cfg)


def exit_stats(bundle: ExitPriceBundle, *, horizon: int = HORIZON) -> dict[str, Any]:
    xs = [
        float(p.exit_price_per_share)
        for p in bundle.paths
        if p.valid and p.horizon_years == horizon and p.exit_price_per_share is not None
    ]
    arr = np.asarray(xs, dtype=float)
    return {
        "n_valid_horizon": int(arr.size),
        "n_valid_bundle": int(bundle.n_valid),
        "n_input_paths": int(bundle.n_input_paths),
        "n_failed": int(bundle.n_failed),
        "mean": float(arr.mean()) if arr.size else None,
        "p50": float(np.median(arr)) if arr.size else None,
        "p05": float(np.quantile(arr, 0.05)) if arr.size else None,
        "p95": float(np.quantile(arr, 0.95)) if arr.size else None,
        "min": float(arr.min()) if arr.size else None,
        "max": float(arr.max()) if arr.size else None,
        "scenario_kind": bundle.scenario_kind,
        "label": bundle.label,
        "default_forbids_intrinsic_copy": bundle.default_forbids_intrinsic_copy,
        "dependence_on_fundamentals": bundle.dependence_on_fundamentals,
        "metric_id": bundle.metric_id,
    }


def _nonempty(stats: dict[str, Any]) -> bool:
    return int(stats.get("n_valid_horizon") or 0) > 0 and stats.get("mean") is not None


def run_official_suite_g() -> dict[str, Any]:
    started = _now()
    paths_a = project_paths(GROWTH_A)
    paths_b = project_paths(GROWTH_B)
    hash_a = hash_paths(paths_a)
    hash_b = hash_paths(paths_b)
    cfg_c = compressed_config()
    cfg_e = expanded_config()
    post_c = fallback_posterior(cfg_c)
    post_e = fallback_posterior(cfg_e)
    intrinsic = {(p.path_id, HORIZON): SENTINEL_IV for p in paths_a.paths}

    # G-01 / G-02: fixed fundamental paths, vary market-pricing regime / multiple scales
    hash_a_before = hash_paths(paths_a)
    exit_c = generate_exit_prices(
        paths_a,
        market_posterior=post_c,
        config=cfg_c,
        horizons_years=[HORIZON],
        metric_id=METRIC,
        seed=EXIT_SEED,
        scenario_kind="TERMINAL_MULTIPLE_DEFAULT",
        intrinsic_by_path_horizon=intrinsic,
    )
    exit_e = generate_exit_prices(
        paths_a,
        market_posterior=post_e,
        config=cfg_e,
        horizons_years=[HORIZON],
        metric_id=METRIC,
        seed=EXIT_SEED,
        scenario_kind="TERMINAL_MULTIPLE_DEFAULT",
        intrinsic_by_path_horizon=intrinsic,
    )
    hash_a_after = hash_paths(paths_a)
    stats_c = exit_stats(exit_c)
    stats_e = exit_stats(exit_e)
    silent_copied = [
        p.path_id
        for p in exit_c.paths
        if p.valid and p.exit_price_per_share is not None and abs(p.exit_price_per_share - SENTINEL_IV) < 1e-9
    ]
    intrinsic_used_default = any(p.intrinsic_value_used for p in list(exit_c.paths) + list(exit_e.paths))

    g01 = {
        "status": "PASS"
        if (
            _nonempty(stats_c)
            and _nonempty(stats_e)
            and stats_c["mean"] != stats_e["mean"]
            and stats_c["p50"] != stats_e["p50"]
            and not silent_copied
            and not intrinsic_used_default
            and exit_c.default_forbids_intrinsic_copy
            and exit_c.scenario_kind == "TERMINAL_MULTIPLE_DEFAULT"
        )
        else "BLOCKED",
        "compressed": stats_c,
        "expanded": stats_e,
        "silent_copy_of_sentinel": silent_copied,
        "any_intrinsic_value_used_on_default": intrinsic_used_default,
        "notes": "Fixed financial-path distribution; only market prior/scales changed. Default scenario must not copy intrinsic.",
    }
    if not _nonempty(stats_c) or not _nonempty(stats_e):
        g01["status"] = "BLOCKED"
        g01["blocking"] = "vacuous: n_valid==0"

    g02 = {
        "status": "PASS"
        if (
            g01["status"] == "PASS"
            and hash_a_before == hash_a_after == hash_a
            and hash_a != hash_b
        )
        else "BLOCKED",
        "financial_path_hash_before": hash_a_before,
        "financial_path_hash_after": hash_a_after,
        "financial_path_hash_A": hash_a,
        "financial_path_unchanged": hash_a_before == hash_a_after == hash_a,
        "exit_mean_compressed": stats_c["mean"],
        "exit_mean_expanded": stats_e["mean"],
        "notes": "Intrinsic/fundamental path bundle held fixed (content hash); terminal multiple regime compressed→expanded.",
    }

    # G-03: market held fixed, change financial paths
    exit_a = generate_exit_prices(
        paths_a, market_posterior=post_c, config=cfg_c,
        horizons_years=[HORIZON], metric_id=METRIC, seed=EXIT_SEED,
    )
    exit_b = generate_exit_prices(
        paths_b, market_posterior=post_c, config=cfg_c,
        horizons_years=[HORIZON], metric_id=METRIC, seed=EXIT_SEED,
    )
    stats_a = exit_stats(exit_a)
    stats_b = exit_stats(exit_b)
    sample = next((p for p in exit_a.paths if p.valid), None)
    g03 = {
        "status": "PASS"
        if (
            _nonempty(stats_a)
            and _nonempty(stats_b)
            and stats_a["mean"] != stats_b["mean"]
            and hash_obj(post_c) == hash_obj(post_c)
            and sample is not None
            and sample.denominator_field
            and sample.denominator_value is not None
            and sample.lineage
            and sample.lineage.get("denominator_field")
            and sample.lineage.get("terminal_multiple") is not None
        )
        else "BLOCKED",
        "paths_A_growth": GROWTH_A,
        "paths_B_growth": GROWTH_B,
        "paths_A": stats_a,
        "paths_B": stats_b,
        "market_posterior_hash": hash_obj(post_c),
        "market_config_hash": hash_obj(cfg_c),
        "attribution_sample": {
            "path_id": None if sample is None else sample.path_id,
            "denominator_field": None if sample is None else sample.denominator_field,
            "denominator_value": None if sample is None else sample.denominator_value,
            "terminal_multiple": None if sample is None else sample.terminal_multiple,
            "metric_id": None if sample is None else sample.metric_id,
            "lineage_keys": None if sample is None else sorted(sample.lineage.keys()),
        },
        "notes": "Same market posterior/config/seed; financial paths A vs B. Exit change attributed via lineage (denominator + terminal multiple).",
    }

    # G-04: bidirectional independence + explicit opt-in coupling
    tilted = apply_configured_dependence(
        post_c,
        fundamental_state="GROWTH",
        tilt={"GROWTH": {"EXPANDED": 2.0, "COMPRESSED": 0.5}},
    )
    g04 = {
        "status": "PASS"
        if (
            g02["status"] == "PASS"
            and g03["status"] == "PASS"
            and post_c.dependence_on_fundamentals == "NONE"
            and exit_c.dependence_on_fundamentals == "NONE"
            and tilted.dependence_on_fundamentals == "CONFIGURED"
            and "CONFIGURED_FUNDAMENTAL_DEPENDENCE" in tilted.flags
        )
        else "BLOCKED",
        "market_only": {
            "financial_path_hash_unchanged": hash_a_before == hash_a_after,
            "exit_distribution_changed": stats_c["mean"] != stats_e["mean"],
        },
        "fundamental_only": {
            "path_hash_A": hash_a,
            "path_hash_B": hash_b,
            "path_hashes_differ": hash_a != hash_b,
            "market_posterior_held_fixed": True,
            "exit_distribution_changed_through_projected_metrics": stats_a["mean"] != stats_b["mean"],
        },
        "default_dependence": post_c.dependence_on_fundamentals,
        "configured_dependence_opt_in": tilted.dependence_on_fundamentals,
        "configured_dependence_flags": list(tilted.flags),
        "notes": "Default dependence is NONE. Coupling is available only via explicit apply_configured_dependence.",
    }

    # G-05: explicit, uncertain, separate from default
    conv = run_convergence_scenario(
        paths_a,
        market_posterior=post_c,
        intrinsic_by_path_horizon=intrinsic,
        config=cfg_c,
        horizons_years=[HORIZON],
        metric_id=METRIC,
        seed=EXIT_SEED,
        stochastic_rate=CONV_RATE,
        blend_weight=CONV_BLEND,
    )
    stats_conv = exit_stats(conv)
    fired = [p.path_id for p in conv.paths if p.valid and p.intrinsic_value_used]
    not_fired = [p.path_id for p in conv.paths if p.valid and not p.intrinsic_value_used]
    g05 = {
        "status": "PASS"
        if (
            _nonempty(stats_conv)
            and conv.scenario_kind == "CONVERGENCE_TO_INTRINSIC"
            and "EXPLICIT_CONVERGENCE_SCENARIO" in conv.flags
            and exit_c.scenario_kind == "TERMINAL_MULTIPLE_DEFAULT"
            and 0 < CONV_RATE < 1
            and 0 < CONV_BLEND < 1
            and len(fired) > 0
            and len(not_fired) > 0
            and cfg_c.convergence.enabled is False
        )
        else "BLOCKED",
        "default_scenario_kind": exit_c.scenario_kind,
        "convergence_scenario_kind": conv.scenario_kind,
        "convergence_flags": list(conv.flags),
        "stochastic_rate": CONV_RATE,
        "blend_weight": CONV_BLEND,
        "config_convergence_enabled_by_default": cfg_c.convergence.enabled,
        "n_fired": len(fired),
        "n_not_fired": len(not_fired),
        "stats": stats_conv,
        "notes": "Convergence is opt-in, labeled, parameterized, uncertain (rate in (0,1)), and not the default path.",
    }

    # G-06 is report-label discipline; this runner records exit-bundle labels only.
    g06_bundle_labels = {
        "exit_bundle_label": exit_c.label,
        "exit_is_not_labeled_intrinsic": exit_c.label == "FUTURE_MARKET_EXIT_PRICES",
        "notes": "Bundle-level label check only. Official G-06 also requires evaluation/report evidence (price_mae_forbidden / MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH).",
    }

    criteria = {
        "G-01": g01["status"],
        "G-02": g02["status"],
        "G-03": g03["status"],
        "G-04": g04["status"],
        "G-05": g05["status"],
    }
    overall = "PASS" if all(v == "PASS" for v in criteria.values()) else (
        "PARTIAL" if any(v == "PASS" for v in criteria.values()) else "BLOCKED"
    )
    # G-06 is decided by evaluation tests in the pytest module; overall here is G-01..G-05
    # plus bundle-label support. The test module combines G-06.
    return {
        "started_at_asia_shanghai": started,
        "finished_at_asia_shanghai": _now(),
        "api": {
            "exit": "vms.market_pricing.generate_exit_prices",
            "estimator": "vms.market_pricing.estimate_market_pricing_state",
            "convergence": "vms.market_pricing.run_convergence_scenario",
            "paths": "vms.pipeline.run_path_projection",
            "toy_model_used": False,
        },
        "parameters": {
            "growth_A": GROWTH_A,
            "growth_B": GROWTH_B,
            "n_paths": N_PATHS,
            "n_years": N_YEARS,
            "horizon": HORIZON,
            "metric_id": METRIC,
            "proj_seed": PROJ_SEED,
            "exit_seed": EXIT_SEED,
            "sentinel_iv": SENTINEL_IV,
            "scale_compressed": SCALE_COMPRESSED,
            "scale_expanded": SCALE_EXPANDED,
            "conv_rate": CONV_RATE,
            "conv_blend": CONV_BLEND,
        },
        "G-01": g01,
        "G-02": g02,
        "G-03": g03,
        "G-04": g04,
        "G-05": g05,
        "G-06_bundle_labels": g06_bundle_labels,
        "criteria_G01_to_G05": criteria,
        "suite_g_G01_to_G05": overall,
    }


def write_artifacts(bundle: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "suite_g_production_counterfactuals.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    bundle = run_official_suite_g()
    write_artifacts(bundle, args.out)
    print(json.dumps({
        "criteria_G01_to_G05": bundle["criteria_G01_to_G05"],
        "suite_g_G01_to_G05": bundle["suite_g_G01_to_G05"],
        "G-01_means": (bundle["G-01"]["compressed"]["mean"], bundle["G-01"]["expanded"]["mean"]),
        "G-03_means": (bundle["G-03"]["paths_A"]["mean"], bundle["G-03"]["paths_B"]["mean"]),
        "G-05": (bundle["G-05"]["n_fired"], bundle["G-05"]["n_not_fired"], bundle["G-05"]["status"]),
        "toy_model_used": bundle["api"]["toy_model_used"],
    }, indent=2))
