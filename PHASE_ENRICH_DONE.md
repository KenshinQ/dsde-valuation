# PHASE_ENRICH — Industry / Shares / Corporate Actions — DONE

Local commits only. Date: 2026-10-20 (Asia/Shanghai).

## Feasibility matrix

| Need | Source | Fields | PIT publish time? | Local-first path | Gaps |
|---|---|---|---|---|---|
| Industry (prefer Shenwan L1) | **EM F10** `CompanySurveyAjax` (`sshy`, `sszjhhy`) | board + CSRC strings → **SW2021_L1 proxy** | Listing date `ssrq` only (no reclass history) | `em_industry_profile` in fund DuckDB | **No official Shenwan L1** on EM datacenter / HiThink stock meta / valuations snapshot. HiThink `ths-index-list?tag=industry` has THS boards (银行/证券/保险) but constituents are current-only and SSL flaky. |
| Shares outstanding | **EM** `RPT_F10_EH_EQUITY` | `TOTAL_SHARES`, `NOTICE_DATE` | **Yes** — `NOTICE_DATE` | `em_equity_changes` | Diluted shares not separate. HiThink fundamentals DB has no share capital series. |
| CA cash / 送转 | **EM** `RPT_SHAREBONUS_DET` | `PLAN_NOTICE_DATE`, `NOTICE_DATE`, `EX_DIVIDEND_DATE`, `PRETAX_BONUS_RMB`, `BONUS_IT_RATIO` (per **10**) | **Yes** — plan/notice announce | `em_sharebonus` | Pre-disclosure rows without ex_date skipped. |
| CA allotment / rights | HiThink / marketdb `raw_adjustment_events` | `allotment_ratio`, `ex_date` | **No announce date** | — | **Deferred** (`HITHINK-ALLOTMENT-DEFER-v1`). Never invent announce from ex_date. |
| HiThink adjustment-factors API | `/api/a-share/corporate-actions/adjustment-factors` | `ex_date_ms`, DPS, bonus | ex_date only | marketdb already filled | Same announce gap as marketdb. |

### Winner per need (ingestion plan)

| Need | Primary | Fallback | Assumption IDs |
|---|---|---|---|
| Industry | EM F10 → SW2021_L1 **proxy** | none (production may BLOCK if unset) | `INDUSTRY-SW-L1-PROXY-EM-v1`, `INDUSTRY-NO-RECLASS-HISTORY-v1` |
| Shares | EM `RPT_F10_EH_EQUITY` | leave null | `EM-SHARES-EQUITY-v1` |
| CA | EM `RPT_SHAREBONUS_DET` | empty CA table (provided=true) | `EM-CA-SHAREBONUS-v1`; supersedes `HITHINK-CA-DEFER-v1` |

## Implemented

- `src/vms/providers/eastmoney/` — client, DuckDB cache, sharebonus/equity/industry mappers, `enrich_bundle`
- Wired into `vms.providers.hithink.fetch_bundle` (local-first; REST on miss)
- CLI `ingest-hithink` reports `n_corporate_actions`, `n_classifications`, `n_market_with_shares`
- Tests: `tests/unit/providers/test_em_enrichment.py` (mapper + leakage); live smoke 600519 asserts enrichment
- Docs: assumptions (generated), `docs/data_contracts.md` §5.x, this file

## Live smoke evidence (600519.SH)

Prefer-local after first EM fill:

- Industry: `SW2021_L1:食品饮料`
- Corporate actions: ≥1 with real `PLAN_NOTICE_DATE` announced_at (not ex_date)
- Shares stamped on market bars from equity `NOTICE_DATE` timeline
- Future announce excluded by PIT snapshot filter (unit leakage test)

## Limitations (blockers called out)

1. **Official Shenwan L1 membership** — not available from probed public EM reports or HiThink A-share meta; proxy mapping only.
2. **Industry reclassification history** — unavailable; `published_at` = listing date proxy.
3. **Allotment/rights announce dates** — unavailable; not invented from ex_date.
4. **Diluted shares** — not on `RPT_F10_EH_EQUITY`; continue `DILUTED-SHARES-BASIC-v1`.
5. Overall fundamentals remain `LATEST_ONLY` → `pit_complete=false`.

非投资建议 / Not investment advice.
