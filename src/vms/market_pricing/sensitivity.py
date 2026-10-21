"""Persistence vs mean-reversion sensitivity for exit prices (SPEC §14.5 / Phase 9 AC5)."""

from __future__ import annotations

from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.market_pricing.config import MarketPricingConfig, default_market_pricing_config
from vms.market_pricing.exit_prices import ExitPriceBundle, generate_exit_prices
from vms.market_pricing.schemas import MarketPricingStatePosterior
from vms.market_pricing.transitions import build_transition_models
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord


class PersistenceSensitivityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_kind: str = "PersistenceSensitivityReport"
    baseline_model_id: str
    models_compared: list[str]
    # Per-model exit summaries keyed by transition model_id
    by_model: dict[str, dict[str, Any]]
    # Delta of median exit price vs persistence baseline, by horizon
    delta_median_vs_baseline: dict[str, dict[str, float | None]]
    mean_reversion_estimation_status: str
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def compare_persistence_vs_mean_reversion(
    financial_paths: FinancialPathBundle | Sequence[FinancialPathRecord],
    *,
    market_posterior: MarketPricingStatePosterior,
    config: MarketPricingConfig | None = None,
    horizons_years: Sequence[int] = (1, 3),
    metric_id: str | None = None,
    seed: int = 42,
) -> tuple[PersistenceSensitivityReport, dict[str, ExitPriceBundle]]:
    """Run constant-state baseline + slow/fast configured MR; report sensitivity."""
    cfg = config or default_market_pricing_config()
    models = build_transition_models(cfg)
    bundles: dict[str, ExitPriceBundle] = {}
    by_model: dict[str, dict[str, Any]] = {}
    for m in models:
        b = generate_exit_prices(
            financial_paths,
            market_posterior=market_posterior,
            config=cfg,
            horizons_years=horizons_years,
            metric_id=metric_id,
            transition_model=m,
            seed=seed,
            scenario_kind="TERMINAL_MULTIPLE_DEFAULT",
        )
        bundles[m.model_id] = b
        by_model[m.model_id] = {
            "estimation_status": m.estimation_status,
            "n_valid": b.n_valid,
            "n_failed": b.n_failed,
            "summaries": b.summaries,
            "flags": m.flags,
            "notes": m.notes,
        }

    baseline_id = "CONSTANT_STATE_PERSISTENCE"
    baseline = by_model[baseline_id]["summaries"]
    deltas: dict[str, dict[str, float | None]] = {}
    for mid, block in by_model.items():
        if mid == baseline_id:
            continue
        d_h: dict[str, float | None] = {}
        for h, summ in block["summaries"].items():
            bmed = baseline.get(h, {}).get("p50")
            med = summ.get("p50")
            if bmed is None or med is None:
                d_h[h] = None
            else:
                d_h[h] = float(med) - float(bmed)
        deltas[mid] = d_h

    mr_status = cfg.mean_reversion.estimation_status
    flags = ["PERSISTENCE_BASELINE_ALWAYS_RUN"]
    if mr_status == "UNSUPPORTED":
        flags.append("MEAN_REVERSION_ESTIMATION_UNSUPPORTED")
    notes = [
        "Constant/current-state persistence baseline always runs (SPEC §14.5).",
        "Slow/fast mean-reversion use configured rates only — not estimated from short series.",
        f"mean_reversion.estimation_status={mr_status}.",
        "INVESTMENT_VALUE_NOT_ESTABLISHED.",
    ]
    report = PersistenceSensitivityReport(
        baseline_model_id=baseline_id,
        models_compared=[m.model_id for m in models],
        by_model=by_model,
        delta_median_vs_baseline=deltas,
        mean_reversion_estimation_status=mr_status,
        flags=sorted(flags),
        assumptions=cite(
            "MARKET-PRICING-PERSISTENCE-BASELINE-v1",
            "MARKET-PRICING-ESTIMATOR-PHASE9-v1",
            "EXIT-PRICE-TERMINAL-MULTIPLE-v1",
        ),
        notes=notes,
    )
    return report, bundles
