# Data contracts (Phase 1)

Sources of truth: `src/vms/schemas/observations.py`, `src/vms/schemas/fields.py`,
`src/vms/pit/snapshot.py`, `src/vms/quality/issues.py`. Artifact schema version: `vms-0.1.phase1`.
All models are pydantic v2, `extra="forbid"`, frozen.

## 1. Common rules
- **Timestamps** must be timezone-aware; naive values are rejected with an actionable message.
- **Currency:** ISO-4217 in {CNY, HKD, USD} at schema level. The internal base currency is CNY and
  **FX conversion is not implemented**: any non-CNY amount is a CRITICAL quality error
  (`CURRENCY_NOT_CNY`) so the run is BLOCKED in production.
- **unit_scale:** `unit | thousand | ten_thousand | million | hundred_million | billion`
  (aliases 元/千元/万元/百万元/亿元). Snapshot values are normalised to **CNY yuan** (`value_cny`);
  the reported value, unit and currency are kept alongside.
- Numbers must be finite. Missing data is `null` + `quality_status ∈ {missing, not_applicable}`;
  it is never filled.

## 2. as_of rule (versioned assumption ASOF-DATE-CLOSE-1)
A date-only as_of (`--as-of 2026-06-30`) means **2026-06-30T15:00:00+08:00** (A-share close).
Announcements published after the close (e.g. 18:00) are excluded until the next date's as_of.
Explicit tz-aware datetimes are used as given. The rule id/version is written into
`request.json`, `data_manifest.json` and `pit_snapshot.json`.

## 3. Canonical field vocabulary — registry `FIELDS-1`
- **kind**: `flow` (period amount; eligible for cumulative→standalone conversion) or
  `stock` (point-in-time balance; **never** converted).
- **unit**: all fields are currency amounts (CNY yuan after normalisation).
- **sign**:
  - `positive_magnitude`: stored as a **non-negative magnitude even though it is an outflow/expense**.
    `capex = 100` means 100 of cash spent. Same for `dividends_paid`, `share_repurchases`,
    `cost_of_revenue`, `operating_expenses`, `interest_expense`, `depreciation_amortization`,
    `debt_repayment`, `debt_issuance`, `share_issuance_proceeds`.
  - `nonnegative`: cannot be negative by nature (revenue, cash, receivables, total assets, …).
  - `signed`: either sign is meaningful; the description gives the direction.
  - A negative value in a positive_magnitude/nonnegative field is CRITICAL (`SIGN_CONVENTION_VIOLATION`).
    It is **not** flipped automatically, because the provider may already have flipped it, and a second
    flip would be wrong.
- Non-canonical field names are kept, flagged `NON_CANONICAL_FIELD` (WARNING), and never converted.
- A statement_type that disagrees with the registry is CRITICAL (`STATEMENT_TYPE_MISMATCH`).

