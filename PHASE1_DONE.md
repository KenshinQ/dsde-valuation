# Phase 1: PIT data and integrity gates (completion report; VMS-0.1 §18, reported per §21)

Date: 2026-10-20 (Asia/Shanghai). Local git only, no remote. Phase 2 not started.
Status: **all Phase 1 acceptance criteria pass.** This is engineering evidence on SYNTHETIC data
only; it says nothing about investment value.

## Decisions implemented (from kenshin, 2026-10-20)
- Date-only as_of means 15:00:00 Asia/Shanghai. This is versioned rule **ASOF-DATE-CLOSE-1** (`vms.pit.asof`),
  recorded in request/manifest/snapshot. Explicit tz-aware datetimes are still allowed; naive ones are rejected.
- Canonical field vocabulary **FIELDS-1** (31 fields): `vms.schemas.fields` plus a table in
  docs/data_contracts.md, kept in sync by test. Each field declares flow/stock, unit, and sign convention.
  capex, dividends_paid, share_repurchases (and other outflows) are stored as positive magnitudes.
- Cumulative → standalone conversion only for sources declared `CN_CUMULATIVE_YTD` in `sources.yaml`.
  Otherwise flows are kept as reported and flagged. Never applied to stocks.
- No provider adapters: CSV/Parquet ingestion of the canonical schema only.
- The synthetic generator emits cumulative YTD flows, a restatement, a late annual report, a bonus share
  and a cash dividend with a later revision, and vendor 前复权 prices that embed the future action.

## Changed files
New:
```
src/vms/schemas/fields.py            canonical field registry FIELDS-1
src/vms/pit/asof.py                  ASOF-DATE-CLOSE-1 parsing
src/vms/pit/snapshot.py              PIT snapshot builder
src/vms/quality/issues.py            issue catalogue (code → severity/check/message) + collector
src/vms/quality/checks.py            §6.1 checks + check catalogue (EV_BRIDGE DEFERRED)
src/vms/quality/report.py            DataQualityReport, status precedence, assess(), gate()
scripts/leakage_mutation_check.sh    injects 4 leaks; leakage suite must fail on each
tests/factories.py
tests/unit/{test_fields_asof,test_schemas_phase1,test_io,test_snapshot,test_quality,test_docs_sync}.py
tests/leakage/test_leakage.py        (replaces README placeholder)
PHASE1_DONE.md
```
Modified:
```
pyproject.toml, requirements.lock    + pyarrow (Parquet; justified in README)
config/default.yaml                  + quality thresholds block; timezone comment updated
src/vms/__init__.py                  SCHEMA_VERSION vms-0.1.phase1, IMPLEMENTED_PHASE PHASE_1
src/vms/schemas/observations.py      + CorporateActionEvent, SourceDescriptor, ReportingConvention, Versioning
src/vms/schemas/__init__.py, schemas/config.py (+QualityConfig)
src/vms/data/io.py                   CSV/Parquet, corporate_actions, sources.yaml, file hashes
src/vms/data/synthetic.py            Phase-1 scenarios
src/vms/reporting/metadata.py        instant-normalised data hash, content_run_id, ArtifactStamp
src/vms/cli/main.py                  build-snapshot; validate-data --as-of runs real PIT+gates; demo goes through gate; exit 3
src/vms/pit/__init__.py, quality/__init__.py (now implemented)
tests/conftest.py, tests/unit/{test_config,test_package_skeleton}.py, tests/property/test_properties.py,
tests/integration/test_cli.py
docs/architecture.md, docs/data_contracts.md, README.md, .github/workflows/ci.yml,
examples/synthetic_operating_company/{README.md,generate_data.py}
```

## Tests executed
| Environment | Command | Result |
|---|---|---|
| Fresh `git clone` → new `.venv` Python 3.11.17 → `uv pip sync requirements.lock` → `-e . --no-deps` | `python -m pytest` | **218 passed** (unit 181, integration 22, property 3, leakage 12) |
| same | `scripts/leakage_mutation_check.sh` | 4/4 injected leaks **KILLED** |
| Repo `.venv` Python 3.13.5 | `python -m pytest` | 218 passed |

Hypothesis leakage properties run 40 + 25 random as_of values (2021–2025, any hour).

## Evidence per Phase 1 acceptance criterion
1. **Post-as_of observations are excluded.**
   `build_snapshot` filters financials by `published_at`, prices by `timestamp`, and actions by
   `announced_at` before any processing.
   - Tests: `test_every_snapshot_input_known_at_as_of` (property; also covers `version_history`),
     `test_future_publication_excluded_late_annual_report`, `test_date_only_as_of_excludes_evening_publication_same_day`
     (2023-04-28 excludes the 18:00 Q1 report; 2023-04-29 includes it),
     `test_prices_after_as_of_excluded_close_at_as_of_included` (14:59 vs 15:00), `test_corporate_action_not_known_before_announcement`.
   - CLI: `build-snapshot --as-of 2024-05-15` → `excluded_post_as_of.financial=93` records and `MISSING_QUARTER` (2023Q4 annual report not yet published).
2. **Later restatements cannot change earlier snapshots.**
   - `test_snapshot_invariant_to_information_after_as_of` (property): a snapshot from the full data equals
     one from only the known records, and all quality findings except the post-as_of count are equal too.
   - `test_future_restatement_excluded`: FY2022 is r0 at 2023-08-28 15:00 and r1 at 2023-08-29.
     The derived Q4 standalone uses only the known versions.
   - `test_injected_future_restatement_of_old_period_does_not_change_old_snapshot` (10× value, r9, published 2025).
   - `test_restatement_latest_known_version_used_history_kept`.
   - Mutation script: widening any of the 3 filters by 30 days, or applying unannounced/ineffective
     adjustments, makes the suite fail.
