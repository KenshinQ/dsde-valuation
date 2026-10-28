# Phase cyc-midcycle-extrema — local extrema peak/trough HIGH gate: DONE

Date: 2026-10-28 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/cyc-midcycle-extrema`. Base: master @ `ffbfd76` (post PR#19).
SPEC: `/workspace/CYCLICAL_MIDCYCLE_EXTREMA_SPEC.md`. Pace: **cyc-midcycle-extrema**.

Status: **AC1–AC6 CLOSED** on branch + PR (merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items (SPEC AC)

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | Skel proxy (`max>med & min<med`) removed from HIGH path; local-extrema rule documented + coded | CLOSED — `_local_extrema_indices` window=1; `peak_trough_method=local_extrema_v1` |
| 2 | Monotone / flat / no local peak or trough → None + LOW + explicit reason (no invent) | CLOSED — `NO_LOCAL_PEAK` / `NO_LOCAL_TROUGH` |
| 3 | Synthetic complete series with real local peak+trough → finite denom + HIGH; diagnostics list extrema | CLOSED — `tests/unit/test_midcycle_skel.py` |
| 4 | Phase5 `test_cyclical_trailing_without_midcycle_flagged` + SF1 nonpositive median green | CLOSED |
| 5 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV label unchanged | CLOSED |
| 6 | PR against master; merge authority kenshin | CLOSED (open; not merged) |

## Explicit HIGH rules (this slice)

- `n_usable >= MIN_COMPLETE_POINTS` (7)
- dated span `>= MIN_COMPLETE_SPAN_YEARS` (6.0)
- ≥1 strict local peak AND ≥1 strict local trough (window=1 vs immediate neighbors; endpoints never count)
- `median > 0` required for HIGH (`NONPOSITIVE_MEDIAN` → LOW + denom None)
- Sector-prior stub unchanged (research-only / LOW; opt-in only)

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`; package `0.2.0rc1`; `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift
- No peak/base/trough scenario probabilities; no sector-prior shrink calibration
- No emitter / DCF / rim / MD fan-out; no Track B / `regimes/` confusion

## Non-goals (still backlog #4 later)

- Scenario distribution with probabilities
- Full sector-prior shrink
- Wiring into all multiples emitters / scenario DCF / rim_run / calibrate-rim / MethodDistribution

## Touch list

- `src/vms/methods/multiples/midcycle.py` (local extrema HIGH gate)
- `src/vms/assumptions.py` + `docs/assumptions.md` (`CYCLE-MIDCYCLE-EXTREMA-v1`; SKEL note bump)
- `tests/unit/test_midcycle_skel.py`
- `PHASE_CYC_MIDCYCLE_EXTREMA_DONE.md`
