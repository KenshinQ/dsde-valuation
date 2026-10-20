"""Versioned assumption register.

Every modelling/scope assumption has a stable ID ``NAME-vN``. Artifacts cite the IDs they rely
on. docs/assumptions.md mirrors this table (a test keeps them in sync). Changing an assumption
means adding a new version, not editing the old one silently.
"""

from __future__ import annotations

ASSUMPTIONS: dict[str, str] = {
    # ---- scope / data (decided 2026-10-20)
    "ASOF-DATE-CLOSE-v1": "A date-only as_of means 15:00:00 Asia/Shanghai (A-share close) on that date.",
    "SCOPE-CNY-v1": "Scope is A-share main board, CNY only. Any non-CNY amount is CRITICAL (BLOCKED). No FX table.",
    "PIT-INCOMPLETE-v1": "PIT_INCOMPLETE does not block a single valuation. Phase 9 evaluation must exclude "
                         "PIT-incomplete snapshots (snapshot.pit_complete == false) from unbiased metrics.",
    "PRICE-REVISION-DEFER-v1": "Market rows carry no revision/publication field. A close is assumed known at its own "
                               "timestamp and vendor price corrections are not versioned (deferred).",
    "RIGHTS-ADJ-DEFER-v1": "Rights issues/placements are not price-adjusted. Only bonus shares/splits adjust prices. "
                           "Dilution from issuance is handled via share counts (Phase 2 deterministic, Phase 5 paths).",
    "STALENESS-CN-DEADLINE-v1": "CN statutory disclosure deadlines: annual and Q1 reports by Apr 30, H1 by Aug 31, "
                                "Q3 by Oct 31. A required period missing after its deadline => WARNING, not a block.",
    "SOURCE-CONFLICT-BLOCK-v1": "Conflicting values from different sources BLOCK. Configurable source priority is deferred.",
    "FISCAL-YEAR-CALENDAR-v1": "Only calendar fiscal years (12-31) are supported.",
    # ---- profiles
    "INDUSTRY-SW-L1-v1": "Industry classification scheme is assumed to be Shenwan 2021 level-1 names. Default "
                         "unsupported list: 银行, 非银金融 (FCFF/EV inappropriate). 房地产 and 公用事业 are supported "
                         "but flagged PROFILE_CAUTION (presales/contract liabilities; regulated returns).",
    "INDUSTRY-UNCLASSIFIED-v1": "If no PIT classification is known, the generic operating-company profile is used and "
                                "flagged INDUSTRY_UNCLASSIFIED (warning).",
    # ---- drivers
    "ANNUAL-BASE-v1": "Phase 2 projects annual fiscal years from the latest complete FY in the snapshot. Interim "
                      "data after that FY is not used for the projection base (stub periods deferred).",
    "DRIVER-CENTRAL-MEDIAN-v1": "Deterministic central driver value is the median of up to N most recent annual "
                                "observations (transform-invariant), clipped to profile bounds (flagged). With no "
                                "history the profile prior is used and flagged LOW_CONFIDENCE. Shrinkage is Phase 3.",
    "DRIVER-PRIORS-PLACEHOLDER-v1": "Profile priors and bounds are hand-set placeholders, not calibrated estimates.",
    "PAYOUT-SAME-YEAR-v1": "Dividends paid in year t are modelled as payout x parent net income of year t "
                           "(A-share practice pays prior-year dividends mid-year; timing simplified).",
    # ---- statements / FCFF
    "EBIT-MARGIN-PRIMARY-v1": "EBIT = revenue x ebit_margin (spec §9.1). Operating expenses are implied as "
                              "gross_profit - EBIT. opex_ratio is a diagnostic driver only.",
    "ONE-OFFS-v1": "If non_recurring_items_pretax is reported, historical EBIT margins use recurring EBIT "
                   "(EBIT - non_recurring_items_pretax). Otherwise reported EBIT is treated as recurring (flagged). "
                   "No one-offs are projected.",
    "TAX-CN-STATUTORY-25-v1": "Fallback effective tax rate is the CN statutory EIT rate of 25%. Preferential rates "
                              "(e.g. 15% high-tech) apply only via the historical effective-rate driver.",
    "TAX-CN-LCF-5Y-v1": "Tax losses carry forward 5 years (CN EIT general rule), used FIFO, no carry-back. "
                        "Separate pools are kept for book tax (pre-tax income) and operating tax (EBIT, for FCFF).",
    "TAX-LOSS-POOL-FROM-BOOK-v1": "The opening tax-loss pools are reconstructed from historical book pre-tax income/"
                                  "EBIT (book losses approximate tax losses).",
    "NEGATIVE-EBIT-v1": "Negative EBIT gives zero operating tax (no negative tax). The loss enters the operating "
                        "loss pool and NOPAT = EBIT.",
    "NWC-OPERATING-v1": "Operating NWC = accounts_receivable + inventory - accounts_payable. Contract assets/"
                        "liabilities and other working-capital items are held constant (not modelled). Year-1 "
                        "change is measured against actual base-year balances.",
    "ACQUISITIONS-SEPARATE-v1": "Acquisitions are a separate line from recurring capex, set by the capital-"
                                "allocation policy, and deducted in FCFF/FCFE. Revenue effects of acquisitions are not "
                                "modelled separately from the growth driver.",
    "LEASES-EXCLUDED-v1": "Leases are not modelled separately. Right-of-use depreciation/interest stay wherever the "
                          "reported EBIT/D&A put them. Lease liabilities are not in interest_bearing_debt. The Phase 6 "
                          "bridge must treat leases consistently with this.",
    "SBC-IN-EBIT-v1": "Share-based compensation is an expense inside reported EBIT (CAS 11) and is not added back. "
                      "SBC dilution is only captured by the diluted_share_growth driver.",
    "INTEREST-OPENING-DEBT-v1": "Interest expense = cost_of_debt x opening debt (avoids circularity). Interest "
                                "income on cash is not modelled.",
    "MINORITY-SHARE-v1": "Parent net income = net income x parent_share_of_net_income (driver). Minority dividends "
                         "are not modelled. total_equity includes minority interest.",
    "BALANCE-PLUG-FREE-v1": "Other assets = base other assets + capex + acquisitions - D&A. Other liabilities are "
                            "held at base level. The base-year identity residual (source definitions) is held constant. "
                            "No cash plug is used.",
    "REVOLVER-MIN-CASH-v1": "If cash after allocation would fall below min_cash_to_revenue x revenue, a revolver "
                            "draw (debt issuance) restores it. This is flagged and never silent.",
    "BUYBACK-PRICE-v1": "Deterministic repurchases/cash issuance execute at the last known close (adjusted for "
                        "known pending bonus/split ratios). Price paths are Phase 4/5.",
    "DILUTED-SHARES-BASIC-v1": "No dilutive-security data: diluted shares = basic shares outstanding after "
                               "projected dilution.",
    "PENDING-CA-v1": "Known (announced, not yet effective) share-changing corporate actions are applied to shares "
                     "in the projection year containing their ex_date.",
}


def cite(*ids: str) -> list[str]:
    missing = [i for i in ids if i not in ASSUMPTIONS]
    if missing:
        raise KeyError(f"unknown assumption ids {missing}")
    return sorted(set(ids))