| field_name | statement_type | kind | sign convention | description |
|---|---|---|---|---|
| `revenue` | income | flow | nonnegative | Operating revenue (营业收入) |
| `cost_of_revenue` | income | flow | positive_magnitude | Cost of revenue (营业成本), stored positive |
| `gross_profit` | income | flow | signed | Revenue - cost of revenue; negative = gross loss |
| `operating_expenses` | income | flow | positive_magnitude | Selling + G&A + R&D (+ taxes & surcharges if provider includes), stored positive |
| `ebit` | income | flow | signed | Operating profit before interest and tax; negative = loss |
| `interest_expense` | income | flow | positive_magnitude | Gross interest expense, stored positive |
| `tax_expense` | income | flow | signed | Income tax expense; negative = tax benefit |
| `parent_net_income` | income | flow | signed | Net income attributable to parent (归母净利润) |
| `depreciation_amortization` | income | flow | positive_magnitude | D&A, stored positive |
| `cash_flow_from_operations` | cash_flow | flow | signed | Net CFO; negative = net operating outflow |
| `capex` | cash_flow | flow | positive_magnitude | Purchases of PP&E/intangibles, stored as positive outflow magnitude |
| `acquisitions_net` | cash_flow | flow | signed | Acquisitions net of disposals; positive = net cash OUTflow |
| `dividends_paid` | cash_flow | flow | positive_magnitude | Cash dividends paid, positive magnitude |
| `share_repurchases` | cash_flow | flow | positive_magnitude | Cash spent on buybacks, positive magnitude |
| `share_issuance_proceeds` | cash_flow | flow | positive_magnitude | Cash from equity issuance, positive |
| `debt_issuance` | cash_flow | flow | positive_magnitude | Cash from new borrowings, positive |
| `debt_repayment` | cash_flow | flow | positive_magnitude | Cash used to repay borrowings, positive |
| `cash` | balance_sheet | stock | nonnegative | Cash and equivalents |
| `interest_bearing_debt` | balance_sheet | stock | nonnegative | Short + long-term borrowings + bonds |
| `accounts_receivable` | balance_sheet | stock | nonnegative | Trade receivables (incl. notes) |
| `inventory` | balance_sheet | stock | nonnegative | Inventories |
| `accounts_payable` | balance_sheet | stock | nonnegative | Trade payables (incl. notes) |
| `contract_assets` | balance_sheet | stock | nonnegative | Contract assets |
| `contract_liabilities` | balance_sheet | stock | nonnegative | Contract liabilities / advances |
| `goodwill` | balance_sheet | stock | nonnegative | Goodwill |
| `intangible_assets` | balance_sheet | stock | nonnegative | Intangible assets |
| `minority_interest` | balance_sheet | stock | signed | Non-controlling interests (can be negative) |
| `total_assets` | balance_sheet | stock | nonnegative | Total assets |
| `total_liabilities` | balance_sheet | stock | nonnegative | Total liabilities |
| `total_equity` | balance_sheet | stock | signed | Total equity INCLUDING minority interest; identity: total_assets = total_liabilities + total_equity |
| `parent_equity` | balance_sheet | stock | signed | Equity attributable to parent |

## 4. Input tables
Directory with one file per table, either `.csv` or `.parquet` (both present → error):

| table | required | known-at time |
|---|---|---|
| `financial_observations` | yes | `published_at` |
| `market_observations` | yes | `timestamp` (a close is known at its own timestamp) |
| `corporate_actions` | no (absence → `CORPORATE_ACTIONS_UNAVAILABLE` warning) | `announced_at` |
| `sources.yaml` | no (absence → every source undeclared → PIT_INCOMPLETE) | — |

CSV: an empty cell means null; errors are reported as `file:line N`. Parquet: timestamps must be
tz-aware; errors are reported as `file:row N`.

### FinancialObservation
| field | type | rule |
|---|---|---|
| instrument_id | str | non-empty |
| period_end | date | |
| published_at | datetime | tz-aware; date ≥ period_end |
| ingested_at | datetime? | tz-aware; ≥ published_at |
| statement_type | income / cash_flow / balance_sheet | must match the registry for canonical fields |
| field_name | str | see §3 |
| value | float? | finite |
| currency, unit_scale | | see §1 |
| source_id | str | non-empty |
| revision_id | str? | |
| quality_status | observed / derived / missing / not_applicable / low_confidence | `value is null` ⇔ missing/not_applicable |

### MarketObservation
instrument_id, timestamp (tz), raw_close > 0, adjusted_close? > 0 (**vendor field, audit only — never
used in snapshots**), shares_outstanding? > 0 (shares), corporate_action_version?, currency, source_id.

### CorporateActionEvent
| field | rule |
|---|---|
| action_id | revisions of the same action share an id and have a later `announced_at` |
| action_type | cash_dividend / bonus_share / stock_split / share_issuance / share_cancellation |
| announced_at | tz-aware; the PIT known-at time |
| ex_date | ≥ announced_at date (Asia/Shanghai); the action is *effective* from ex_date |
| share_ratio | post-action shares per pre-action share (10送3 = 1.3); required and ≠ 1 for share actions |
| cash_per_share | required for cash_dividend (gross, per pre-action share) |
| currency, source_id, revision_id | |

