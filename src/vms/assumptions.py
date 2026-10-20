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
    "CENTRAL-PATH-GATE-v1": "If the central path fails accounting invariants or is INSUFFICIENT_DATA: BLOCK in "
                            "production (non-zero exit). Exploratory may continue only with a recorded override reason. "
                            "Central failure is a critical modeling failure.",
    "PATH-LEDGER-PARQUET-v1": "Default artifact for path-level statement ledgers is Parquet "
                             "(financial_path_ledgers.parquet). JSON financial_path_bundle.json stays a lean summary.",
    "BUYBACK-PRICE-LAST-CLOSE-v1": "VMS-0.1 path buybacks/issuance continue to price at the last known close "
                                  "(BUYBACK-PRICE-v1). Simulated price paths belong to Phase 7 returns, not Phase 5/6.",
    "WACC-RF-CONFIG-v1": "Risk-free rate must be supplied explicitly in config (valuation.risk_free_rate) or via a "
                         "labeled PIT series. Never invent silently. Production will require a PIT 10y CGB adapter later "
                         "(WACC-INPUTS-v1).",
    "WACC-BETA-SHRINK-v1": "Beta: when a raw beta (or 2y weekly CSI300 beta series) is provided, "
                          "beta = (n_eff * beta_raw + k * beta_prior) / (n_eff + k) with beta_prior default 1. "
                          "Synthetic/offline runs may supply valuation.beta or valuation.cost_of_equity directly "
                          "with provenance labels.",
    "WACC-CONSTRUCTION-v1": "WACC = we*ke + wd*kd*(1-tc). ke = rf + beta*erp (or explicit cost_of_equity). "
                            "kd, tc, target wd/we from config (PIT snapshot debt/cash/market equity when used). "
                            "All inputs labeled assumption or snapshot.",
    "TV-GORDON-v1": "Terminal value TV = FCFF[n]*(1+g)/(WACC-g) with g = valuation.terminal_growth, bounded by "
                    "terminal_value.max_terminal_growth. Require WACC-g >= min_wacc_minus_g; else reject path "
                    "(WACC_G_MARGIN_FAIL). No silent denominator repair. Report PV(TV)/EV; warn above tv_fraction_warning.",
    "EXIT-MULTIPLE-SEPARATE-v1": "Exit-multiple cross-check (normalized EBIT or EBITDA x multiple) is reported "
                                "separately from DCF. Peer multiples from explicit config/synthetic peers with robust "
                                "location + shrink. Composite with DCF only if valuation.composite_weights is set "
                                "(versioned); default null = keep separate.",
    "EV-EQUITY-BRIDGE-v1": "EquityValue = EV + cash - interest_bearing_debt - lease_debt_like - minority_book "
                          "- other_senior_claims (LEASE-BRIDGE-DEBTLIKE-v1, MINORITY-BOOK-BRIDGE-v1). Components and "
                          "signs reported. Negative equity preserved (no silent clamp). "
                          "ValuePerShare = EquityValue / diluted_shares (must be > 0 and time-aligned to horizon).",
    "DIVIDEND-NO-REINVEST-v1": "VMS-0.1 total shareholder return uses cumulative cash dividends WITHOUT reinvestment: "
                               "R=(VPS_H + cum_DPS_H - P0)/P0 where cum_DPS_H = sum_{y=1..H} dividends[y]/diluted_shares[y]. "
                               "Buybacks/issuance affect share count / per-share value only (not added as cash); splits "
                               "already in the share path. No double-counting of dividends, splits, buybacks, or issuance.",
    "HORIZON-EQUITY-REMAINING-PV-v1": "At forecast horizon H (end of year H within N), EquityValue_H comes from "
                                     "EV_H = PV_H(remaining FCFF from H+1..N) + PV_H(Gordon TV at N), discounted to H at "
                                     "path WACC, then the Phase 6 EV-equity bridge with cash/debt/leases/minority/other "
                                     "and diluted_shares at H. At H=N, EV_N = TV_N. Same WACC-g margin reject as Phase 6.",
    "ANNUALIZED-GEO-ENDYEAR-v1": "Annualized geometric return = (1+R)^(1/H) - 1 where R is the H-year holding-period "
                                "total return and H is an integer year count (end-of-year convention). Undefined for R<=-1 "
                                "(flagged); reported separately from arithmetic mean of R.",
    "ENTRY-PRICE-GRID-v1": "Entry prices = spot_price * entry_price_grid.relative_to_spot (from config / ValuationRequest). "
                           "spot_price must be > 0 and finite. Grid shows how returns change across prices; no claim of a "
                           "universally optimal buy price.",
    "PRICE-REGIME-INVARIANT-v1": "Holding future-value paths fixed, lower entry price must mechanically improve pathwise "
                                "return. Changing the fundamental posterior / future-value distribution requires joint "
                                "recomputation. Never encode that lower price alone improves fundamental odds, or that "
                                "price decline proves fundamental deterioration.",
    "SENS-OAT-ISOLATION-v1": "One-at-a-time driver sensitivities shock only the named driver on frozen baseline paths; "
                            "isolation_check verifies other year-1 driver means are unchanged. Config/valuation OATs "
                            "change only the named valuation inputs.",
    "SENS-MC-PERCENTILE-NOT-CI-v1": "Monte Carlo p05/p95 (and similar) bands in sensitivity and valuation/return reports "
                                   "are empirical percentile intervals across simulated paths. They must NOT be labeled "
                                   "statistical confidence intervals unless a separate CI construction is documented.",
    "SENS-PROCESS-VS-PARAM-v1": "Process vs parameter uncertainty: compare runs with parameter_mode=fixed (point "
                               "estimates) vs parameter_mode=resampled (bootstrap), holding the process seed stream "
                               "convention fixed. Difference approximates parameter-uncertainty contribution.",
    "SENS-DRIVER-ABLATION-v1": "Driver contribution uses simple pathwise ablation to the central path year-1 value "
                              "(baseline metric minus ablated metric). Not a Shapley/game-theoretic allocation.",
    "EVAL-CHRONOLOGICAL-ONLY-v1": "Phase 9 walk-forward evaluation allows only chronological origins. Random "
                                 "row-level time-series train/test splits are prohibited (RandomSplitProhibitedError).",
    "EVAL-FORECAST-BEFORE-OUTCOME-v1": "At each origin, forecasts are persisted with outcomes=null before any "
                                      "realization is attached. Evaluation of a horizon occurs only after that horizon elapses.",
    "EVAL-TARGETS-SEPARATE-v1": "Operating cash-flow, intrinsic value, market-price, and TSR forecasts are scored in "
                               "separate metric blocks. Intrinsic value is never judged solely by matching future market prices.",
    "EVAL-INVESTMENT-LABEL-v1": "Every evaluation report carries ENGINEERING_PASS, DATA_QUALITY_PASS, CALIBRATION_PASS "
                               "(or INCONCLUSIVE), and investment_value. Synthetic / no predeclared leakage-safe OOS "
                               "evidence => INVESTMENT_VALUE_NOT_ESTABLISHED; never SUPPORTED on synthetic demos.",
    # ---- real A-share HiThink + Eastmoney NOTICE adapter (2026-10-20)
    "HITHINK-PIT-NOTICE-v1": "PIT published_at for HiThink statements = Eastmoney NOTICE_DATE joined by "
                            "(thscode/security_code, period_end ↔ EM REPORTDATE). Date-only NOTICE → "
                            "15:00:00 Asia/Shanghai that day (same clock as ASOF-DATE-CLOSE-v1). "
                            "Forbidden: using HiThink period_end_ms as published_at.",
    "HITHINK-REPORT-DATE-FALLBACK-v1": "Only if NOTICE is missing after local+EM fetch: use HiThink "
                                      "report_date_ms as published_at with quality_status=low_confidence and "
                                      "published_at_source=hithink_report_date_ms_fallback. Never claim exchange announce.",
    "HITHINK-LATEST-ONLY-v1": "HiThink fundamentals store has no restatement history (versioning=LATEST_ONLY). "
                             "SourceDescriptor source_id=hithink_em_notice ⇒ snapshots are PIT_INCOMPLETE / "
                             "pit_complete=false so Phase 9 unbiased metrics exclude them (PIT-INCOMPLETE-v1).",
    "HITHINK-UNITS-YUAN-v1": "HiThink statement amounts are treated as CNY yuan (元), unit_scale=unit. "
                            "Confirmed on CSI300 samples (e.g. 600519.SH annual revenue ~1e11). If a feed "
                            "were in 万元, convert ×10000 and label — not observed in the local store.",
    "HITHINK-NO-VENDOR-QFQ-v1": "MarketObservation.raw_close comes from marketdb raw_kline_daily (unadjusted). "
                               "Never put vendor forward-adjusted (qfq) closes into adjusted_close — qfq embeds "
                               "future splits. adjusted_close left null unless VMS-side adjust from known-at CAs.",
    "HITHINK-LOCAL-FIRST-v1": "Ingest is local-first: marketdb + hithink_fundamentals.duckdb + em_earnings_notices. "
                             "On miss for the requested ticker: Recipe E (one HiThink REST upsert + re-read). "
                             "Do not silently switch vendors. Never echo API keys.",
    "HITHINK-CA-DEFER-v1": "Corporate actions from marketdb raw_adjustment_events lack announced_at (ex_date only), "
                          "so they are not PIT-safe. Superseded by EM-CA-SHAREBONUS-v1 (Eastmoney announce dates).",
    "EM-CA-SHAREBONUS-v1": "A-share cash dividends and bonus/转增 events come from Eastmoney RPT_SHAREBONUS_DET. "
                          "announced_at = PLAN_NOTICE_DATE @ 15:00 Asia/Shanghai (else NOTICE_DATE); "
                          "ex_date = EX_DIVIDEND_DATE. PRETAX_BONUS_RMB and BONUS_IT_RATIO are per 10 shares "
                          "(÷10 → cash_per_share / share_ratio=1+ratio/10). Rows without announce date or "
                          "ex_date are skipped — never invent announced_at from ex_date. "
                          "Allotment/rights without EM announce stay deferred (HITHINK-ALLOTMENT-DEFER-v1).",
    "EM-SHARES-EQUITY-v1": "Shares outstanding from Eastmoney RPT_F10_EH_EQUITY TOTAL_SHARES, known-at = "
                          "NOTICE_DATE. Applied to MarketObservation.shares_outstanding on bars with "
                          "date >= NOTICE_DATE. Diluted shares are not published separately on this report "
                          "⇒ diluted = basic (DILUTED-SHARES-BASIC-v1). Local DuckDB cache em_equity_changes.",
    "INDUSTRY-SW-L1-PROXY-EM-v1": "No public Shenwan L1 membership feed found on EM datacenter / HiThink stock "
                                 "meta (2026-10-20 probe). Industry = EM F10 CompanySurvey sshy+sszjhhy mapped "
                                 "to SW2021_L1 proxy names (keyword+board table) so unsupported 银行/非银金融 "
                                 "still gate. scheme remains SW2021_L1. Not official SW membership.",
    "INDUSTRY-NO-RECLASS-HISTORY-v1": "EM F10 industry is a current snapshot only. published_at uses listing "
                                     "date when available (ssrq) so past as_of can see a class; historical "
                                     "reclassifications are not versioned — labeled limitation.",
    "HITHINK-ALLOTMENT-DEFER-v1": "HiThink/marketdb adjustment events expose allotment_ratio but only ex_date "
                                 "(no announced_at). Rights/allotment share_issuance stays out of VMS CA until "
                                 "an announce-date source is wired. Do not backfill announce from ex_date.",
    "HITHINK-FIELD-MAP-v1": "HiThink columns map to FIELDS-2 via vms.providers.hithink.mapping (documented in "
                           "docs/data_contracts.md). Outflows use positive magnitudes. Unmapped columns ignored "
                           "with optional warning count. pay_dividends_profits_interest_cash → dividends_paid "
                           "as low_confidence (mixed interest).",
}




SUPERSEDED: dict[str, str] = {
    "HITHINK-CA-DEFER-v1": "EM-CA-SHAREBONUS-v1",
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
