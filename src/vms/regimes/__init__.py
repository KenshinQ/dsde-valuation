"""Fundamental regimes (SPEC §7.4). Phase 3: implemented (rule-based baseline; HMM = interface only).

Inference sees PIT *financial* records only, never prices or returns (REGIME-PIT-FUNDAMENTALS-ONLY-v1).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from vms.pit.snapshot import SnapshotFinancial
from vms.regimes.features import fundamental_features
from vms.regimes.hmm import HiddenMarkovRegimeModel, RegimeModel, RegimeModelNotImplemented
from vms.regimes.market import market_regime
from vms.regimes.rule_based import RuleBasedClassifier
from vms.regimes.schemas import (FeatureRow, FundamentalRegimePosterior, MarketRegimePosterior, PeriodPosterior,
                                 TransitionModel, validate_probabilities)
from vms.regimes.transitions import estimate_transitions, propagate
from vms.schemas.config import RegimeConfig

__all__ = ["FeatureRow", "FundamentalRegimePosterior", "HiddenMarkovRegimeModel", "MarketRegimePosterior",
           "PeriodPosterior", "RegimeModel", "RegimeModelNotImplemented", "RegimeResult", "TransitionModel",
           "estimate_transitions", "fundamental_features", "infer_regimes", "make_regime_model", "propagate",
           "validate_probabilities"]


class RegimeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    features: list[FeatureRow]
    history: list[PeriodPosterior]
    current: FundamentalRegimePosterior
    next_year: dict[str, float]
    transitions: TransitionModel
    market: MarketRegimePosterior
    hmm_status: str = HiddenMarkovRegimeModel.status


def make_regime_model(cfg: RegimeConfig) -> RegimeModel:
    if cfg.model == "rule_based":
        return RuleBasedClassifier(cfg)
    return HiddenMarkovRegimeModel(cfg)   # raises RegimeModelNotImplemented


def infer_regimes(financials: Sequence[SnapshotFinancial], *, as_of: datetime, cfg: RegimeConfig) -> RegimeResult:
    """Features -> filtered posteriors -> current posterior + annual transitions. Financials only."""
    model = make_regime_model(cfg)
    rows = fundamental_features(financials)
    hist = model.filter(rows)
    cur = model.current(hist, as_of)
    tm = estimate_transitions(hist, cfg, rows[0].cadence if rows else None)
    return RegimeResult(features=rows, history=hist, current=cur, next_year=propagate(cur.probabilities, tm),
                        transitions=tm, market=market_regime(cfg.market_regime_source))
