# R1 — Real A-share FINANCIAL_INSTITUTION → RIM: DONE

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior: VMS-0.2 Phase 12 (`PHASE12_DONE.md`). Spec: `SPEC.md` (VMS-0.2) §12.4 + design A+C.

Status: **R1 acceptance criteria pass** for PITSnapshot → residual income bridge + `vms value-rim`.
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim OOS calibration, ensemble, returns, or P/B-ROE.

## Design
- **A+C (approved)**: bridge PIT → `rim_inputs` + thin CLI `vms value-rim`.
- **Reject B**: `industry.unsupported` unchanged; legacy `vms project` / `vms value` still `UNSUPPORTED_PROFILE` for 银行/非银金融.
- **NI P1**: constant last-FY `parent_net_income` for N years (ASSUMPTION).
- **CS**: missing OCI/net_issuance only with `zeros_explicit=true` → `CLEAN_SURPLUS_ZEROS_ASSUMED` (never silent).

## Changed / added files
```
src/vms/methods/rim/from_snapshot.py   NEW: features_from_snapshot + rim_inputs_from_snapshot
src/vms/methods/rim/__init__.py        export bridge symbols
src/vms/reporting/value_rim_bundle.py  NEW: build_value_rim_bundle + RUN_REPORT.md
src/vms/cli/main.py                    `vms value-rim`
src/vms/assumptions.py                 RIM-NI-CONSTANT-LAST-FY-v1, RIM-CS-ZEROS-EXPLICIT-v1, RIM-REAL-PIT-BRIDGE-v1
docs/assumptions.md                    regenerated
docs/method_registry.md / model_card.md / README.md  R1 notes
tests/unit/methods/test_rim_from_snapshot.py
tests/unit/test_r1_bank_rim_acceptance.py
tests/integration/test_cli_value_rim.py
PHASE_R1_BANK_RIM_DONE.md
```

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `python -m pytest` | **697 passed** (Phase 12 was **688**; +9) |
| Smoke | `vms value-rim --input /tmp/vms_000001 --ticker 000001.SZ --as-of 2025-06-30 --out /tmp/vms_000001_rim ...` | VALID; see RUN_REPORT |
| Legacy | `vms project` / `vms value` on same input | exit **4** UNSUPPORTED_PROFILE |

## Acceptance criterion → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Legacy project/value still UNSUPPORTED | `test_ac1_legacy_industry_unsupported_unchanged`; CLI exit 4 on 000001; `industry.unsupported` untouched |
| 2 | value-rim builds rim_inputs; TE rule | `BOOK_EQUITY_TE_RULE`; smoke book_equity_0=494842e6 @ FY2024 |
| 3 | Profile FINANCIAL_INSTITUTION (low_conf OK); not MATURE | smoke + `test_features_from_bank_snapshot_are_financial_not_mature` |
| 4 | residual_income eligible; fcff_dcf / ev_ebitda ineligible | route on FUNDAMENTAL + RELATIVE targets |
| 5 | CS zeros_explicit + CLEAN_SURPLUS_ZEROS_ASSUMED | bridge flags + method diagnostics; refuse silent zeros |
| 6 | VALID equity (+VPS); ev_bridge_applied=false; no ensemble | smoke equity≈4.936e11, VPS≈25.44 |
| 7 | Unit/integration green; RUN_REPORT | `/tmp/vms_000001_rim/RUN_REPORT.md` |
| 8 | Docs note engineering smoke / PIT / ASSUMPTIONs | this file + docs + RUN_REPORT |

## Smoke numbers (000001.SZ @ 2025-06-30)
- equity_value ≈ **4.936e11** CNY
- value_per_share ≈ **25.44**
- ke=0.08, g=0.03, years=5, NI=4.4508e10 constant
- spot close 12.07 — **not** intrinsic value

## Known gaps (honest)
- No live OCI / net_issuance / goodwill in canonical PIT fields.
- Industry-aux-only profile → low_confidence.
- No returns, ensemble, or P/B-ROE (deferred).
- ke/g from config WACC ASSUMPTIONs (not live PIT curve).
- SCHEMA_VERSION remains `vms-0.2.phase12` (R1 is a post-Phase-12 engineering slice).
