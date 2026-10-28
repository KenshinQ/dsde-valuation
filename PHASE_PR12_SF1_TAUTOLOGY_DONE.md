# Phase pr12-sf1-tautology: DONE

Date: 2026-10-28 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/pr12-sf1-tautology`. Base: master @ `0db0e4d` (PR#16 merged).
SPEC: `/workspace/PR12_SF1_TAUTOLOGY_SPEC.md`. Pace: **pr12-sf1**.

Status: **AC CLOSED** (local branch + PR; merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | Tautology `reason != HIST_PB_BELOW_MIN or instrument_id` removed from CLI golden | CLOSED |
| 2 | New asserts fail on NOT_ASSESSED-shaped / fabricated HIST row (unit sibling injects; CLI cannot) | CLOSED |
| 3 | `test_track_b_ledger_only_counts_skip_status` + CLI golden AC5–AC7 green | CLOSED |
| 4 | SCHEMA / package / MIN / IV unchanged | CLOSED |
| 5 | PR against master; merge authority kenshin | CLOSED (PR opened; not merged) |

## Change summary

- **CLI golden** (`tests/integration/test_cli_calibrate_rim.py` AC5): replace noop with meaningful anti-disguise — non-empty `skip_reason` ≠ `NOT_ASSESSED`; if `status` present must be `SKIP`; `instrument_id` present; `hist_n` / `min_required` present with `hist_n < min_required`. Applied to both `rep["track_b_skips"]` and `tb["skips"]`.
- **Unit** (`tests/unit/test_r6_rim_calibration.py`): shared `_assert_track_b_skips_anti_disguise` on honest ledger; sibling `test_track_b_skips_anti_disguise_rejects_not_assessed_row` proves fabricated NOT_ASSESSED / literal reason fail.
- **Production emission**: unchanged (Y/N = **N**) — meaningful asserts pass on current `rim_run` / `rim_metrics` SKIP-only ledger.

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`
- package `0.2.0rc1`
- `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift; no pit_complete / FULL_HISTORY chase
- No SCHEMA / package / MIN / IV / ENSEMBLE_CALIBRATED flip

## Touch list

- `tests/integration/test_cli_calibrate_rim.py`
- `tests/unit/test_r6_rim_calibration.py`
- `PHASE_PR12_SF1_TAUTOLOGY_DONE.md`
