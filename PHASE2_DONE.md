# Phase 2 — Drivers and deterministic statements: DONE

Spec: SPEC.md §7.1–7.2, §9, §10, §18 Phase 2. Code commit: `19e93ec`. There is **no valuation** yet:
projections are labeled `DETERMINISTIC_CENTRAL_CASE_NOT_A_VALUATION`, and the demo is `PHASE2_SMOKE_NOT_A_VALUATION`.
Standalone; no legacy imports (enforced by test).

## Owner decisions on Phase 1 questions (recorded as versioned assumptions, docs/assumptions.md)
| # | Decision | ID | Implementation |
|---|---|---|---|
| 1 | Non-CNY keeps blocking; no FX | SCOPE-CNY-v1 | unchanged gate |
| 2 | PIT_INCOMPLETE does not block; Phase 9 must exclude it | PIT-INCOMPLETE-v1 | `PITSnapshot.pit_complete` (PIT-SNAPSHOT-2) |
| 3 | Price-row revisions deferred | PRICE-REVISION-DEFER-v1 | documented limitation |
| 4 | Rights/placement price adjustment deferred; dilution via share counts | RIGHTS-ADJ-DEFER-v1 | documented; Phase 5 note |
| 5 | Staleness WARNING by CN deadlines | STALENESS-CN-DEADLINE-v1 | `STALE_FINANCIALS` check |
| 6 | Source conflicts block; priority deferred | SOURCE-CONFLICT-BLOCK-v1 | unchanged gate |

## Changed files (6b6f6f2..19e93ec: 53 files, +2784/−93)
```
src/vms/assumptions.py               versioned assumption register + cite()
src/vms/drivers/history.py           annual history from the PIT snapshot (FY = 12-31 YTD or 4 standalone quarters)
src/vms/drivers/definitions.py       18 driver definitions (formula, flags)
src/vms/drivers/transforms.py        identity / log1p / bounded logit
src/vms/drivers/estimate.py          central values (median, clipped, prior fallback, flags)
src/vms/drivers/profiles.py          SectorProfile ABC + registry + resolve_profile (config-driven UNSUPPORTED_PROFILE)
src/vms/statements/ledger.py         TracedValue / write-once Ledger / unresolved_refs
src/vms/statements/tax.py            FIFO tax-loss pool with N-year expiry
src/vms/statements/projection.py     operating_company profile: §9 projection (DET-PROJ-1)
src/vms/statements/invariants.py     independent §9.2 checker, 18 reason codes
src/vms/statements/cashflows.py      FCFFSeries/FCFESeries, WACC/CostOfEquity, present_value guard
src/vms/capital_allocation/policies.py  5 versioned policies
src/vms/pipeline.py                  assess → gate → profile → drivers → policy → projection
src/vms/cli/main.py                  `vms project`; demo runs Phase 2; exit codes 4/5
src/vms/{schemas,data,pit,quality}/… InstrumentClassification table, FIELDS-2 (non_recurring_items_pretax),
                                     pit_complete, STALE_FINANCIALS, config blocks industry/projection/capital_allocation
config/default.yaml, config/driver_profiles/operating_company.yaml (0.2.0, 18 drivers with priors)
scripts/invariant_mutation_check.sh  NEW
docs/assumptions.md (NEW), docs/architecture.md, docs/data_contracts.md, README.md, examples/*, CI
tests: company.py, test_drivers, test_profiles, test_projection, test_policies_invariants,
       test_tax_cashflow_types, property/test_projection_properties, integration/test_cli_project (all NEW);
       updated test_cli, test_quality, test_snapshot, test_docs_sync, test_fields_asof, test_package_skeleton
```

## Tests executed
| Run | Result |
|---|---|
| `pytest -q` (dev venv) | **301 passed**, 0 failed, 0 skipped (Phase 1: 205) |
| Clean clone → `uv venv --python 3.11` → `uv pip sync requirements.lock` → `pytest` | **301 passed** (Python 3.11.17) |
| clean clone `vms demo --seed 42` / `vms project … --as-of 2025-06-30` | exit 0 / exit 0, VALID, 0 violations |
| `scripts/leakage_mutation_check.sh` | 4/4 leaks KILLED |
| `scripts/invariant_mutation_check.sh` (NEW) | **6/6 modelling bugs KILLED** (CFO missing ΔNWC, FCFF missing capex, FCFE missing acquisitions, equity double-counting buybacks, shares ignoring buybacks, debt roll-forward wrong) |

