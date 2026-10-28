# Phase pr13-sf1-warning-helper: DONE

Date: 2026-10-28 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/pr13-sf1-warning-helper`. Base: master @ `5e71897` (PR#17 merged).
SPEC: `/workspace/PR13_SF1_WARNING_HELPER_SPEC.md`. Pace: **pr13-sf1**.

Status: **AC CLOSED** (local branch + PR; merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | Nested ternary blocks for both warnings removed; helpers use flat `if/elif` | CLOSED |
| 2 | Emitted warning text identical on four paths (calibrate_rim / R10 live_samples / R9 live / R8 demo); test-pinned | CLOSED |
| 3 | Existing R8/R9/R10/R12 prior-only unit + relevant CLI tests green | CLOSED (local) |
| 4 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV label unchanged | CLOSED |
| 5 | PR against master; merge authority kenshin | CLOSED (PR opened; not merged) |

## Change summary

- **Production readability only**: extract `_ensemble_report_warning` and `_simulation_metadata_warning` in `prior_only_fi_bundle.py`; replace nested ternaries at ensemble_report / simulation_metadata call sites with flat-branch helpers (same style as assumption selection above).
- **Behavior / copy**: Y/N = **N** — warning strings byte-identical on four paths (identity-checked vs pre-refactor expression; pinned as literals in unit test).
- **Tests**: `tests/unit/test_pr13_sf1_warning_helper.py` pins full strings for four paths + R8 demo bundle wiring assert.

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`
- package `0.2.0rc1`
- `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift; no pit_complete / FULL_HISTORY chase
- No weight / ledger / adapter / SCHEMA / package / MIN / IV / ENSEMBLE_CALIBRATED flip

## Touch list

- `src/vms/reporting/prior_only_fi_bundle.py`
- `tests/unit/test_pr13_sf1_warning_helper.py`
- `PHASE_PR13_SF1_WARNING_HELPER_DONE.md`
