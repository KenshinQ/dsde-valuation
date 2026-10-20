# Phase 5 — Financial & capital-allocation paths: DONE

Also includes Phase 4 follow-up decisions (coupled bootstrap, invalid-path gate, block-bootstrap deferral, no coverage autoswitch).

Not started: Phase 6 (DCF / WACC / multiples).

## Decisions recorded
| ID | Decision |
|---|---|
| PARAM-BOOTSTRAP-COUPLED-v1 | Shared bootstrap draw index across drivers within each path (implemented) |
| DEP-BLOCK-BOOTSTRAP-DEFER-v1 | Keep Gaussian-copula + shrink; residual block bootstrap deferred |
| INVALID-PATH-FRACTION-GATE-v1 | Production BLOCK (exit 5); exploratory + recorded override |
| COVERAGE-MISCAL-NO-AUTOSWITCH-v1 | Warning only; no silent persistence_t preference |
| PATH-STATEMENTS-v1 / FAILED-PATHS-EXCLUDED-v1 | Path-wise §9 projection; failed paths excluded from aggregates |

## Changed / new files
- `src/vms/sampling/simulate.py` — coupled bootstrap; `SamplingGateError`; mode/override gate
- `src/vms/statements/projection.py` — `year_drivers` path mode; per-share placeholders (`fcff_per_share`, `fcfe_per_share`, `book_equity_per_share`); `PATH_LABEL`
- `src/vms/statements/paths.py` — `FinancialPathBundle` / `project_financial_paths`
- `src/vms/pipeline.py` — `Phase5Run`, `run_path_projection`
- `src/vms/engine.py` — `project_financials(bundle, ...)` + `project_financials_from_load`
- `src/vms/cli/main.py` — `vms project-paths`; demo writes `financial_path_bundle.json`; SMOKE Phase 5
- assumptions + docs + CI
- Tests: `test_phase4_followups.py` (3), `test_path_statements.py` (9), `test_cli_project_paths.py` (1)

## Tests
- **420 passed** (~150 s box; clean-clone py3.11 noted below).
- Leakage 6/6 KILLED; invariant 7/7 KILLED.

## Acceptance evidence

1. **All valid paths pass accounting invariants.**
   - `test_all_valid_paths_pass_invariants`: 60/60 MC + central VALID, `violations == []`, reuses Phase 2 `check_invariants`.
   - `test_forced_negative_ebit_tax_loss_flags`: hostile margins still VALID (reconciled) with NEGATIVE_EBIT / tax-loss flags.

2. **Debt, cash, dividends, buybacks, issuance reconcile.**
   - Enforced by Phase 2 invariant checker on every path (`test_debt_cash_dividends_buybacks_issuance_reconcile`).
   - Series mirrors ledger values for cash/debt/dividends/repurchases/issuance/net_borrowing.

3. **Share count affects per-share results.**
   - Path projection writes `fcff_per_share`, `fcfe_per_share`, `book_equity_per_share`.
   - `test_share_count_affects_per_share`: `fcff/share == fcff/shares`; halving shares doubles per-share.
   - `test_wc_capex_dilution_path_mechanics`: share dilution / diluted_shares fields present; WC & capex in FCFF.

4. **Failed paths never silently enter summaries.**
   - `excluded_from_aggregates`, `failed[]` with reason codes, `valid_path_id_hash` over valid IDs only.
   - `test_failed_paths_never_enter_aggregates`: dropping a valid path changes the hash and `n`.
   - INVALID_PATH_FRACTION: production raises `SamplingGateError` → CLI exit 5; exploratory override recorded (`test_invalid_path_fraction_blocks_production`).

5. **Tests covering negative earnings / tax loss / WC / capex / dilution.**
   - `test_forced_negative_ebit_tax_loss_flags`, `test_wc_capex_dilution_path_mechanics`, plus path suite above.

Also: coupled bootstrap (`test_coupled_bootstrap_*`); coverage no-autoswitch; CLI `project-paths` artifacts (`vms-0.1.phase5`); facade `ValuationEngine.project_financials`.

## Limitations
1. CLI embeds slim MC projection ledgers (cap 100); full ledgers via the Python facade.
2. Per-share fields are FCFF/FCFE/book placeholders until Phase 6 value/share.
3. Buyback price still last known close (BUYBACK-PRICE-v1); no path-wise price process.
4. Central path failure is flagged but does not block MC aggregates.
5. Suite ~2.5 min (path projection × N).

## New questions
1. Should a failed central path BLOCK the Phase 5 run in production?
2. Persist full per-path ledgers as parquet by default (size vs auditability)?
3. Path-wise buyback price: last close vs a simple price path linked to book/residual income (Phase 6/7)?