New tests by file: drivers 14, profiles 10, projection 20, policies+invariants 23, tax+cash-flow types 7, projection
property 1 (40 hypothesis examples), CLI project 7, plus snapshot +1 and docs-sync +2.

## Acceptance evidence
**1. Every derived item traces to inputs/formulas — PASS**
- Each projected item is a write-once `TracedValue(value, formula, inputs)`. Inputs reference `item@year`, `driver:`,
  `policy:`, `config:`, `assumption:`, `corporate_action:` or `snapshot:<source>:<stmt>.<field>@<period>[basis]#<revision>`.
- `test_valid_and_fully_traced_for_every_policy` (×5 policies): `unresolved_refs == []`, every item has a formula,
  and every cited assumption exists. `test_base_items_trace_to_snapshot_records`: every `snapshot:` ref equals a record
  in the PIT snapshot. The projection itself REJECTS with `TRACE_UNRESOLVED` if any ref dangles.
- Drivers: `driver_diagnostics.json` lists each driver's formula, observations by year, method, and flags
  (`test_history_and_core_driver_values`, `test_estimates_median_flags_and_fallback`).
- Hand check of the §9 formulas: `test_spec_formulas_hand_check`.

**2. Accounting invariants pass synthetic fixtures — PASS**
- The invariant checker recomputes everything from the ledger independently. It covers the cash
  reconciliation, debt/equity/share roll-forwards, the balance sheet vs. constant base residual, NWC and income links,
  FCFF/FCFE composition, the FCFF−FCFE bridge, and non-negative tax, debt, and shares. Repurchase/issuance cash must equal shares × price.
  The min-cash floor is also checked, as is "no double counting of distributions".
- VALID for the SYNTHETIC demo company and for the crafted company under all 5 policies. Hypothesis covered 40 random
  combinations of growth, EBIT (incl. negative), capex, receivables, cash, and policy (`test_projection_valid_and_invariants_hold`).
- Tampering with any of 14 items yields the expected reason code (`test_tampered_projection_rejected_with_reason`).
  The REJECTED status is wired through (`test_rejected_projection_is_not_usable`), and the CLI exits 5. The mutation script proves that real engine bugs are caught.

**3. Tests cover negative earnings, tax losses, working capital, capex, and dilution — PASS**
- Negative earnings: `test_negative_earnings_and_tax_losses` checks that operating and book tax are 0, NOPAT = EBIT (NEGATIVE-EBIT-v1),
  dividends are 0, the pool grows, and the flags NEGATIVE_EBIT/NEGATIVE_NET_INCOME are set. `test_fixed_payout_and_negative_income`
  and `test_tax_rate_and_payout_skip_loss_years` cover the rest.
- Tax losses: `test_loss_carryforward_fifo_and_no_negative_tax`, `test_loss_expires_after_five_years` (usable in year
  +5, expired in year +6; TAX-CN-LCF-5Y-v1), `test_reconstruct_pool_from_history`, and `test_tax_loss_pool_shields_then_expires`
  (projected tax is below t×EBIT, and the pool is consumed monotonically).
- Working capital: `test_working_capital_effect` (higher receivables intensity raises ΔNWC and lowers FCFF by exactly that
  amount; year 1 is measured against the actual base balances).
- Capex: `test_capex_effect_and_asset_rollforward`. Acquisitions are kept separate from capex: `test_acquisitions_separate_from_capex`.
- Dilution: `test_dilution_and_buybacks_change_share_count` (diluted_share_growth, buyback shares = cash/price),
  `test_known_pending_bonus_share_applied_in_ex_year` (a known pending 10送3 is applied in its ex-date year, and the price is adjusted),
  and `test_share_growth_excludes_bonus_shares` (bonus shares are not counted as dilution in history).
- One-offs: `test_ebit_margin_one_off_handling`.

**4. FCFF/FCFE are not mixed — PASS**
- They are distinct pydantic types with a `kind` literal, extra=forbid, and no subclass relation. `present_value(FCFF, CostOfEquity)` and
  `present_value(FCFE, WACC)` raise `CashFlowTypeError`, as do `+` between series and cross-`model_validate`
  (`test_mixing_rejected`, `test_no_arithmetic_or_cross_validation`). Artifacts carry `"kind": "FCFF"/"FCFE"` (CLI test).
