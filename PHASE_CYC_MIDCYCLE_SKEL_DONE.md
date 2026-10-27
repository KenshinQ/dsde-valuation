# Phase cyc-midcycle-skel — skeleton mid-cycle estimator: DONE

Date: 2026-10-27 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/cyc-midcycle-skel`. Base: master @ `45b02fd` (post PR#15).
SPEC: `/workspace/CYCLICAL_MIDCYCLE_ENGINE_SPEC.md`. Pace: **cyc-midcycle-skel**.

Status: **AC1–AC6 CLOSED** on branch + PR; SF1–SF4 follow-up CLOSED (merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items (SPEC AC)

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | New estimator module + public fn; incomplete → None + low-conf diagnostics (no invent) | CLOSED — `src/vms/methods/multiples/midcycle.py` `estimate_mid_cycle_denominator` |
| 2 | Existing Phase5 cyclical trailing-without-midcycle test still passes | CLOSED — `test_cyclical_trailing_without_midcycle_flagged` |
| 3 | Synthetic complete-ish series → finite denom + documented diagnostic keys | CLOSED — `tests/unit/test_midcycle_skel.py` |
| 4 | Hook: absent/low-conf still flags; HIGH only under explicit completeness rules | CLOSED — wired in `common.py`; cyclical-only auto-call |
| 5 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV label unchanged | CLOSED |
| 6 | PR against master; merge authority kenshin | CLOSED (open; not merged) |

## Explicit HIGH rules (skeleton)

- `n_usable >= MIN_COMPLETE_POINTS` (7)
- dated span `>= MIN_COMPLETE_SPAN_YEARS` (6.0)
- peak_detected AND trough_detected (**skel proxy**: max > median and min < median; not a true cycle extrema / turning-point detector — almost always true when values are non-identical)
- `median > 0` required for HIGH (`NONPOSITIVE_MEDIAN` → LOW + denom None; hook also gates `denom>0`)
- Bad date strings drop the point and degrade (no `ValueError`); unparseable `as_of` → `ASOF_UNPARSEABLE`, PIT filter off
- Sector-prior stub never elevates above LOW; opt-in only (`use_sector_prior_stub`)

## Architecture SHOULD-FIX follow-up (PR#16 SF1–SF4)

| SF | Fix | Status |
|----|-----|--------|
| SF1 | HIGH path requires `med>0` + `NONPOSITIVE_MEDIAN` | CLOSED |
| SF2 | Bad date strings drop point / degrade (no throw) | CLOSED |
| SF3 | peak/trough marked skel proxy in DONE + assumption | CLOSED |
| SF4 | `_complete_series` median comment corrected (60 not 70) | CLOSED |

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`; package `0.2.0rc1`; `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift; no peak/base/trough scenario dist
- No Track B / `regimes/` confusion; no SCHEMA bump
- Full cycle model remains minimal (assumption cite additive)

## Touch list

- `src/vms/methods/multiples/midcycle.py` (NEW)
- `src/vms/methods/multiples/common.py` (cyclical-only wire into `assess_cycle_normalization`)
- `src/vms/methods/multiples/cycle.py` (docstring pointer)
- `src/vms/assumptions.py` + `docs/assumptions.md` (`CYCLE-MIDCYCLE-ESTIMATOR-SKEL-v1`)
- `tests/unit/test_midcycle_skel.py` (NEW)
- `PHASE_CYC_MIDCYCLE_SKEL_DONE.md`
