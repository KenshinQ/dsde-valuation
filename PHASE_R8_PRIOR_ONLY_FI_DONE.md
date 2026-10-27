# Phase R8 — FI PRIOR_ONLY research ensemble wiring: DONE

Date: 2026-10-25 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/r8-prior-only-fi`. Prior: [PHASE_R7_FI_REAL_OOS_DONE.md](PHASE_R7_FI_REAL_OOS_DONE.md),
[PHASE8_DONE.md](PHASE8_DONE.md).

Status: **R8 PRIOR_ONLY wiring accepted** for research path only.
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. **Not** investment advice.
**No** `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
Does **not** claim calibrated production ensemble. SCHEMA stays `vms-0.2.phase12`;
package `0.2.0rc1`.

## Scope
Wire deposit-taking FI / bank RIM method distributions into Phase 8
`build_ensemble(intent="research_prior")` so research PRIOR_ONLY mixture artifacts
can be produced from the FI world. Reuses `src/vms/ensemble/*`; does not replace
synthetic `vms phase8`.

## Changed / added files
```
src/vms/reporting/prior_only_fi_bundle.py   NEW: FI components + PRIOR_ONLY bundle
src/vms/cli/main.py                         prior-only-fi subcommand + guards
src/vms/assumptions.py                      ENSEMBLE-PRIOR-ONLY-FI-v1
docs/assumptions.md                         regenerated
docs/calibration_protocol.md                R8 section
tests/unit/test_r8_prior_only_fi.py         NEW: AC1–AC4
tests/integration/test_cli_prior_only_fi.py NEW: CLI smoke
PHASE_R8_PRIOR_ONLY_FI_DONE.md              this file
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | FI/PRIOR_ONLY path → research mixture; PRIOR_ONLY; calibrated_claim=false | `test_ac1_*`; summary fields |
| 2 | Same components production intent → mixture null | `test_ac2_*`; `production_refusal.mixture is null` |
| 3 | Incompatible bases refused; Track B hist_n&lt;12 not in weights | `test_ac3_*`; ledger SKIP |
| 4 | Forbidden labels locked; Track A required; schema/package unchanged | `test_ac4_*`; `MIN_HIST_PB_POINTS=12` |
| 5 | Docs + assumption id | `ENSEMBLE-PRIOR-ONLY-FI-v1`; calibration_protocol R8 |
| 6 | CLI smoke | `test_cli_prior_only_fi_track_b_skip_smoke` |

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `pytest tests/unit/test_r8_prior_only_fi.py tests/integration/test_cli_prior_only_fi.py` | see PR |
| Repo `.venv` | phase8 + r6/r7 regression subset | see PR |
| CLI | `vms prior-only-fi --out /tmp/vms_r8 --scenario track_b_skip` | PRIOR_ONLY mixture; Track B not in weights; `calibrated_claim=false` |

## Hard constraints honored
- Never emit `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`
- Production `intent=production` refuses mixture
- Track B &lt; MIN=12 → SKIP, not in weights (no invent OEI / no default PB)
- No lift of `industry.unsupported` / 非银金融
- calibrate-rim guards unchanged
- prefer_local / Recipe E path untouched (R7 B1)

## SHOULD-FIX follow-up (arch APPROVE on #8 @ d6b0556)
Applied on branch (this pass):
1. Injected `components=` path re-checks Track B `hist_n >= MIN_HIST_PB_POINTS` (`sanitize_injected_components`).
2. Runtime claim guard switched to **allow-list** (`ALLOWED_ENSEMBLE_STATUS` / `ALLOWED_CALIBRATION_STATUS` / `ALLOWED_INVESTMENT_VALUE`).
3. `test_ac4` hard-asserts status fields (not string deny-list).
4. `assumptions.py` indentation cleaned for `ENSEMBLE-PRIOR-ONLY-FI-v1` / `EVAL-RIM-FI-DEPOSIT-WF-v1`.
5. Live MethodDistribution adapter — **documented residual only** (below); not implemented here.

## Known gaps (honest)
- Default demos are **synthetic FI-shaped centers** (engineering wiring).
  **Live FI → MethodDistribution adapter** residual:
  - `value-rim` half → **CLOSED** by R9 (`PHASE_R9_LIVE_MD_ADAPTER_DONE.md`;
    R10/R11 samples/stride).
  - calibrate-rim forecast blob half → **CLOSED** by R12
    (`PHASE_R12_CALIBRATE_RIM_MD_DONE.md`). Research PRIOR_ONLY only — still
    **not** `ENSEMBLE_CALIBRATED`.
- Track B eligible path mixes exit-price channel on declared PER_SHARE basis for
  research disagreement only; still labeled PRIOR_ONLY / not IV truth
  (`EVAL-IV-NOT-PRICE-TRUTH-v1`).
- Production calibrated ensemble still blocked until real OOS + frozen weights
  satisfy §17.4 (`CALIBRATION_INSUFFICIENT` remains honest).

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — research PRIOR_ONLY wiring ≠ investment advice.
