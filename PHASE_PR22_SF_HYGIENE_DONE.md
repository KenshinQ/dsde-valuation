# Phase pr22-sf-hygiene: DONE

Date: 2026-10-29 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `chore/pr22-sf-hygiene`. Base: master @ `1c50ad9` (PR#22 merged).
SPEC: `/workspace/PR22_SF_HYGIENE_SPEC.md`. Pace: **pr22-sf-hygiene**.
Source: `/workspace/agent-tools/pr22-review/VERDICT.md` SHOULD-FIX SF1–SF3.

Status: **AC CLOSED** (local branch + PR; merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | SF1: λ=0 incomplete (n≥MIN, no extrema) pinned; denom=m, LOW, research_only | CLOSED |
| 2 | SF2: Phase5 e2e asserts LOW shrink stays out of mid inject | CLOSED |
| 3 | SF3: module docstring no longer primary-describes path as bare “stub” | CLOSED |
| 4 | Existing midcycle + Phase5 trailing tests green | CLOSED (local) |
| 5 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV unchanged | CLOSED |
| 6 | PR against master; merge authority kenshin | CLOSED (PR opened; not merged) |

## Change summary

- **SF1**: `test_sector_prior_shrink_lambda_zero_n_ge_min_but_incomplete` — monotone 7-pt series + stub+prior=999 → λ=0, denom=sample median, LOW / research_only (not HIGH).
- **SF2**: `test_cyclical_low_shrink_denom_not_injected_into_mid` — cyclical + stub+prior+short series → shrink denom present at LOW but trailing used; no `MID_CYCLE_DENOMINATOR_USED`. common.py inject gate untouched.
- **SF3**: `midcycle.py` module docstring — “Optional sector-prior shrink (opt-in stub)…” replaces stale primary “stub” phrasing; L7–9 shrink wording kept consistent.
- **Behavior**: Y/N = **N** for λ / HIGH / Phase5 inject. Tests + docstring only (+ DONE).

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`
- package `0.2.0rc1`
- `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- λ formula / HIGH gate / Phase5 `HIGH ∧ denom>0` inject condition
- No emitter / scenario dist / λ calibration
- No invent OEI / default PB; no 非银 lift; no ENSEMBLE_CALIBRATED flip

## Touch list

- `src/vms/methods/multiples/midcycle.py` (module docstring only)
- `tests/unit/test_midcycle_skel.py` (SF1 unit pin)
- `tests/unit/test_phase5_acceptance.py` (SF2 Phase5 e2e)
- `PHASE_PR22_SF_HYGIENE_DONE.md`

## Local verification

```text
.venv/bin/python -m pytest tests/unit/test_midcycle_skel.py tests/unit/test_phase5_acceptance.py -q
→ 32 passed
```
