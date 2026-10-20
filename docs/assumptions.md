# Versioned assumption register (VMS-0.1)

Source of truth: `src/vms/assumptions.py` (`ASSUMPTIONS`, `SUPERSEDED`). `tests/unit/test_docs_sync.py` keeps this
table in sync; regenerate with `python scripts/gen_assumptions_doc.py`. Artifacts cite the IDs they rely on
(e.g. `statement_projection.json → assumptions`). **Changing an assumption means adding `-v2`, never silently
editing `-v1`.** Superseded IDs stay listed and can no longer be cited (`cite()` raises).

Owner decisions: scope/data items (ASOF, SCOPE-CNY, PIT-INCOMPLETE, PRICE-REVISION-DEFER, RIGHTS-ADJ-DEFER,
STALENESS, SOURCE-CONFLICT) after Phase 1 review; ANNUAL-BASE-STALENESS, INDUSTRY-UNCLASSIFIED-v2,
DIVIDEND-T-PLUS-1, ANNOUNCED-DIVIDEND-BASE, INTEREST-OPENING-DEBT-v2, REVOLVER-RATE, CASH-INTEREST-ZERO,
BS-RESIDUAL-WARN, LEASE-BRIDGE-DEBTLIKE, MINORITY-BOOK-BRIDGE, WACC-INPUTS-DEFERRED after Phase 2 review (2026-10-20).

## Notes for later phases
- **Phase 4:** sample parameters from the persisted parameter-uncertainty draws and the Dirichlet transition
  posterior; do not collapse the uncertainty types (SPEC §8.1).
- **Phase 5:** dilution from rights issues/placements enters through share-count paths (RIGHTS-ADJ-DEFER-v1).
- **Phase 6:** leases are debt-like in the bridge and FCFF must not also deduct lease principal (LEASE-BRIDGE-DEBTLIKE-v1).
  Minority interest at book (MINORITY-BOOK-BRIDGE-v1). Dividends declared on the final FY are unpaid at the horizon
  (DIVIDEND-T-PLUS-1-v1). WACC inputs need an owner decision (WACC-INPUTS-DEFERRED-v1).
- **Phase 7:** holders at as_of receive announced dividends with ex_date > as_of (ANNOUNCED-DIVIDEND-BASE-v1).
- **Phase 9:** exclude snapshots with `pit_complete == false` from unbiased evaluation metrics (PIT-INCOMPLETE-v1).

