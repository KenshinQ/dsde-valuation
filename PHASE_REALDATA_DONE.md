# Real A-share HiThink adapter — DONE

Local commits only. No DSDE wiring / Phase 11 valuation changes beyond the adapter.

## Policy encoded (versioned assumptions)

| ID | Rule |
|---|---|
| HITHINK-PIT-NOTICE-v1 | `published_at` = EM NOTICE_DATE @ 15:00 Asia/Shanghai; never `period_end_ms` |
| HITHINK-REPORT-DATE-FALLBACK-v1 | Fallback `report_date_ms` + `low_confidence` + `published_at_source=hithink_report_date_ms_fallback` |
| HITHINK-LATEST-ONLY-v1 | `source_id=hithink_em_notice`, `versioning=LATEST_ONLY` → `pit_complete=false` |
| HITHINK-UNITS-YUAN-v1 | Amounts = CNY yuan |
| HITHINK-NO-VENDOR-QFQ-v1 | `raw_close` only; `adjusted_close=null` |
| HITHINK-LOCAL-FIRST-v1 | marketdb + fund DuckDB first; Recipe E REST on miss; no silent vendor swap; no key echo |
| HITHINK-CA-DEFER-v1 | CA empty (no announced_at on adj events) |
| HITHINK-FIELD-MAP-v1 | Column map in `mapping.py` + docs/data_contracts.md |

## Deliverables

- `src/vms/providers/hithink/` — `fetch_bundle`, mapping, PIT join, local DuckDB store, optional lab Recipe E
- CLI: `vms ingest-hithink`; `vms build-snapshot --provider hithink`
- Tests: mapper + NOTICE leakage (unit); live smoke on 600519.SH if DBs present (else skip)
- Docs: assumptions, data_contracts mapping, README; optional extra `[hithink]` (duckdb, requests)
- Core `import vms` / synthetic suite does not require DuckDB or live HiThink

## Acceptance evidence

1. **Offline synthetic + existing suite green** — full pytest after adapter (see report).
2. **Mapper / PIT leakage tests** — `tests/unit/providers/test_hithink_*.py` pass; future NOTICE excluded; fallback marked; period_end never used as PIT when NOTICE present.
3. **Live smoke (600519.SH, local DBs):**
   - `vms ingest-hithink --ticker 600519.SH --prefer-local` → n_financial=692, n_market=2427, notice_joined=120, fallback=0
   - `build-snapshot --as-of 2025-06-30` → `pit_complete=false`, `SOURCE_NOT_FULL_HISTORY`, `POST_AS_OF_EXCLUDED` (financial+market), all `adjusted_close` null
4. **No key leakage / no period_end-as-PIT / no silent vendor swap** — diagnostics redact secrets; REST only via Recipe E when local miss / `--refresh`.
5. **Local commits** — see git log.

## Known limitations (real A-share)

- No Shenwan L1 in meta → `INDUSTRY_UNCLASSIFIED` (production BLOCKED; use exploratory + reason).
- Inventory / AP / D&A absent from HiThink store.
- `total_debt` ≈ interest-bearing debt (approximation).
- `dividends_paid` from mixed dividends+interest cashflow field → `low_confidence`.
- Corporate actions not ingested (no announce timestamp).
- Shares outstanding null.
- HiThink LATEST_ONLY → excluded from Phase 9 unbiased metrics by design.
