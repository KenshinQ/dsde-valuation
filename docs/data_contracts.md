# Data contracts (Phase 0)

Source: `src/vms/schemas/observations.py`. All models are pydantic v2, `extra="forbid"`, frozen.
Schema version: `vms-0.1.phase0`.

## Common rules
- **Timestamps** (`published_at`, `ingested_at`, `timestamp`, `as_of`) must be timezone-aware.
  Naive values fail: `published_at=... is timezone-naive; provide an explicit offset, e.g. '...+08:00'`.
- **Currency:** ISO-4217, one of `CNY`, `HKD`, `USD` (case/whitespace normalised). Internal base
  currency is CNY; FX conversion is **not** implemented (Phase 1 needs PIT FX data).
- **unit_scale:** `unit | thousand | ten_thousand | million | hundred_million | billion`;
  aliases `元, 千元, 万元, 百万元, 亿元` accepted. `value_in_units` applies the multiplier.
- Numbers must be finite (NaN/Inf rejected — use `null` + quality status).

## FinancialObservation
| field | type | rule |
|---|---|---|
| instrument_id | str | non-empty |
| period_end | date | |
| published_at | datetime | tz-aware; date ≥ period_end |
| ingested_at | datetime? | tz-aware; ≥ published_at (§5.1; optional in Phase 0) |
| statement_type | `income \| cash_flow \| balance_sheet` | |
| field_name | str | non-empty; canonical field vocabulary is Phase 1 |
| value | float? | finite |
| currency | str | see above |
| unit_scale | UnitScale | see above |
| source_id | str | non-empty |
| revision_id | str? | |
| quality_status | `observed \| derived \| missing \| not_applicable \| low_confidence` | `value is null` ⇔ status ∈ {missing, not_applicable} |

## MarketObservation
| field | type | rule |
|---|---|---|
| instrument_id | str | non-empty |
| timestamp | datetime | tz-aware |
| raw_close | float | > 0, finite |
| adjusted_close | float? | > 0 |
| shares_outstanding | float? | > 0 (shares, unit = 1 share) |
| corporate_action_version | str? | |
| currency | str | **added vs §5.3 minimal contract** because §5.2 requires currency on all amounts |
| source_id | str | non-empty |

## ValuationRequest
| field | type | rule |
|---|---|---|
| instrument_id | str | non-empty (identifier format not constrained) |
| as_of | datetime | tz-aware |
| spot_price | float | > 0, finite |
| horizons_years | list[int] | ≥ 1 item, all > 0, unique; stored sorted |
| monte_carlo_paths | int | 1 … 10,000,000 (not bool) |
| random_seed | int | 0 … 2^63−1 (not bool) |
| configuration_version | str | non-empty |

## CSV layout (`vms validate-data`)
Directory with `financial_observations.csv` and `market_observations.csv`; columns = field names
above; empty cell = null. Unknown or missing required columns are rejected; row errors report
`<file>:line N: <field>: <message> (got <value>)`.

CLI `--as-of` accepts ISO-8601 with offset, or a bare date interpreted as 23:59:59 in the config
timezone (Asia/Shanghai). Naive datetimes are rejected.

## Not yet enforced (later phases)
PIT filtering (`published_at <= as_of`), restatement versioning, `PIT_INCOMPLETE`, duplicates,
cumulative-quarter conversion, cross-record unit/currency consistency, canonical field names,
quality states `PASS/PASS_WITH_WARNINGS/BLOCKED/PIT_INCOMPLETE` — Phase 1.