### SourceDescriptor (`sources.yaml`)
```yaml
sources:
  - source_id: SYNTHETIC
    reporting_convention: CN_CUMULATIVE_YTD   # CN_CUMULATIVE_YTD | STANDALONE_QUARTER | UNKNOWN
    versioning: FULL_HISTORY                  # FULL_HISTORY | LATEST_ONLY | UNKNOWN
    fiscal_year_end: "12-31"                  # only calendar fiscal years are supported
```

## 5. PIT snapshot (`pit_snapshot.json`, PIT-SNAPSHOT-1)
- A record is included only if its known-at time ≤ as_of. The snapshot is a pure function of the
  records known at as_of. Information known later (new periods, restatements, prices, corporate
  actions, action revisions) cannot change it. tests/leakage proves this, and
  `scripts/leakage_mutation_check.sh` shows that injected leaks are caught.
- **Versions/restatements:** per key (period_end, statement_type, field_name), every known version is
  kept in `version_history`. The value used is the latest published version (ties → source_id).
  Two sources that disagree → `CONFLICTING_SOURCES` (CRITICAL). The same source and published_at with
  different values → `CONFLICTING_VERSIONS` (CRITICAL). Exact duplicates are deduplicated with a WARNING.
- **basis:** `balance` (stocks), `cumulative_ytd` / `standalone_quarter` / `unknown_basis` (flows, from the
  declared source convention), `unclassified` (non-canonical).
- **Cumulative → standalone:** applied only to flows from a source declared `CN_CUMULATIVE_YTD`, and only
  for calendar quarter ends: Q1 = YTD(Q1), Qn = YTD(Qn) − YTD(Qn−1) within the same fiscal year, using the
  versions known at as_of. The reported cumulative record is kept. Each derived record has
  `quality_status=derived` (or `low_confidence` if any input is), a `formula`, and `derived_from` refs.
  If an input is unknown or null, the derived record is `missing` with a reason flag.
  Undeclared/UNKNOWN convention → no conversion + `CUMULATIVE_CONVENTION_UNKNOWN`. Stocks are never converted.
- **Prices:** `pit_adjusted_close = raw_close × pit_adjustment_factor`. The factor is the product of
  1/share_ratio over *known and effective* bonus_share/stock_split actions with ex_date in (obs date, as_of date].
  Cash dividends are not price-adjusted here (they are handled as distributions in Phase 7).
- **Corporate actions:** the latest known version per action_id, with status `effective` (ex_date ≤ as_of date)
  or `pending`.

## 6. Data-quality report (`data_quality_report.json`, DQ-REPORT-1)
Status precedence: any CRITICAL → **BLOCKED**; otherwise any PIT_INCOMPLETE finding → **PIT_INCOMPLETE**;
otherwise any WARNING → **PASS_WITH_WARNINGS**; otherwise **PASS**. PIT_INCOMPLETE does not block
valuation, but such data must not be used to claim unbiased historical performance (§5.1).

Production mode + BLOCKED → CLI exit **3**, and `pit_snapshot.json` is not written. With
`--mode exploratory --override-reason "..."` the run proceeds. The report keeps `status=BLOCKED` and
`usable_for_production=false`, and records `override.reason` and `overridden_critical_codes`.

The full issue catalogue (code → severity, check, message) is in `src/vms/quality/issues.py::CODES`.
Checks: DATA_AVAILABILITY, DUPLICATES_CONFLICTS, FIELD_VOCABULARY, UNIT_CURRENCY, POST_AS_OF,
PERIOD_COVERAGE, CUMULATIVE_CONVERSION, BALANCE_SHEET_IDENTITY, CASH_FLOW_SIGN_UNIT,
SHARE_COUNT_CORPORATE_ACTIONS, PRICE_ADJUSTMENT, PROVENANCE, PIT_VERSIONING, RESTATEMENTS: **RUN**.
EV_BRIDGE: **DEFERRED to Phase 6**.

## 7. Not yet covered
FX conversion; non-calendar fiscal years; suspension/price-limit flags; price corrections by vendors
(market rows have no revision field); staleness of last price; per-record reporting-convention overrides.