- They are computed from different ledger items, and a bridge identity checks them against each other (FCF_BRIDGE_FAIL).

**5. Unsupported profiles are flagged — PASS**
- 银行 / 非银金融 → `UNSUPPORTED_PROFILE` from a configurable list (INDUSTRY-SW-L1-v1). The projection is empty with
  `drivers=None`, but raw annual history is still reported. CLI exits **4** (`test_financials_unsupported`,
  `test_pipeline_unsupported_profile_no_projection`, `test_project_unsupported_profile_exit_4`).
- 房地产 / 公用事业 → supported, with PROFILE_CAUTION. Unclassified → generic profile with INDUSTRY_UNCLASSIFIED. A different scheme →
  UNSUPPORTED (INDUSTRY_SCHEME_MISMATCH). A profile_map entry pointing to an unregistered profile → ConfigError.
- Plug-in interface: register/validate tests. `test_no_scattered_sector_conditionals` greps `src/` and finds no sector names
  outside the assumption register.

**Phase 2 tests in data quality:** `test_stale_financials_warning_cn_deadlines` and `test_pit_complete_flag_and_classification`
(a later reclassification is invisible at as_of).

## Known limitations (honest)
- **Annual base only (ANNUAL-BASE-v1).** Interim quarters after the latest FY are ignored, and there is no stub period. At as_of
  2025-06-30, 2025Q1 is known but unused.
- **Central values = median of ≤5 years, clipped.** No shrinkage, mean reversion, or regimes; those are Phase 3. Priors and bounds are
  placeholders (DRIVER-PRIORS-PLACEHOLDER-v1). Year 1 jumps from the base-year ratios to the median (e.g. demo NWC: ΔNWC
  2025 is 10.4M vs ~35M in later years, so FCFF dips in 2026). This is visible and documented, not smoothed.
- **One-offs:** the `non_recurring_items_pretax` field is removed from the EBIT margin history only when reported. No
  automatic one-off detection. The pre-tax line carries no projected one-offs (ONE-OFFS-v1).
- **Dividends** are payout × same-year NI (PAYOUT-SAME-YEAR-v1). A-share practice pays the prior year's dividend in mid-year.
  **Known pending cash dividends are not yet deducted** (only share-changing pending actions are applied).
- **Interest** is computed on opening debt. The revolver uses the same cost_of_debt, and there is no interest on cash.
  cost_of_debt uses closing debt only (CLOSING_DEBT_ONLY).
- **Leases** are excluded from FCFF and from debt (LEASES-EXCLUDED-v1). SBC is assumed inside EBIT. Minorities are a constant
  share of NI; minority dividends are not modelled.
- **Balance sheet:** an unexplained base-year residual (total_assets − modelled items) is held constant and checked
  against, not forced to zero.
- **Tax:** a single effective rate per year is applied to taxable income after losses. Pools are reconstructed from ≤ available
  history, so earlier losses are unknown and assumed zero. Operating and book pools are kept separately (TAX-LOSS-POOL-FROM-BOOK-v1).
- **Diluted shares = basic shares.** No options or convertibles (DILUTED-SHARES-BASIC-v1). Buyback/issuance price = last PIT close.
- Calendar fiscal years only. CNY only. Rights issues are not price-adjusted.
- The full suite was developed on Python 3.13 and verified on Python 3.11.17 in a clean clone.

## New spec questions
1. **Stub period:** should Phase 3+ build the base from TTM / latest interim (e.g. 2025Q1) instead of the last FY?
2. **Unclassified industry:** keep "generic profile + warning", or block in production?
3. **Dividend timing:** model prior-year payout in year t (A-share practice) and deduct known pending cash dividends?
4. **Revolver/cash interest:** what rate for the revolver; should interest income on cash be modelled?
5. **Leases (Phase 6 bridge):** treat IFRS16 lease liabilities as debt-like in the equity bridge, keeping FCFF ex-lease?
6. **Minority dividends** and the minority-interest valuation in the bridge: book or multiple?
7. **Base-year balance residual:** acceptable as constant, or must the data contract require a fuller balance sheet?
8. **WACC/CoE inputs** (rf, ERP, beta source) remain open for Phase 6. Phase 2 only defines the types.
