# R3 / R2e — Deposit-taking FI peer PIT universe for R2c: DONE

Date: 2026-10-23 (Asia/Shanghai). Branch: `feat/r3-fi-peer-universe` (from `4add9d6` / R2c+d merge).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: `PHASE_R2CD_BANK_RIM_DONE.md`. Pace: **r3-default** (user widget).

Status: **R3 acceptance criteria pass** (post architecture-review BLOCKER + SHOULD-FIX) (builder + unit AC; 000001 smoke documents honest PEER_SCARCITY + exclusion funnel on thin local panel).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim OOS calibration, ensemble, gate lift, 非银金融 support, or `pit_complete=true`.

## Design
- **Builder** (`methods/rim/bank_peers.py`): discover candidates = lean curated A-share deposit-taking FI tickers ∪ local SW L1 proxy classifications (label from `em_industry_proxy.yaml` via `deposit_taking_fi_sw_label()` — no hardcoded industry tokens in Python).
- **Metric**: `pb_common = raw_close / ((TE − MI − OEI) / shares)` — same common-equity identity as RIM (`RIM-COMMON-EQUITY-v1`).
- **PIT**: financial `published_at` (NOTICE-aligned) and market `timestamp` must be `<= as_of`. Future notice/price → excluded.
- **MISSING_OEI**: peer excluded with canonical code `MISSING_OTHER_EQUITY_INSTRUMENTS` (alias `MISSING_OEI`); **never** treat total equity as common.
- **value-rim**: when `load.peers` empty and `auto_fi_peers=True` (default), auto-build and write `rim_fi_peers.json` **only if** subject is `FINANCIAL_INSTITUTION` or latest PIT SW label is deposit-taking FI; else flag `AUTO_FI_PEERS_SKIPPED_NON_FI`. CLI `--no-auto-fi-peers` → `AUTO_FI_PEERS_DISABLED`.
- **Universe flags**: peer-level cflags (MI assumed 0, PB numerator/denominator) stay in `peer_diagnostics` / exclusion records — do **not** pollute bundle `result_flags`.
- **Lean curated ownership**: ID allowlist in `bank_peers.LEAN_CURATED_*`; LABEL SoT = `em_industry_proxy.yaml` via `deposit_taking_fi_sw_label()`. Dual-universe drift accepted for lean v1; prefer classifications-only once panel is rich.
- **Assumption**: `RIM-FI-PEER-UNIVERSE-v1`.
- Legacy `industry.unsupported` / `vms value` gate **untouched**.
- **Smoke wording**: builder ready; thin local panel may still report honest `PEER_SCARCITY` — not "production panel exited scarcity".

## Changed / added files
```
src/vms/methods/rim/bank_peers.py          NEW builder + lean curated + funnel
src/vms/reporting/value_rim_bundle.py      auto-wire + rim_fi_peers artifact
src/vms/cli/main.py                        --no-auto-fi-peers
src/vms/assumptions.py / docs/assumptions.md
tests/unit/methods/test_rim_r3_bank_peers.py
tests/unit/methods/test_rim_r3_auto_fi_wiring.py
PHASE_R2E_FI_PEER_UNIVERSE_DONE.md
```

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `python -m pytest` | **723 passed** |
| Smoke | `vms value-rim ... --out /tmp/vms_000001_rim_r3` | R2a/b retained; R3 auto peers n=0 funnel MISSING_FINANCIALS×19; R2c PEER_SCARCITY; R2d UNAVAILABLE |

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Builder emits peers or empty + reasons/funnel | `build_fi_peer_observations`; `test_builder_emits_peers_and_funnel`, `test_thin_panel_empty_peers_with_funnel` |
| 2 | Leakage: future notice/price excluded | `test_leakage_future_notice_and_price_excluded` |
| 3 | Formula = raw_close / ((TE−MI−OEI)/shares) | `test_formula_pb_common_matches_te_mi_oei` |
| 4 | MISSING_OEI never TE-as-common (canonical `MISSING_OTHER_EQUITY_INSTRUMENTS`) | `test_missing_oei_never_uses_te_as_common` |
| 5 | 000001 smoke VALID **or** scarcity+funnel (builder ready; not claim panel exit) | smoke notes below |
| 6 | unsupported unchanged | no router/profile gate edits; `test_ac1_legacy_industry_unsupported_unchanged` + CLI |
| 9 | Auto FI subject gate + wiring | `test_rim_r3_auto_fi_wiring.py`; latest-PIT nonbank veto; peer cflags isolated |
| 7 | INVESTMENT_VALUE_NOT_ESTABLISHED | summary + artifacts |
| 8 | pytest green | see Commands |

## Smoke notes (000001.SZ @ 2025-06-30, Asia/Shanghai)
Local panel still thin (em_bank_f10 / classifications only subject; HiThink BS has TE for many banks but no OEI). R3 auto-build therefore emits **empty peers + MISSING_* funnel** → R2c remains **PEER_SCARCITY** (honest). Subject P/B/ROE still reported. R2a/b/d numbers unchanged vs R2cd.

## Known gaps (honest)
- Multi-bank OEI not yet in local panel → VALID peer set needs richer EM F10 / multi-instrument input (out of R3 data-plane scope beyond lean curated IDs).
- SCHEMA_VERSION remains `vms-0.2.phase12`.
- Walk-forward calibration / ensemble / gate lift / 非银金融 / Track B hist length out of scope.

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — engineering smoke ≠ investment advice.
