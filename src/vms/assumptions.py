"""Versioned assumption register.

Every modelling/scope assumption has a stable ID ``NAME-vN``. Artifacts cite the IDs they rely
on. docs/assumptions.md mirrors this table (a test keeps them in sync). Changing an assumption
means adding a new version, not editing the old one silently. Superseded versions stay in the
register (``SUPERSEDED`` maps old -> new) and can no longer be cited by new outputs.
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
    # ---- owner decisions after Phase 2 review (2026-10-20)
    "ANNUAL-BASE-STALENESS-v1": "VMS-0.1 keeps the last full FY as projection base (ANNUAL-BASE-v1). Interim results "
                                "published after that FY are not used, so the base can be up to ~15 months old. "
                                "Known limitation; a TTM/interim base is deferred.",
    "INDUSTRY-UNCLASSIFIED-v2": "No PIT industry classification at as_of => INDUSTRY_UNCLASSIFIED (CRITICAL): "
                                "BLOCKED in production. An exploratory run with a recorded override reason uses the "
                                "generic operating-company profile, flagged INDUSTRY_UNCLASSIFIED.",
    "DIVIDEND-T-PLUS-1-v1": "A-share convention: dividends declared on FY t results are paid in year t+1. The payout "
                            "driver is dividends_paid[t+1] / parent_net_income[t]. Projected year-t dividends paid = "
                            "dividends declared on FY t-1. Dividends declared on the final projected FY are unpaid at "
                            "the horizon (Phase 6 must treat them consistently).",
    "ANNOUNCED-DIVIDEND-BASE-v1": "Cash dividends announced by as_of with ex_date after the base FY end are unpaid at "
                                  "the base balance-sheet date. They are deducted from base cash and base equity (and "
                                  "total assets) and replace the policy's FY-base declaration. Amount = cash_per_share x "
                                  "shares before ex_date (last known market shares x known pending share ratios before "
                                  "ex_date). Phase 7: holders at as_of receive those with ex_date > as_of.",
    "INTEREST-OPENING-DEBT-v2": "Interest expense = cost_of_debt x opening term debt + (cost_of_debt + revolver_spread) "
                                "x opening revolver balance (opening balances avoid circularity). Interest income = "
                                "cash_interest_rate x max(opening cash, 0).",
    "REVOLVER-RATE-v1": "Revolver rate = cost_of_debt + configurable revolver_spread (default 0). Debt repayments "
                        "retire the revolver first.",
    "CASH-INTEREST-ZERO-v1": "Interest income on cash defaults to 0 (cash_interest_rate = 0). This is conservative "
                             "and labeled. Excess cash is valued in the Phase 6 bridge instead.",
    "BS-RESIDUAL-WARN-v1": "The base-year unexplained balance-sheet residual (assets - liabilities - equity under "
                           "source definitions) is held constant. If abs(residual) > bs_residual_warn_ratio (default 5%) "
                           "x total assets => WARNING BASE_BS_RESIDUAL_LARGE.",
    "LEASE-BRIDGE-DEBTLIKE-v1": "(Phase 6) Lease liabilities are debt-like in the EV-to-equity bridge. Since FCFF "
                                "(LEASES-EXCLUDED-v1) does not deduct lease principal, it must not be deducted twice.",
    "MINORITY-BOOK-BRIDGE-v1": "(Phase 6) Minority interest is deducted in the bridge at book value (labeled "
                               "approximation). Minority dividends are not modelled.",
    "WACC-INPUTS-DEFERRED-v1": "WACC / cost-of-equity inputs (risk-free rate, ERP, beta source) are deferred to "
                               "Phase 6 and require an owner decision. Phase 2 only defines the typed rates.",
    "WACC-INPUTS-v1": "Phase 6 WACC / cost of equity (owner decision 2026-10-20): risk-free = 10-year China "
                      "government bond yield known at as_of (PIT); equity risk premium default 6% (swept in "
                      "sensitivity); beta vs CSI 300, estimated on 2-year weekly returns, shrunk toward 1.",
    # ---- Phase 3: regimes and driver distributions
    "REGIME-PIT-FUNDAMENTALS-ONLY-v1": "Fundamental regimes are inferred from PIT financial records only (TTM revenue "
                                       "growth, TTM recurring EBIT margin and its yoy change). Never from prices, "
                                       "returns or any post-as_of information.",
    "REGIME-RULES-v1": "Rule-based soft classifier: logistic memberships for strong growth, contraction and margin "
                       "compression; RECOVERY = improvement after a weak (DETERIORATING/RECOVERY) prior period. "
                       "Thresholds are placeholders. Filter only (no smoothing with later periods).",
    "REGIME-TRANSITION-DIRICHLET-v1": "Annual-step transitions from soft-label expected counts of (p, p+1y) pairs "
                                      "(overlapping quarterly pairs weighted 1/4), with a per-row Dirichlet prior "
                                      "(stay/move pseudo-counts). Rows with little support are flagged prior-dominated.",
    "REGIME-HMM-DEFERRED-v1": "The optional hidden-state model is an interface only: a per-company HMM is "
                              "over-parameterised for ~4-20 observations; a pooled panel HMM needs Phase 9 data.",
    "MARKET-REGIME-UNAVAILABLE-v1": "No market-regime inputs exist in VMS-0.1. The market dimension is UNAVAILABLE "
                                    "and never inferred from the fundamental state.",
    "REGIME-ANNUAL-LABEL-v1": "An annual driver observation for FY y is weighted by the fundamental posterior at "
                              "y-12-31 (or the last period within FY y). No posterior => equal weights (flagged).",
    "DRIVER-TRANSFORMS-v1": "Estimation happens in transformed space: logit (scaled to bounds) for bounded margins/"
                            "ratios, log1p for growth and intensities, identity for zero-inflated policy ratios "
                            "(payout, buybacks, acquisitions) truncated at bounds. Logit observations at a bound are "
                            "clamped by boundary_eps (flagged BOUNDARY_OBS).",
    "DRIVER-DIST-v1": "Robust location = median, dispersion = 1.4826 x MAD (weighted versions per regime). Shrinkage: "
                      "loc = (n loc_hat + k prior)/(n + k); var = (n_d s_hat^2 + k s_prior^2)/(n_d + k), n_d = n - 1. "
                      "Regime parameters shrink to the pooled estimate with k_regime, and fall back to pooled below "
                      "min_regime_support. Fewer than min_history_years observations => SPARSE_HISTORY + "
                      "LOW_CONFIDENCE; none => PRIOR_FALLBACK.",
    "DRIVER-FAMILY-v1": "Process uncertainty uses a Student-t (df configurable) in transformed space, or the empirical "
                        "standardized residuals when n >= min_empirical_n (spec 'pooled_empirical'). No unconstrained "
                        "normal on bounded or skewed raw variables.",
    "PRIORS-GLOBAL-v1": "Profile priors (prior, prior_scale) act as the global prior. A dedicated sector profile "
                        "supplies sector priors through its own driver-profile file. All are placeholders.",
    "PARAM-UNCERTAINTY-BOOTSTRAP-v1": "Parameter uncertainty: nonparametric bootstrap of the full pooled estimator "
                                      "(resample observations, re-shrink), seeded per driver stream. Draws are persisted "
                                      "for Phase 4. Walk-forward predictive scales add the analytic se = s/sqrt(n+k).",
    "WALK-FORWARD-ORIGINS-v1": "Rolling-origin evaluation: at each FY origin the snapshot is rebuilt as known at the "
                               "first publication of that FY (past-only data, including versions). Specs are fitted "
                               "there and score the next FY value as known at the run as_of.",
    "MODEL-SELECTION-WF-v1": "Driver-distribution specs are selected per driver by mean walk-forward pinball loss "
                             "(transformed space). Fewer than min_origins scored origins => the configured default spec "
                             "(flagged). In-sample fit is reported but never used for selection.",
    "MODEL-SELECTION-WF-v2": "Driver-distribution specs selected by mean walk-forward pinball (transformed space). "
                             "Candidates: prior_only, pooled_t, pooled_empirical, regime_t, persistence_t "
                             "(last observation + shrunk dispersion). Point benchmark naive_last is scored but not "
                             "selectable. Fewer than min_origins scored origins => default spec + "
                             "SELECTION_DEFAULT_INSUFFICIENT_ORIGINS + LOW_EVAL_SUPPORT (diagnostics marked "
                             "low-confidence; no silent calibration claim). Selected-spec central-interval coverage "
                             "outside nominal +/- coverage_tolerance => COVERAGE_MISCALIBRATED warning.",
    "DRIVER-DEPENDENCE-PHASE4-v1": "Phase 3 estimates marginal (regime-conditional) distributions only. Dependence "
                                   "between drivers is modelled by the Phase 4 sampler (regime-conditional block "
                                   "bootstrap / shrunk correlations).",
    "DRIVER-DEPENDENCE-v1": "Phase 4: drivers are drawn jointly via a Gaussian copula over shrunk residual "
                            "correlations in transformed space (identity target). Material blocks "
                            "(DEMAND_PROFIT, WORKING_CAPITAL, REINVESTMENT, CAPITAL) are never sampled independently. "
                            "Within-regime residual correlations are used when a state has enough overlapping years; "
                            "otherwise the pooled shrunk matrix. Small n => heavy shrink (flagged).",
    "REGIME-CLOCK-MISMATCH-v1": "VMS-0.1 keeps quarterly/TTM fundamental regimes with annual driver observations "
                                "(REGIME-ANNUAL-LABEL-v1). Known clock mismatch; annual-only regimes are deferred.",
    "INDUSTRY-PRIORS-DEFER-v1": "Sector/industry priors need a cross-sectional panel and are out of VMS-0.1 scope. "
                               "Keep global profile priors + shrinkage (PRIORS-GLOBAL-v1).",
    "CENTRAL-FROM-SELECTED-v1": "Phase 4 central scenario uses the walk-forward-selected, shrunk distribution "
                               "(median / q=0.5 in transformed space, inverse-transformed and clipped). Phase 2 "
                               "deterministic projection still uses DRIVER-CENTRAL-MEDIAN-v1.",
    "PATH-SAMPLER-v1": "Per path: (1) sample a shared bootstrap index then parameters from persisted draws (PARAM-BOOTSTRAP-COUPLED-v1); "
                       "(2) sample initial fundamental state from current posterior; (3) simulate annual transitions "
                       "from a Dirichlet draw of the transition posterior; (4) sample correlated driver shocks "
                       "conditional on state and, for persistence_t, the lagged z; (5) enforce documented bounds/"
                       "accounting constraints; (6) reject invalid paths with reason codes. Process and parameter "
                       "uncertainty stay separate (SPEC section 8.1).",
    "PATH-CONSTRAINTS-v1": "Driver bounds from the profile. Soft repairs: clip to [lower, upper]; if ebit_margin > "
                           "gross_margin set ebit_margin = gross_margin (flagged MARGIN_ORDER_REPAIRED). Hard rejects: "
                           "non-finite draws, growth <= -1 after inverse, empty parameter draws "
                           "(BOUND_VIOLATION, GROWTH_UNDEFINED, PARAMETER_DRAW_EMPTY, DEPENDENCE_DRAW_FAILED).",
    "PARAM-BOOTSTRAP-COUPLED-v1": "Within each Monte Carlo path, a single bootstrap draw index is shared across all "
                                 "drivers that have nonparametric bootstrap draws (coupled parameter uncertainty). "
                                 "Drivers without draws keep their point estimate (flagged PARAM_POINT_ESTIMATE).",
    "DEP-BLOCK-BOOTSTRAP-DEFER-v1": "Regime-conditional residual block bootstrap is a documented alternative when "
                                   "overlapping history is long enough. VMS-0.1 keeps Gaussian-copula + shrink "
                                   "(DRIVER-DEPENDENCE-v1) as the default; do not switch.",
    "INVALID-PATH-FRACTION-GATE-v1": "If invalid sampling-path fraction exceeds monte_carlo.max_invalid_path_fraction: "
                                    "BLOCK in production (CLI exit 5). Exploratory may continue only with a recorded "
                                    "override reason (same pattern as quality gates).",
    "COVERAGE-MISCAL-NO-AUTOSWITCH-v1": "COVERAGE_MISCALIBRATED is a warning only. Model selection stays walk-forward "
                                       "pinball (MODEL-SELECTION-WF-v2); never silently prefer persistence_t.",
    "PATH-STATEMENTS-v1": "Phase 5: each SimulationBundle path (and the central path) is projected with the Phase 2 "
                          "operating-company mechanics, using that path's year-t drivers and the same capital-allocation "
                          "policy. Per-year policy driver lookups (payout, debt_to_revenue, ...) use the path year.",
    "FAILED-PATHS-EXCLUDED-v1": "Paths that fail accounting invariants or are INSUFFICIENT_DATA are recorded with "
                               "reason codes and excluded from FinancialPathBundle aggregates and any later valuation "
                               "summary. They never enter silently.",
}



SUPERSEDED: dict[str, str] = {
    "PAYOUT-SAME-YEAR-v1": "DIVIDEND-T-PLUS-1-v1",
    "INDUSTRY-UNCLASSIFIED-v1": "INDUSTRY-UNCLASSIFIED-v2",
    "INTEREST-OPENING-DEBT-v1": "INTEREST-OPENING-DEBT-v2",
    "WACC-INPUTS-DEFERRED-v1": "WACC-INPUTS-v1",
    "MODEL-SELECTION-WF-v1": "MODEL-SELECTION-WF-v2",
    "DRIVER-DEPENDENCE-PHASE4-v1": "DRIVER-DEPENDENCE-v1",
}


def cite(*ids: str) -> list[str]:
    missing = [i for i in ids if i not in ASSUMPTIONS]
    if missing:
        raise KeyError(f"unknown assumption ids {missing}")
    old = [i for i in ids if i in SUPERSEDED]
    if old:
        raise KeyError(f"superseded assumption ids {old}; cite {[SUPERSEDED[i] for i in old]}")
    return sorted(set(ids))
