# Phase cyc-midcycle-sector-prior — sector-prior shrink (research-only LOW): DONE

Date: 2026-10-28 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/cyc-midcycle-sector-prior`. Base: master @ `eb860fe` (post PR#21).
SPEC: `/workspace/CYCLICAL_MIDCYCLE_SECTOR_PRIOR_SPEC.md`. Pace: **cyc-midcycle-sector-prior**.

Status: **AC1–AC6 CLOSED** on branch + PR (merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items (SPEC AC)

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | Incomplete + stub on + prior>0 + sample med>0 → blended denom, LOW, research_only, diagnostics expose λ | CLOSED — `_maybe_prior_or_low` shrink; `SECTOR_PRIOR_SHRINK_APPLIED` |
| 2 | Empty series + stub + prior → prior fill LOW (compat); never HIGH | CLOSED — `SECTOR_PRIOR_SHRINK_EMPTY_SERIES` |
| 3 | Complete HIGH path unchanged; prior does not upgrade confidence | CLOSED |
| 4 | Stub off / invalid prior / nonpositive sample med → no invent | CLOSED |
| 5 | Existing midcycle extrema + Phase5 trailing + SF hygiene tests green | CLOSED |
| 6 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV unchanged; PR vs master | CLOSED (open; not merged) |

## Shrink formula (deterministic)

When `use_sector_prior_stub` and `prior > 0` and incomplete and sample median `m > 0`:

- `λ = clip(1 - n_usable / MIN_COMPLETE_POINTS, 0, 1)` (`N_FULL = MIN_COMPLETE_POINTS = 7`)
- `denom = (1-λ)*m + λ*prior` (if denom ≤ 0 → None + LOW)
- Always `confidence=LOW`, `research_only=True`; diagnostics: `shrink_lambda`, `sample_median`, `sector_prior`

Empty + stub + prior → raw prior fill (compat). `m ≤ 0` / stub off / invalid prior → no invent.
HIGH path never applies prior.

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`; package `0.2.0rc1`; `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift
- No λ calibration / calibration-pass claim
- No emitter / DCF / rim / MD wiring (slice C); no scenario probabilities (slice D)
- Local-extrema HIGH gate unchanged (PR#20/#21)

## Non-goals (still backlog #4 later)

- C emitter wiring into multiples / DCF / rim_run / calibrate-rim / MethodDistribution
- D peak/base/trough scenario probabilities

## Touch list

- `src/vms/methods/multiples/midcycle.py` (shrink path)
- `src/vms/assumptions.py` + `docs/assumptions.md` (`CYCLE-MIDCYCLE-SECTOR-PRIOR-SHRINK-v1`; SKEL note)
- `tests/unit/test_midcycle_skel.py`
- `PHASE_CYC_MIDCYCLE_SECTOR_PRIOR_DONE.md`
