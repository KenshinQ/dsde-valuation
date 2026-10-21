"""Exit-price generation engine (SPEC §14.4 / Phase 9).

Default path: terminal multiple × future metric → bridge → per-share exit price.
NEVER silently copies intrinsic/fundamental value to future market price
(MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1).
"""

from __future__ import annotations

import math
from typing import Any, Literal, Mapping, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.equity_bridge.bridge import bridge_ev_to_equity
from vms.market_pricing.config import MarketPricingConfig, default_market_pricing_config
from vms.market_pricing.estimator import sample_state
from vms.market_pricing.path_metrics import extract_horizon_metrics
from vms.market_pricing.schemas import MarketPricingStatePosterior
from vms.market_pricing.terminal_multiples import metric_is_ev, sample_terminal_multiple
from vms.market_pricing.transitions import TransitionModel, constant_state_persistence, evolve_state
from vms.methods.multiples.apply import apply_equity_multiple, apply_ev_multiple
from vms.methods.multiples.definitions import get_definition
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord

EXIT_PRICE_VERSION = "EXIT-PRICE-1"
ScenarioKind = Literal["TERMINAL_MULTIPLE_DEFAULT", "CONVERGENCE_TO_INTRINSIC"]


class ExitPricePath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path_id: str
    horizon_years: int
    calendar_year: int | None
    valid: bool
    invalid_reason: str | None = None
    scenario_kind: ScenarioKind
    transition_model_id: str
    # Market-pricing lineage
    initial_market_state: str | None = None
    terminal_market_state: str | None = None
    # Multiple / metric lineage
    metric_id: str | None = None
    denominator_field: str | None = None
    denominator_value: float | None = None
    terminal_multiple: float | None = None
    # Bridge / shares lineage
    claim_object: str | None = None
    enterprise_value: float | None = None
    equity_value: float | None = None
    diluted_shares: float | None = None
    exit_price_per_share: float | None = None
    bridge: dict[str, Any] | None = None
    # Explicit: intrinsic was NOT used unless scenario_kind says so
    intrinsic_value_used: bool = False
    intrinsic_value_per_share: float | None = None
    flags: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    lineage: dict[str, Any] = Field(default_factory=dict)


class ExitPriceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_kind: Literal["ExitPriceBundle"] = "ExitPriceBundle"
    version: str = EXIT_PRICE_VERSION
    label: str = "FUTURE_MARKET_EXIT_PRICES"
    scenario_kind: ScenarioKind
    transition_model_id: str
    metric_id: str
    horizons_years: list[int]
    n_input_paths: int
    n_valid: int
    n_failed: int
    paths: list[ExitPricePath]
    summaries: dict[str, Any] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # Hard invariant markers for acceptance / property tests
    default_forbids_intrinsic_copy: bool = True
    dependence_on_fundamentals: Literal["NONE", "CONFIGURED"] = "NONE"