3. **Quarterly cumulative flows are converted only when reporting rules are known.**
   - `test_cn_cumulative_ytd_converted_to_standalone` (100/250/330/500 → 100/150/80/170, with formula and derived_from).
   - `test_no_conversion_without_declared_convention` + `test_cumulative_unknown_flagged` (`CUMULATIVE_CONVENTION_UNKNOWN`).
   - `test_standalone_convention_not_converted`, `test_stocks_never_converted`, `test_irregular_period_not_converted`.
4. **Missing/derived values preserve provenance.**
   - Derived records carry `quality_status=derived|low_confidence`, `formula`, `derived_from` (source:field@period#rev@published_at),
     and `published_at = max(inputs)`.
   - Underivable values become `missing` with a reason flag (`test_prior_missing_yields_missing_with_provenance`,
     `test_null_input_propagates_missing`, `test_low_confidence_input_propagates`).
   - Explicit nulls stay null with their source and status (`test_missing_values_preserved_and_reported`).
   - Reported value/unit/currency and `version_history` are kept. The `PROVENANCE` check raises CRITICAL if a derived record lacks inputs.
5. **Critical errors block production-mode valuation.**
   - `test_critical_blocks` (sign violation in capex/revenue/cash, non-CNY, statement-type mismatch, conflicting versions),
     `test_no_market_or_financial_data_blocks`, `test_market_currency_not_cny`.
   - CLI: production mode → exit **3**, report + manifest written, **no pit_snapshot.json**
     (`test_build_snapshot_blocked_production_exit_3_no_snapshot`, `test_validate_data_as_of_blocked_exit_3`).
   - Exploratory requires `--override-reason`. The report keeps `status=BLOCKED, usable_for_production=false` and records
     `override.reason` + `overridden_critical_codes` (`test_exploratory_override_recorded`, `test_build_snapshot_exploratory_override_recorded`).
   ```
   $ vms build-snapshot --input data --ticker SYN000001.SZ --as-of 2024-12-31 --out s2    # capex sign corrupted
   error: SYN000001.SZ as_of 2024-12-31T15:00:00+08:00: BLOCKED by critical data-quality errors ['SIGN_CONVENTION_VIOLATION']. ...   exit=3
   ```
6. **Leakage tests cover financials, prices and corporate actions.** `tests/leakage/test_leakage.py` (12 tests):
   - financials: future publication, same-day evening publication, future restatement, injected restatement
   - prices: post-as_of closes; vendor 前复权 `adjusted_close` never enters the snapshot, and before the
     announcement `pit_adjusted_close == raw_close` while the vendor value embeds the 1.3 factor
   - corporate actions: unknown before announcement; pending actions do not adjust prices; a revision after as_of is
     invisible; effective actions adjust only earlier prices; a future action cannot explain a past share change
   - plus the two property tests above. Mutation evidence: `scripts/leakage_mutation_check.sh`.

### §6.1 check coverage (`data_quality_report.json` → `checks`)
RUN: DATA_AVAILABILITY, DUPLICATES_CONFLICTS, FIELD_VOCABULARY, UNIT_CURRENCY, POST_AS_OF, PERIOD_COVERAGE,
CUMULATIVE_CONVERSION, BALANCE_SHEET_IDENTITY, CASH_FLOW_SIGN_UNIT, SHARE_COUNT_CORPORATE_ACTIONS,
PRICE_ADJUSTMENT, PROVENANCE, PIT_VERSIONING, RESTATEMENTS. **DEFERRED: EV_BRIDGE (Phase 6).**
Each check has at least one positive test in `tests/unit/test_quality.py`.

## Known limitations
- **No FX:** any non-CNY amount BLOCKS (by design, rather than silently dropping it).
- **Calendar fiscal years only** (`fiscal_year_end: "12-31"`; others are rejected by the schema).
- Reporting convention is per source, not per record or per field.
- Market rows have no revision/published field, so vendor price corrections cannot be versioned.
  A close is assumed known at its own timestamp.
- Vendor `adjusted_close` is excluded from snapshots. The PRICE_ADJUSTMENT audit check still reads it for known
  rows, so a vendor's later re-adjustment could change that warning (not the snapshot).
- `pit_adjusted_close` adjusts only for bonus_share/stock_split. Dividends are distributions (Phase 7).
  share_issuance/cancellation are not price-adjusted.
- Thresholds (balance-sheet tolerance 0.5%, share change 1%, unit-jump 100×, capex/revenue 5, late 120d) are
  hand-set assumptions in config.
- `MISSING_QUARTER` only checks gaps between the first and last known periods. There is no staleness check
  (latest period vs as_of), no stale-price/suspension check, and no price-limit flags.
- Balance-sheet identity is a WARNING (spec: "subject to source definitions"), not a block.
- `PIT_INCOMPLETE` does not block. It marks data unfit for unbiased-history claims.
- Status precedence BLOCKED > PIT_INCOMPLETE > PASS_WITH_WARNINGS hides warnings in the status field
  (they remain in `issues`/`severity_counts`).
- Single-instrument snapshot per call; `validate-data --as-of` loops instruments.
- Unit-jump detection is heuristic (≥100× between versions or consecutive balance periods).
- CI workflow file is untested remotely (no remote).
