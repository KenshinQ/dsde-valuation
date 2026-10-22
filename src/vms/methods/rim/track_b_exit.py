"""R2d: RIM book paths → own-hist P/B exit multiples → Track B return distributions.

Exit multiple family is centered on the subject's own historical common-equity P/B
(raw close / common BPS). Default market-pricing pb center=2.0 is NOT used.
If hist P/B points < MIN_HIST_PB_POINTS → channel status UNAVAILABLE (explicit).
Never silently copies intrinsic VPS to future market exit price.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from vms.assumptions import cite
from vms.market_pricing.config import (
    MarketPricingConfig,
    TerminalMultipleFamilyConfig,
    default_market_pricing_config,
)
from vms.market_pricing.estimator import estimate_market_pricing_state
from vms.market_pricing.exit_prices import ExitPriceBundle, generate_exit_prices
from vms.methods.rim.book_paths import build_rim_book_path_bundle
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS, historical_common_pb, subject_spot_raw_close
from vms.methods.rim.from_snapshot import RimBridgeResult
from vms.pit.snapshot import PITSnapshot
from vms.returns.track_b import (
    ReturnDistributionBundleTrackB,
    build_return_distributions_from_exit_prices,
)
from vms.schemas.config import LoadedConfig
from vms.statements.paths import FinancialPathBundle


@dataclass(frozen=True)
class RimTrackBResult:
    ok: bool
    status: str  # VALID | UNAVAILABLE | INELIGIBLE
    ineligible_reason: str | None
    flags: list[str]
    assumption_ids: list[str]
    hist_pb: dict[str, Any]
    exit_prices: dict[str, Any] | None
    returns: dict[str, Any] | None
    spot_price: float | None
    pb_center_used: float | None
    n_book_paths: int
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "ineligible_reason": self.ineligible_reason,
            "flags": list(self.flags),
            "assumption_ids": list(self.assumption_ids),
            "hist_pb": self.hist_pb,
            "exit_prices": self.exit_prices,
            "returns": self.returns,
            "spot_price": self.spot_price,
            "pb_center_used": self.pb_center_used,
            "n_book_paths": self.n_book_paths,
            "detail": self.detail,
            "metric_id": "pb",
            "exit_multiple_source": "OWN_HIST_COMMON_PB",
            "default_pb_center_2_forbidden": True,
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "ensemble": None,
        }


def _pb_family_from_hist(
    *,
    center: float,
    base: MarketPricingConfig,
) -> MarketPricingConfig:
    """Replace pb family center with own-hist median; keep other families for schema validity."""
    families: list[TerminalMultipleFamilyConfig] = []
    for f in base.families:
        if f.metric_id == "pb":
            # widen bounds around hist center but never invent a 2.0 default
            lo = max(0.05, min(f.min_multiple, center * 0.25))
            hi = max(f.max_multiple, center * 4.0, center + 1.0)
            families.append(
                TerminalMultipleFamilyConfig(
                    metric_id="pb",
                    center=float(center),
                    log_sigma=float(f.log_sigma),
                    min_multiple=float(lo),
                    max_multiple=float(hi),
                )
            )
        else:
            families.append(f)
    return base.model_copy(
        update={
            "default_metric_id": "pb",
            "families": families,
            "min_history_obs_for_estimation": MIN_HIST_PB_POINTS,
        }
    )


def _exit_summary(bundle: ExitPriceBundle) -> dict[str, Any]:
    return {
        "version": bundle.version,
        "scenario_kind": bundle.scenario_kind,
        "metric_id": bundle.metric_id,
        "horizons_years": list(bundle.horizons_years),
        "n_input_paths": bundle.n_input_paths,
        "n_valid": bundle.n_valid,
        "n_failed": bundle.n_failed,
        "summaries": bundle.summaries,
        "flags": list(bundle.flags),
        "assumptions": list(bundle.assumptions),
        "notes": list(bundle.notes),
        "default_forbids_intrinsic_copy": bundle.default_forbids_intrinsic_copy,
        "dependence_on_fundamentals": bundle.dependence_on_fundamentals,
    }


def _returns_summary(bundle: ReturnDistributionBundleTrackB) -> dict[str, Any]:
    mixture = []
    for c in bundle.mixture:
        mixture.append(
            {
                "entry_price": c.entry_price,
                "relative_to_spot": c.relative_to_spot,
                "horizon_years": c.horizon_years,
                "n_valid": c.n_valid,
                "n_failed": c.n_failed,
                "stats": {
                    k: c.stats.get(k)
                    for k in ("n", "mean", "p05", "p50", "p95", "prob_loss", "prob_below_0")
                    if k in c.stats or True
                },
            }
        )
    return {
        "version": bundle.version,
        "spot_price": bundle.spot_price,
        "entry_prices": list(bundle.entry_prices),
        "relative_to_spot": list(bundle.relative_to_spot),
        "horizons_years": list(bundle.horizons_years),
        "n_input_exit_paths": bundle.n_input_exit_paths,
        "n_valid_cells_paths": bundle.n_valid_cells_paths,
        "mixture": mixture,
        "exit_ref": bundle.exit_ref,
        "flags": list(bundle.flags),
        "quality_flags": list(bundle.quality_flags),
        "assumptions": list(bundle.assumptions),
        "notes": list(bundle.notes),
        "content_fingerprint": bundle.content_fingerprint,
        "investment_value": bundle.investment_value,
    }


def run_rim_track_b(
    snap: PITSnapshot,
    *,
    bridge: RimBridgeResult,
    loaded: LoadedConfig,
    years: int | None = None,
    n_paths: int = 200,
    seed: int = 42,
    horizons_years: Sequence[int] = (1, 3),
    zeros_explicit: bool = True,
    oci_constant: float | None = None,
    min_hist_pb: int = MIN_HIST_PB_POINTS,
) -> RimTrackBResult:
    aids = cite(
        "RIM-EXIT-OWN-PB-HIST-v1",
        "RIM-COMMON-EQUITY-v1",
        "RIM-NI-P2-ROE-v1",
        "MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1",
        "EXIT-PRICE-TERMINAL-MULTIPLE-v1",
        "TRACK-B-EXIT-RETURN-v1",
        "HITHINK-NO-VENDOR-QFQ-v1",
    )
    flags: list[str] = [
        "TRACK_B_FI_RIM",
        "EXIT_MULTIPLE_OWN_HIST_COMMON_PB",
        "FORBID_DEFAULT_PB_CENTER_2",
        "NO_SILENT_INTRINSIC_EXIT",
        "NO_ENSEMBLE",
    ]
    hist = historical_common_pb(snap, zeros_explicit=zeros_explicit, min_points=min_hist_pb)
    hist_payload = {
        "ok": hist.ok,
        "ineligible_reason": hist.ineligible_reason,
        "n": hist.n,
        "median": hist.median,
        "p25": hist.p25,
        "p75": hist.p75,
        "flags": hist.flags,
        "assumption_ids": hist.assumption_ids,
        "detail": hist.detail,
        "points": [
            {
                "year": p.year,
                "pb": p.pb,
                "raw_close": p.raw_close,
                "bps": p.bps,
                "common_equity": p.common_equity,
            }
            for p in hist.points
        ],
    }
    flags.extend(hist.flags)

    if not hist.ok or hist.median is None:
        return RimTrackBResult(
            ok=False,
            status="UNAVAILABLE",
            ineligible_reason=hist.ineligible_reason or "INSUFFICIENT_OWN_PB_HISTORY",
            flags=sorted(set(flags + ["TRACK_B_EXIT_UNAVAILABLE"])),
            assumption_ids=aids,
            hist_pb=hist_payload,
            exit_prices=None,
            returns=None,
            spot_price=None,
            pb_center_used=None,
            n_book_paths=0,
            detail=hist.detail,
        )

    if not bridge.ok or bridge.common_equity_0 is None:
        return RimTrackBResult(
            ok=False,
            status="INELIGIBLE",
            ineligible_reason="BRIDGE_INELIGIBLE",
            flags=sorted(set(flags + ["BRIDGE_INELIGIBLE"])),
            assumption_ids=aids,
            hist_pb=hist_payload,
            exit_prices=None,
            returns=None,
            spot_price=None,
            pb_center_used=float(hist.median),
            n_book_paths=0,
            detail="rim bridge not ok for book paths",
        )

    shares = bridge.rim_inputs.get("diluted_shares")
    dps = bridge.last_fy_dps
    be_year = bridge.book_equity_year
    if shares is None or dps is None or be_year is None:
        return RimTrackBResult(
            ok=False,
            status="INELIGIBLE",
            ineligible_reason="MISSING_DPS_OR_SHARES_OR_YEAR",
            flags=sorted(set(flags + ["MISSING_BOOK_PATH_INPUTS"])),
            assumption_ids=aids,
            hist_pb=hist_payload,
            exit_prices=None,
            returns=None,
            spot_price=None,
            pb_center_used=float(hist.median),
            n_book_paths=0,
            detail="need diluted_shares, last_fy_dps, book_equity_year",
        )

    n_years = int(years if years is not None else loaded.config.projection.default_years)
    fin: FinancialPathBundle | None = build_rim_book_path_bundle(
        snap,
        book_equity_0=float(bridge.common_equity_0),
        book_equity_year=int(be_year),
        dps=float(dps),
        diluted_shares=float(shares),
        years=n_years,
        n_paths=int(n_paths),
        seed=int(seed),
        zeros_explicit=zeros_explicit,
        oci_constant=oci_constant,
    )
    if fin is None or fin.n_valid == 0:
        return RimTrackBResult(
            ok=False,
            status="INELIGIBLE",
            ineligible_reason="BOOK_PATHS_EMPTY",
            flags=sorted(set(flags + ["BOOK_PATHS_EMPTY"])),
            assumption_ids=aids,
            hist_pb=hist_payload,
            exit_prices=None,
            returns=None,
            spot_price=None,
            pb_center_used=float(hist.median),
            n_book_paths=0,
            detail="could not build RIM P2 book paths",
        )

    spot, sflags = subject_spot_raw_close(snap)
    flags.extend(sflags)
    if spot is None:
        return RimTrackBResult(
            ok=False,
            status="INELIGIBLE",
            ineligible_reason="MISSING_SPOT_RAW_CLOSE",
            flags=sorted(set(flags)),
            assumption_ids=aids,
            hist_pb=hist_payload,
            exit_prices=None,
            returns=None,
            spot_price=None,
            pb_center_used=float(hist.median),
            n_book_paths=fin.n_valid,
            detail="no raw_close at as_of",
        )

    mp_base = loaded.config.market_pricing or default_market_pricing_config()
    mp_cfg = _pb_family_from_hist(center=float(hist.median), base=mp_base)

    hist_vals = [p.pb for p in hist.points]
    market_post = estimate_market_pricing_state(
        current_multiple=float(hist.points[-1].pb) if hist.points else float(hist.median),
        historical_multiples=hist_vals,
        config=mp_cfg,
        use_fallback_when_unavailable=True,
    )

    exit_bundle = generate_exit_prices(
        fin,
        market_posterior=market_post,
        config=mp_cfg,
        horizons_years=list(horizons_years),
        metric_id="pb",
        seed=int(seed),
        scenario_kind="TERMINAL_MULTIPLE_DEFAULT",
    )
    # Guard: no path may silently use intrinsic
    if any(p.intrinsic_value_used for p in exit_bundle.paths if p.valid):
        flags.append("UNEXPECTED_INTRINSIC_USED")
    flags.extend(exit_bundle.flags)

    returns = build_return_distributions_from_exit_prices(
        exit_prices=exit_bundle,
        spot_price=float(spot),
        loaded=loaded,
        financial=fin,
        horizons_years=list(horizons_years),
    )
    flags.extend(returns.flags)
    flags.extend(returns.quality_flags)

    ok = exit_bundle.n_valid > 0 and returns.n_valid_cells_paths > 0
    return RimTrackBResult(
        ok=ok,
        status="VALID" if ok else "INELIGIBLE",
        ineligible_reason=None if ok else "EXIT_OR_RETURNS_EMPTY",
        flags=sorted(set(flags)),
        assumption_ids=aids,
        hist_pb=hist_payload,
        exit_prices=_exit_summary(exit_bundle),
        returns=_returns_summary(returns),
        spot_price=float(spot),
        pb_center_used=float(hist.median),
        n_book_paths=fin.n_valid,
        detail=(
            f"own_hist_pb_n={hist.n} median={hist.median}; "
            f"exit_valid={exit_bundle.n_valid}; returns_paths={returns.n_valid_cells_paths}"
        ),
    )