def _summarize(paths: list[ExitPricePath], horizons: Sequence[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for h in horizons:
        xs = np.array(
            [p.exit_price_per_share for p in paths if p.horizon_years == h and p.valid and p.exit_price_per_share is not None],
            dtype=float,
        )
        xs = xs[np.isfinite(xs)]
        key = str(h)
        if xs.size == 0:
            out[key] = {"n_valid": 0}
            continue
        out[key] = {
            "n_valid": int(xs.size),
            "mean": float(xs.mean()),
            "p50": float(np.median(xs)),
            "p05": float(np.quantile(xs, 0.05)),
            "p95": float(np.quantile(xs, 0.95)),
        }
    return out


def generate_exit_prices(
    financial_paths: FinancialPathBundle | Sequence[FinancialPathRecord],
    *,
    market_posterior: MarketPricingStatePosterior,
    config: MarketPricingConfig | None = None,
    horizons_years: Sequence[int] = (1, 3),
    metric_id: str | None = None,
    transition_model: TransitionModel | None = None,
    seed: int = 42,
    scenario_kind: ScenarioKind = "TERMINAL_MULTIPLE_DEFAULT",
    intrinsic_by_path_horizon: Mapping[tuple[str, int], float] | None = None,
    convergence_rate: float | None = None,
    convergence_blend: float | None = None,
    profile_scale: float = 1.0,
) -> ExitPriceBundle:
    """Generate exit-price paths. Default scenario never copies intrinsic → exit."""
    cfg = config or default_market_pricing_config()
    mid = metric_id or cfg.default_metric_id
    trans = transition_model or constant_state_persistence()
    assumptions = cite(
        "EXIT-PRICE-TERMINAL-MULTIPLE-v1",
        "EXIT-PRICE-LINEAGE-v1",
        "MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1",
        "MARKET-PRICING-INDEPENDENT-v1",
        "MARKET-PRICING-PERSISTENCE-BASELINE-v1",
        "EV-EQUITY-BRIDGE-v1",
        "NO-DOUBLE-EV-BRIDGE-v1",
    )
    if scenario_kind == "CONVERGENCE_TO_INTRINSIC":
        assumptions = sorted(
            set(assumptions)
            | set(cite("CONVERGENCE-SCENARIO-EXPLICIT-v1", "MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1"))
        )
        if intrinsic_by_path_horizon is None:
            raise ValueError("CONVERGENCE_TO_INTRINSIC requires intrinsic_by_path_horizon")
        if not cfg.convergence.enabled and convergence_rate is None:
            raise ValueError(
                "CONVERGENCE_TO_INTRINSIC requires config.convergence.enabled "
                "or an explicit convergence_rate argument"
            )

    if isinstance(financial_paths, FinancialPathBundle):
        records = [r for r in financial_paths.paths if r.path_id != "central"]
        if not records:
            records = list(financial_paths.paths)
    else:
        records = list(financial_paths)

    rng = np.random.default_rng(seed)
    out_paths: list[ExitPricePath] = []
    flags_bundle: list[str] = ["DEFAULT_FORBIDS_INTRINSIC_COPY"]
    if scenario_kind == "CONVERGENCE_TO_INTRINSIC":
        flags_bundle.append("EXPLICIT_CONVERGENCE_SCENARIO")

    rate = (
        float(convergence_rate)
        if convergence_rate is not None
        else float(cfg.convergence.stochastic_rate)
    )
    blend = (
        float(convergence_blend)
        if convergence_blend is not None
        else float(cfg.convergence.blend_weight)
    )

    for rec in records:
        for h in horizons_years:
            path_flags: list[str] = []
            reason_codes: list[str] = []
            # 1. Future financial metrics from fundamental path
            hm = extract_horizon_metrics(rec, horizon_years=int(h), metric_id=mid)
            if not hm.valid:
                out_paths.append(
                    ExitPricePath(
                        path_id=rec.path_id,
                        horizon_years=int(h),
                        calendar_year=hm.calendar_year,
                        valid=False,
                        invalid_reason=hm.invalid_reason,
                        scenario_kind=scenario_kind,
                        transition_model_id=trans.model_id,
                        metric_id=mid,
                        denominator_field=hm.denominator_field,
                        denominator_value=hm.denominator_value,
                        diluted_shares=hm.diluted_shares,
                        intrinsic_value_used=False,
                        flags=sorted(set(hm.flags) | {"EXIT_METRIC_GATE"}),
                        reason_codes=[hm.invalid_reason or "METRIC_GATE"],
                        assumptions=assumptions,
                        lineage=hm.lineage,
                    )
                )
                continue

            # 2. Sample initial market-pricing state (independent of fundamental path state)
            init_state, sflags = sample_state(
                market_posterior, rng=rng, fallback_prior=cfg.fallback_prior.as_dict()
            )
            path_flags.extend(sflags)
            # State transition over horizon
            term_state = evolve_state(init_state, trans, horizon_years=int(h), rng=rng)

            # 3. Sample terminal multiple conditional on state / metric
            td = sample_terminal_multiple(
                metric_id=mid,
                market_pricing_state=term_state,
                rng=rng,
                config=cfg,
                profile_scale=profile_scale,
            )
            if not td.valid or td.multiple is None:
                out_paths.append(
                    ExitPricePath(
                        path_id=rec.path_id,
                        horizon_years=int(h),
                        calendar_year=hm.calendar_year,
                        valid=False,
                        invalid_reason=td.invalid_reason,
                        scenario_kind=scenario_kind,
                        transition_model_id=trans.model_id,
                        initial_market_state=init_state,
                        terminal_market_state=term_state,
                        metric_id=mid,
                        denominator_field=hm.denominator_field,
                        denominator_value=hm.denominator_value,
                        diluted_shares=hm.diluted_shares,
                        intrinsic_value_used=False,
                        flags=sorted(set(path_flags) | set(td.flags)),
                        reason_codes=[td.invalid_reason or "MULTIPLE_INVALID"],
                        assumptions=assumptions,
                        lineage={**hm.lineage, "terminal_multiple_draw": td.model_dump(mode="json")},
                    )
                )
                continue

            # 4–5. Bridge + share count
            defn = get_definition(mid)
            bridge_dict = None
            ev = None
            equity = None
            vps = None
            if metric_is_ev(mid):
                mv = apply_ev_multiple(
                    definition=defn,
                    multiple=td.multiple,
                    denominator=float(hm.denominator_value),
                    cash=float(hm.cash or 0.0),
                    debt=float(hm.debt or 0.0),
                    lease_debt_like=cfg.lease_debt_like,
                    minority_interest_book=cfg.minority_interest_book,
                    other_senior_claims=cfg.other_senior_claims,
                    diluted_shares=float(hm.diluted_shares),
                )
            else:
                mv = apply_equity_multiple(
                    definition=defn,
                    multiple=td.multiple,
                    denominator=float(hm.denominator_value),
                    diluted_shares=float(hm.diluted_shares),
                )
            if not mv.valid:
                out_paths.append(
                    ExitPricePath(
                        path_id=rec.path_id,
                        horizon_years=int(h),
                        calendar_year=hm.calendar_year,
                        valid=False,
                        invalid_reason=mv.invalid_reason,
                        scenario_kind=scenario_kind,
                        transition_model_id=trans.model_id,
                        initial_market_state=init_state,
                        terminal_market_state=term_state,
                        metric_id=mid,
                        denominator_field=hm.denominator_field,
                        denominator_value=hm.denominator_value,
                        terminal_multiple=td.multiple,
                        claim_object=defn.claim_object.value,
                        diluted_shares=hm.diluted_shares,
                        bridge=mv.bridge,
                        intrinsic_value_used=False,
                        flags=sorted(set(path_flags) | set(mv.flags)),
                        reason_codes=[mv.invalid_reason or "BRIDGE_FAIL"],
                        assumptions=assumptions,
                        lineage={
                            **hm.lineage,
                            "terminal_multiple": td.multiple,
                            "bridge": mv.bridge,
                        },
                    )
                )
                continue

            ev = mv.enterprise_value
            equity = mv.equity_value
            vps = mv.value_per_share
            bridge_dict = mv.bridge
            intrinsic_used = False
            intrinsic_vps = None
            reason_codes.append("TERMINAL_MULTIPLE_APPLIED")

            # 6. Optional explicit convergence (never default)
            if scenario_kind == "CONVERGENCE_TO_INTRINSIC":
                key = (rec.path_id, int(h))
                intrinsic_vps = (
                    None if intrinsic_by_path_horizon is None else intrinsic_by_path_horizon.get(key)
                )
                if intrinsic_vps is None or not math.isfinite(intrinsic_vps):
                    out_paths.append(
                        ExitPricePath(
                            path_id=rec.path_id,
                            horizon_years=int(h),
                            calendar_year=hm.calendar_year,
                            valid=False,
                            invalid_reason="MISSING_INTRINSIC_FOR_CONVERGENCE",
                            scenario_kind=scenario_kind,
                            transition_model_id=trans.model_id,
                            initial_market_state=init_state,
                            terminal_market_state=term_state,
                            metric_id=mid,
                            denominator_field=hm.denominator_field,
                            denominator_value=hm.denominator_value,
                            terminal_multiple=td.multiple,
                            claim_object=defn.claim_object.value,
                            enterprise_value=ev,
                            equity_value=equity,
                            diluted_shares=hm.diluted_shares,
                            exit_price_per_share=vps,
                            bridge=bridge_dict,
                            intrinsic_value_used=False,
                            flags=sorted(path_flags + ["CONVERGENCE_INTRINSIC_MISSING"]),
                            reason_codes=["MISSING_INTRINSIC_FOR_CONVERGENCE"],
                            assumptions=assumptions,
                            lineage={**hm.lineage, "terminal_multiple": td.multiple},
                        )
                    )
                    continue
                u = float(rng.random())
                if u < rate:
                    # Blend market exit toward intrinsic
                    assert vps is not None
                    vps = (1.0 - blend) * vps + blend * float(intrinsic_vps)
                    intrinsic_used = True
                    path_flags.append("CONVERGENCE_FIRED")
                    reason_codes.append("CONVERGENCE_BLEND_APPLIED")
                else:
                    path_flags.append("CONVERGENCE_NOT_FIRED")
                    reason_codes.append("CONVERGENCE_SKIPPED_STOCHASTIC")
            else:
                # Hard guard: reject any attempt to pass intrinsic as silent default
                if intrinsic_by_path_horizon is not None:
                    path_flags.append("INTRINSIC_MAP_IGNORED_IN_DEFAULT_SCENARIO")
                    reason_codes.append("NO_SILENT_INTRINSIC_COPY")

            if vps is None or not math.isfinite(vps):
                out_paths.append(
                    ExitPricePath(
                        path_id=rec.path_id,
                        horizon_years=int(h),
                        calendar_year=hm.calendar_year,
                        valid=False,
                        invalid_reason="NONFINITE_EXIT_PRICE",
                        scenario_kind=scenario_kind,
                        transition_model_id=trans.model_id,
                        initial_market_state=init_state,
                        terminal_market_state=term_state,
                        metric_id=mid,
                        terminal_multiple=td.multiple,
                        diluted_shares=hm.diluted_shares,
                        intrinsic_value_used=intrinsic_used,
                        flags=sorted(path_flags),
                        reason_codes=reason_codes + ["NONFINITE_EXIT_PRICE"],
                        assumptions=assumptions,
                    )
                )
                continue

            lineage = {
                **hm.lineage,
                "initial_market_state": init_state,
                "terminal_market_state": term_state,
                "transition_model_id": trans.model_id,
                "metric_id": mid,
                "terminal_multiple": td.multiple,
                "state_scale": td.state_scale,
                "base_center": td.base_center,
                "claim_object": defn.claim_object.value,
                "applies_ev_bridge": defn.applies_ev_bridge,
                "enterprise_value": ev,
                "equity_value": equity,
                "diluted_shares": hm.diluted_shares,
                "exit_price_per_share": vps,
                "bridge": bridge_dict,
                "scenario_kind": scenario_kind,
                "intrinsic_value_used": intrinsic_used,
            }
            out_paths.append(
                ExitPricePath(
                    path_id=rec.path_id,
                    horizon_years=int(h),
                    calendar_year=hm.calendar_year,
                    valid=True,
                    scenario_kind=scenario_kind,
                    transition_model_id=trans.model_id,
                    initial_market_state=init_state,
                    terminal_market_state=term_state,
                    metric_id=mid,
                    denominator_field=hm.denominator_field,
                    denominator_value=hm.denominator_value,
                    terminal_multiple=td.multiple,
                    claim_object=defn.claim_object.value,
                    enterprise_value=ev,
                    equity_value=equity,
                    diluted_shares=hm.diluted_shares,
                    exit_price_per_share=vps,
                    bridge=bridge_dict,
                    intrinsic_value_used=intrinsic_used,
                    intrinsic_value_per_share=intrinsic_vps,
                    flags=sorted(set(path_flags) | set(td.flags) | set(mv.flags)),
                    reason_codes=reason_codes,
                    assumptions=assumptions,
                    lineage=lineage,
                )
            )

    n_valid = sum(1 for p in out_paths if p.valid)
    n_failed = len(out_paths) - n_valid
    notes = [
        "Exit prices are future market prices under terminal-multiple model — not intrinsic value.",
        "INVESTMENT_VALUE_NOT_ESTABLISHED.",
        f"scenario_kind={scenario_kind}; transition={trans.model_id}.",
    ]
    if scenario_kind == "TERMINAL_MULTIPLE_DEFAULT":
        notes.append(
            "Default forbids copying intrinsic/fundamental value to exit price "
            "(MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1)."
        )
    return ExitPriceBundle(
        scenario_kind=scenario_kind,
        transition_model_id=trans.model_id,
        metric_id=mid,
        horizons_years=[int(h) for h in horizons_years],
        n_input_paths=len(records),
        n_valid=n_valid,
        n_failed=n_failed,
        paths=out_paths,
        summaries=_summarize(out_paths, horizons_years),
        flags=sorted(set(flags_bundle)),
        assumptions=assumptions,
        notes=notes,
        default_forbids_intrinsic_copy=True,
        dependence_on_fundamentals=market_posterior.dependence_on_fundamentals,
    )


# Re-export bridge helper for tests that want a direct non-path check
def bridge_only_ev(*, enterprise_value: float, cash: float, debt: float, shares: float):
    return bridge_ev_to_equity(
        enterprise_value=enterprise_value,
        cash=cash,
        debt=debt,
        lease_debt_like=0.0,
        minority_interest_book=0.0,
        other_senior_claims=0.0,
        diluted_shares=shares,
    )
