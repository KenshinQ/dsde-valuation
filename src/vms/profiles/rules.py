"""Versioned interpretable profile rules (SPEC §7.3).

Rules use only features available at ``as_of``. They never use future returns or
post-as_of labels. Industry keywords reinforce financial evidence; they never
alone assign a hard class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from vms.profiles.features import ProfileFeatureBundle
from vms.schemas.contracts import ProfileFlag, ProfileLabel

def _classifier_config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "classifier"


def _load_industry_aux() -> dict[str, tuple[str, ...]]:
    """Load auxiliary industry keywords from config (not hardcoded in logic paths)."""
    import yaml
    path = _classifier_config_dir() / "industry_aux_keywords.yaml"
    if not path.is_file():
        return {"financial_institution": (), "cyclical_operating": ()}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "financial_institution": tuple(data.get("financial_institution") or ()),
        "cyclical_operating": tuple(data.get("cyclical_operating") or ()),
    }


_INDUSTRY_AUX = _load_industry_aux()

RULES_VERSION = "vms-profile-rules-0.2.phase2"


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    profile: ProfileLabel | None
    flag: ProfileFlag | None
    weight: float
    detail: str
    feature_refs: tuple[str, ...]


Predicate = Callable[[ProfileFeatureBundle], RuleHit | None]


def _fin_interest(f: ProfileFeatureBundle) -> RuleHit | None:
    v = f.interest_income_to_revenue
    if v is not None and v >= 0.35:
        return RuleHit("R_FIN_INTEREST_INCOME", ProfileLabel.FINANCIAL_INSTITUTION, None, 3.0,
                       f"interest_income_to_revenue={v:.4f}>=0.35", ("interest_income_to_revenue",))
    return None


def _fin_assets(f: ProfileFeatureBundle) -> RuleHit | None:
    v = f.financial_assets_to_assets
    if v is not None and v >= 0.45:
        return RuleHit("R_FIN_FINANCIAL_ASSETS", ProfileLabel.FINANCIAL_INSTITUTION, None, 2.5,
                       f"financial_assets_to_assets={v:.4f}>=0.45", ("financial_assets_to_assets",))
    return None


def _fin_industry_aux(f: ProfileFeatureBundle) -> RuleHit | None:
    """Auxiliary only: configured financial industry keywords add weak evidence."""
    name = (f.industry_name or "").lower()
    keys = _INDUSTRY_AUX.get("financial_institution", ())
    if keys and any(k.lower() in name for k in keys):
        # Weak: alone cannot hard-class (weight 0.8; needs financial evidence for confidence)
        return RuleHit("R_FIN_INDUSTRY_AUX", ProfileLabel.FINANCIAL_INSTITUTION, None, 0.8,
                       f"industry_name={f.industry_name!r} matches financial keywords (aux only)",
                       ("industry_name",))
    return None


def _hold_invest(f: ProfileFeatureBundle) -> RuleHit | None:
    v = f.investment_assets_to_assets
    if v is not None and v >= 0.30:
        return RuleHit("R_HOLD_INVESTMENT_ASSETS", ProfileLabel.HOLDING_OR_CONGLOMERATE, None, 2.5,
                       f"investment_assets_to_assets={v:.4f}>=0.30", ("investment_assets_to_assets",))
    return None


def _hold_equity_method(f: ProfileFeatureBundle) -> RuleHit | None:
    v = f.equity_method_income_to_pretax
    if v is not None and abs(v) >= 0.25:
        return RuleHit("R_HOLD_EQUITY_METHOD", ProfileLabel.HOLDING_OR_CONGLOMERATE, None, 2.0,
                       f"equity_method_income_to_pretax={v:.4f}; |v|>=0.25",
                       ("equity_method_income_to_pretax",))
    return None


def _hold_segments(f: ProfileFeatureBundle) -> RuleHit | None:
    n = f.n_segments
    if n is not None and n >= 3:
        return RuleHit("R_HOLD_SEGMENTS", ProfileLabel.HOLDING_OR_CONGLOMERATE, None, 1.5,
                       f"n_segments={n}>=3", ("n_segments",))
    if f.has_listed_subsidiaries is True:
        return RuleHit("R_HOLD_LISTED_SUBS", ProfileLabel.HOLDING_OR_CONGLOMERATE, None, 1.5,
                       "has_listed_subsidiaries=true", ("has_listed_subsidiaries",))
    return None


def _distress_neg_equity(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.book_equity is not None and f.book_equity < 0:
        return RuleHit("R_DISTRESS_NEG_EQUITY", ProfileLabel.DISTRESSED_OR_TURNAROUND, None, 3.5,
                       f"book_equity={f.book_equity:.4f}<0", ("book_equity",))
    return None


def _distress_loss_leverage(f: ProfileFeatureBundle) -> RuleHit | None:
    ni = f.net_income_to_revenue
    d = f.debt_to_assets
    if ni is not None and d is not None and ni < 0 and d >= 0.65:
        return RuleHit("R_DISTRESS_LOSS_LEVERAGE", ProfileLabel.DISTRESSED_OR_TURNAROUND, None, 2.5,
                       f"net_income_to_revenue={ni:.4f}<0 and debt_to_assets={d:.4f}>=0.65",
                       ("net_income_to_revenue", "debt_to_assets"))
    return None


def _growth_neg_fcf(f: ProfileFeatureBundle) -> RuleHit | None:
    g, fcf = f.revenue_cagr_3y, f.fcf_to_revenue
    if g is not None and fcf is not None and g >= 0.12 and fcf < 0:
        return RuleHit("R_GROWTH_NEG_FCF", ProfileLabel.GROWTH_OR_REINVESTMENT_HEAVY, None, 3.0,
                       f"revenue_cagr_3y={g:.4f}>=0.12 and fcf_to_revenue={fcf:.4f}<0",
                       ("revenue_cagr_3y", "fcf_to_revenue"))
    return None


def _growth_high_reinvest(f: ProfileFeatureBundle) -> RuleHit | None:
    g = f.revenue_cagr_3y
    if g is not None and g >= 0.20 and (f.fcf_to_revenue is None or f.fcf_to_revenue < 0.02):
        return RuleHit("R_GROWTH_HIGH_CAGR", ProfileLabel.GROWTH_OR_REINVESTMENT_HEAVY, None, 1.5,
                       f"revenue_cagr_3y={g:.4f}>=0.20 with weak/unknown FCF",
                       ("revenue_cagr_3y", "fcf_to_revenue"))
    return None


def _cyclical_vol(f: ProfileFeatureBundle) -> RuleHit | None:
    v = f.ebit_margin_stdev_3y
    if v is not None and v >= 0.06:
        w = 3.5 if v >= 0.10 else 2.5
        return RuleHit("R_CYCLICAL_MARGIN_VOL", ProfileLabel.CYCLICAL_OPERATING, None, w,
                       f"ebit_margin_stdev_3y={v:.4f}>=0.06", ("ebit_margin_stdev_3y",))
    return None


def _cyclical_industry_aux(f: ProfileFeatureBundle) -> RuleHit | None:
    name = (f.industry_name or "").lower()
    keys = _INDUSTRY_AUX.get("cyclical_operating", ())
    if keys and any(k.lower() in name for k in keys):
        return RuleHit("R_CYCLICAL_INDUSTRY_AUX", ProfileLabel.CYCLICAL_OPERATING, None, 0.8,
                       f"industry_name={f.industry_name!r} cyclical keywords (aux only)",
                       ("industry_name",))
    return None


def _asset_ppe(f: ProfileFeatureBundle) -> RuleHit | None:
    v = f.ppe_to_assets
    if v is not None and v >= 0.40:
        return RuleHit("R_ASSET_PPE", ProfileLabel.ASSET_HEAVY_OR_RESOURCE, None, 2.5,
                       f"ppe_to_assets={v:.4f}>=0.40", ("ppe_to_assets",))
    return None


def _mature_pos_fcf(f: ProfileFeatureBundle) -> RuleHit | None:
    g, fcf, m = f.revenue_cagr_3y, f.fcf_to_revenue, f.ebit_margin
    if g is None or fcf is None or m is None:
        return None
    # High margin volatility is cyclical evidence — do not hard-class as mature.
    vol = f.ebit_margin_stdev_3y
    if vol is not None and vol >= 0.06:
        return None
    if fcf >= 0.02 and abs(g) <= 0.12 and m >= 0.04:
        return RuleHit("R_MATURE_POS_FCF_STABLE", ProfileLabel.MATURE_OPERATING, None, 3.0,
                       f"fcf_to_revenue={fcf:.4f}>=0.02, |cagr|={abs(g):.4f}<=0.12, ebit_margin={m:.4f}>=0.04",
                       ("fcf_to_revenue", "revenue_cagr_3y", "ebit_margin"))
    return None


def _mature_moderate(f: ProfileFeatureBundle) -> RuleHit | None:
    g, fcf, m = f.revenue_cagr_3y, f.fcf_to_revenue, f.ebit_margin
    if g is None or fcf is None or m is None:
        return None
    vol = f.ebit_margin_stdev_3y
    if vol is not None and vol >= 0.06:
        return None
    if fcf >= 0.0 and abs(g) <= 0.15 and m >= 0.02:
        return RuleHit("R_MATURE_MODERATE", ProfileLabel.MATURE_OPERATING, None, 1.2,
                       f"moderate mature signals fcf={fcf:.4f} cagr={g:.4f} margin={m:.4f}",
                       ("fcf_to_revenue", "revenue_cagr_3y", "ebit_margin"))
    return None


# --- Independent flags ---

def _flag_neg_fcf(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.fcf_to_revenue is not None and f.fcf_to_revenue < 0:
        return RuleHit("F_CURRENT_FCF_NEGATIVE", None, ProfileFlag.CURRENT_FCF_NEGATIVE, 1.0,
                       f"fcf_to_revenue={f.fcf_to_revenue:.4f}<0", ("fcf_to_revenue",))
    return None


def _flag_earn_neg(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.net_income_to_revenue is not None and f.net_income_to_revenue < 0:
        return RuleHit("F_EARNINGS_NEGATIVE", None, ProfileFlag.EARNINGS_NEGATIVE_OR_UNSTABLE, 1.0,
                       f"net_income_to_revenue={f.net_income_to_revenue:.4f}<0", ("net_income_to_revenue",))
    if f.ebit_margin_stdev_3y is not None and f.ebit_margin_stdev_3y >= 0.08:
        return RuleHit("F_EARNINGS_UNSTABLE", None, ProfileFlag.EARNINGS_NEGATIVE_OR_UNSTABLE, 1.0,
                       f"ebit_margin_stdev_3y={f.ebit_margin_stdev_3y:.4f}>=0.08", ("ebit_margin_stdev_3y",))
    return None


def _flag_div(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.dividend_payout is not None and f.dividend_payout > 0.05:
        return RuleHit("F_DIVIDEND_PAYING", None, ProfileFlag.DIVIDEND_PAYING, 1.0,
                       f"dividend_payout={f.dividend_payout:.4f}>0.05", ("dividend_payout",))
    return None


def _flag_cash(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.net_cash_to_assets is not None and f.net_cash_to_assets >= 0.15:
        return RuleHit("F_HIGH_CASH", None, ProfileFlag.HIGH_CASH_OR_NET_CASH, 1.0,
                       f"net_cash_to_assets={f.net_cash_to_assets:.4f}>=0.15", ("net_cash_to_assets",))
    if f.cash_to_assets is not None and f.cash_to_assets >= 0.25 and (f.debt_to_assets or 0) < 0.15:
        return RuleHit("F_HIGH_CASH_GROSS", None, ProfileFlag.HIGH_CASH_OR_NET_CASH, 1.0,
                       f"cash_to_assets={f.cash_to_assets:.4f} with low debt",
                       ("cash_to_assets", "debt_to_assets"))
    return None


def _flag_lev(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.debt_to_assets is not None and f.debt_to_assets >= 0.55:
        return RuleHit("F_HIGH_LEVERAGE", None, ProfileFlag.HIGH_LEVERAGE, 1.0,
                       f"debt_to_assets={f.debt_to_assets:.4f}>=0.55", ("debt_to_assets",))
    return None


def _flag_cyclical(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.ebit_margin_stdev_3y is not None and f.ebit_margin_stdev_3y >= 0.06:
        return RuleHit("F_HIGH_CYCLICALITY", None, ProfileFlag.HIGH_CYCLICALITY, 1.0,
                       f"ebit_margin_stdev_3y={f.ebit_margin_stdev_3y:.4f}>=0.06",
                       ("ebit_margin_stdev_3y",))
    return None


def _flag_short_hist(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.history_years is not None and f.history_years < 3:
        return RuleHit("F_SHORT_HISTORY", None, ProfileFlag.SHORT_PUBLIC_HISTORY, 1.0,
                       f"history_years={f.history_years}<3", ("history_years",))
    return None


def _flag_segments(f: ProfileFeatureBundle) -> RuleHit | None:
    if (f.n_segments is not None and f.n_segments >= 3) or f.has_listed_subsidiaries is True:
        return RuleHit("F_SEGMENT_COMPLEXITY", None, ProfileFlag.MATERIAL_SEGMENT_COMPLEXITY, 1.0,
                       f"n_segments={f.n_segments} listed_subs={f.has_listed_subsidiaries}",
                       ("n_segments", "has_listed_subsidiaries"))
    return None


def _flag_nonop(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.investment_assets_to_assets is not None and f.investment_assets_to_assets >= 0.20:
        return RuleHit("F_NONOP_ASSETS", None, ProfileFlag.MATERIAL_NONOPERATING_ASSETS, 1.0,
                       f"investment_assets_to_assets={f.investment_assets_to_assets:.4f}>=0.20",
                       ("investment_assets_to_assets",))
    return None


def _flag_low_dq(f: ProfileFeatureBundle) -> RuleHit | None:
    if f.low_data_quality:
        return RuleHit("F_LOW_DATA_QUALITY", None, ProfileFlag.LOW_DATA_QUALITY, 1.0,
                       "low_data_quality=true", ("low_data_quality",))
    return None


PROFILE_RULES: tuple[Predicate, ...] = (
    _fin_interest, _fin_assets, _fin_industry_aux,
    _hold_invest, _hold_equity_method, _hold_segments,
    _distress_neg_equity, _distress_loss_leverage,
    _growth_neg_fcf, _growth_high_reinvest,
    _cyclical_vol, _cyclical_industry_aux,
    _asset_ppe,
    _mature_pos_fcf, _mature_moderate,
)

FLAG_RULES: tuple[Predicate, ...] = (
    _flag_neg_fcf, _flag_earn_neg, _flag_div, _flag_cash, _flag_lev,
    _flag_cyclical, _flag_short_hist, _flag_segments, _flag_nonop, _flag_low_dq,
)


def evaluate_rules(features: ProfileFeatureBundle) -> tuple[list[RuleHit], list[RuleHit]]:
    profile_hits = [h for rule in PROFILE_RULES if (h := rule(features)) is not None]
    flag_hits = [h for rule in FLAG_RULES if (h := rule(features)) is not None]
    return profile_hits, flag_hits