| ID | Status | Assumption |
|---|---|---|
| `ASOF-DATE-CLOSE-v1` | active | A date-only as_of means 15:00:00 Asia/Shanghai (A-share close) on that date. |
| `SCOPE-CNY-v1` | active | Scope is A-share main board, CNY only. Any non-CNY amount is CRITICAL (BLOCKED). No FX table. |
| `PIT-INCOMPLETE-v1` | active | PIT_INCOMPLETE does not block a single valuation. Phase 9 evaluation must exclude PIT-incomplete snapshots (snapshot.pit_complete == false) from unbiased metrics. |
| `PRICE-REVISION-DEFER-v1` | active | Market rows carry no revision/publication field. A close is assumed known at its own timestamp and vendor price corrections are not versioned (deferred). |
| `RIGHTS-ADJ-DEFER-v1` | active | Rights issues/placements are not price-adjusted. Only bonus shares/splits adjust prices. Dilution from issuance is handled via share counts (Phase 2 deterministic, Phase 5 paths). |
| `STALENESS-CN-DEADLINE-v1` | active | CN statutory disclosure deadlines: annual and Q1 reports by Apr 30, H1 by Aug 31, Q3 by Oct 31. A required period missing after its deadline => WARNING, not a block. |
| `SOURCE-CONFLICT-BLOCK-v1` | active | Conflicting values from different sources BLOCK. Configurable source priority is deferred. |
| `FISCAL-YEAR-CALENDAR-v1` | active | Only calendar fiscal years (12-31) are supported. |
| `INDUSTRY-SW-L1-v1` | active | Industry classification scheme is assumed to be Shenwan 2021 level-1 names. Default unsupported list: 银行, 非银金融 (FCFF/EV inappropriate). 房地产 and 公用事业 are supported but flagged PROFILE_CAUTION (presales/contract liabilities; regulated returns). |
| `INDUSTRY-UNCLASSIFIED-v1` | superseded by `INDUSTRY-UNCLASSIFIED-v2` | If no PIT classification is known, the generic operating-company profile is used and flagged INDUSTRY_UNCLASSIFIED (warning). |
| `ANNUAL-BASE-v1` | active | Phase 2 projects annual fiscal years from the latest complete FY in the snapshot. Interim data after that FY is not used for the projection base (stub periods deferred). |
| `DRIVER-CENTRAL-MEDIAN-v1` | active | Deterministic central driver value is the median of up to N most recent annual observations (transform-invariant), clipped to profile bounds (flagged). With no history the profile prior is used and flagged LOW_CONFIDENCE. Shrinkage is Phase 3. |
| `DRIVER-PRIORS-PLACEHOLDER-v1` | active | Profile priors and bounds are hand-set placeholders, not calibrated estimates. |
| `PAYOUT-SAME-YEAR-v1` | superseded by `DIVIDEND-T-PLUS-1-v1` | Dividends paid in year t are modelled as payout x parent net income of year t (A-share practice pays prior-year dividends mid-year; timing simplified). |
| `EBIT-MARGIN-PRIMARY-v1` | active | EBIT = revenue x ebit_margin (spec §9.1). Operating expenses are implied as gross_profit - EBIT. opex_ratio is a diagnostic driver only. |
| `ONE-OFFS-v1` | active | If non_recurring_items_pretax is reported, historical EBIT margins use recurring EBIT (EBIT - non_recurring_items_pretax). Otherwise reported EBIT is treated as recurring (flagged). No one-offs are projected. |
| `TAX-CN-STATUTORY-25-v1` | active | Fallback effective tax rate is the CN statutory EIT rate of 25%. Preferential rates (e.g. 15% high-tech) apply only via the historical effective-rate driver. |
| `TAX-CN-LCF-5Y-v1` | active | Tax losses carry forward 5 years (CN EIT general rule), used FIFO, no carry-back. Separate pools are kept for book tax (pre-tax income) and operating tax (EBIT, for FCFF). |
| `TAX-LOSS-POOL-FROM-BOOK-v1` | active | The opening tax-loss pools are reconstructed from historical book pre-tax income/EBIT (book losses approximate tax losses). |
| `NEGATIVE-EBIT-v1` | active | Negative EBIT gives zero operating tax (no negative tax). The loss enters the operating loss pool and NOPAT = EBIT. |
| `NWC-OPERATING-v1` | active | Operating NWC = accounts_receivable + inventory - accounts_payable. Contract assets/liabilities and other working-capital items are held constant (not modelled). Year-1 change is measured against actual base-year balances. |
| `ACQUISITIONS-SEPARATE-v1` | active | Acquisitions are a separate line from recurring capex, set by the capital-allocation policy, and deducted in FCFF/FCFE. Revenue effects of acquisitions are not modelled separately from the growth driver. |
| `LEASES-EXCLUDED-v1` | active | Leases are not modelled separately. Right-of-use depreciation/interest stay wherever the reported EBIT/D&A put them. Lease liabilities are not in interest_bearing_debt. The Phase 6 bridge must treat leases consistently with this. |
| `SBC-IN-EBIT-v1` | active | Share-based compensation is an expense inside reported EBIT (CAS 11) and is not added back. SBC dilution is only captured by the diluted_share_growth driver. |
| `INTEREST-OPENING-DEBT-v1` | superseded by `INTEREST-OPENING-DEBT-v2` | Interest expense = cost_of_debt x opening debt (avoids circularity). Interest income on cash is not modelled. |
| `MINORITY-SHARE-v1` | active | Parent net income = net income x parent_share_of_net_income (driver). Minority dividends are not modelled. total_equity includes minority interest. |
| `BALANCE-PLUG-FREE-v1` | active | Other assets = base other assets + capex + acquisitions - D&A. Other liabilities are held at base level. The base-year identity residual (source definitions) is held constant. No cash plug is used. |
| `REVOLVER-MIN-CASH-v1` | active | If cash after allocation would fall below min_cash_to_revenue x revenue, a revolver draw (debt issuance) restores it. This is flagged and never silent. |
| `BUYBACK-PRICE-v1` | active | Deterministic repurchases/cash issuance execute at the last known close (adjusted for known pending bonus/split ratios). Price paths are Phase 4/5. |
| `DILUTED-SHARES-BASIC-v1` | active | No dilutive-security data: diluted shares = basic shares outstanding after projected dilution. |
| `PENDING-CA-v1` | active | Known (announced, not yet effective) share-changing corporate actions are applied to shares in the projection year containing their ex_date. |
| `ANNUAL-BASE-STALENESS-v1` | active | VMS-0.1 keeps the last full FY as projection base (ANNUAL-BASE-v1). Interim results published after that FY are not used, so the base can be up to ~15 months old. Known limitation; a TTM/interim base is deferred. |
| `INDUSTRY-UNCLASSIFIED-v2` | active | No PIT industry classification at as_of => INDUSTRY_UNCLASSIFIED (CRITICAL): BLOCKED in production. An exploratory run with a recorded override reason uses the generic operating-company profile, flagged INDUSTRY_UNCLASSIFIED. |
| `DIVIDEND-T-PLUS-1-v1` | active | A-share convention: dividends declared on FY t results are paid in year t+1. The payout driver is dividends_paid[t+1] / parent_net_income[t]. Projected year-t dividends paid = dividends declared on FY t-1. Dividends declared on the final projected FY are unpaid at the horizon (Phase 6 must treat them consistently). |
| `ANNOUNCED-DIVIDEND-BASE-v1` | active | Cash dividends announced by as_of with ex_date after the base FY end are unpaid at the base balance-sheet date. They are deducted from base cash and base equity (and total assets) and replace the policy's FY-base declaration. Amount = cash_per_share x shares before ex_date (last known market shares x known pending share ratios before ex_date). Phase 7: holders at as_of receive those with ex_date > as_of. |
| `INTEREST-OPENING-DEBT-v2` | active | Interest expense = cost_of_debt x opening term debt + (cost_of_debt + revolver_spread) x opening revolver balance (opening balances avoid circularity). Interest income = cash_interest_rate x max(opening cash, 0). |
| `REVOLVER-RATE-v1` | active | Revolver rate = cost_of_debt + configurable revolver_spread (default 0). Debt repayments retire the revolver first. |
| `CASH-INTEREST-ZERO-v1` | active | Interest income on cash defaults to 0 (cash_interest_rate = 0). This is conservative and labeled. Excess cash is valued in the Phase 6 bridge instead. |
| `BS-RESIDUAL-WARN-v1` | active | The base-year unexplained balance-sheet residual (assets - liabilities - equity under source definitions) is held constant. If abs(residual) > bs_residual_warn_ratio (default 5%) x total assets => WARNING BASE_BS_RESIDUAL_LARGE. |
| `LEASE-BRIDGE-DEBTLIKE-v1` | active | (Phase 6) Lease liabilities are debt-like in the EV-to-equity bridge. Since FCFF (LEASES-EXCLUDED-v1) does not deduct lease principal, it must not be deducted twice. |
| `MINORITY-BOOK-BRIDGE-v1` | active | (Phase 6) Minority interest is deducted in the bridge at book value (labeled approximation). Minority dividends are not modelled. |
| `WACC-INPUTS-DEFERRED-v1` | active | WACC / cost-of-equity inputs (risk-free rate, ERP, beta source) are deferred to Phase 6 and require an owner decision. Phase 2 only defines the typed rates. |
