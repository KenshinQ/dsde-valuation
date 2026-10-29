# Phase pr26-sf-hygiene: DONE

Date: 2026-10-30 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `chore/pr26-sf-hygiene`. Base: master @ `f0c7322` (PR#26 merged).
SPEC: `/workspace/PR26_SF_HYGIENE_SPEC.md`. Pace: **pr26-sf-hygiene**.
Source: `/workspace/agent-tools/pr26-review/VERDICT.md` SHOULD-FIX SF1–SF2.

Status: **AC CLOSED** (local branch + PR; merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | SF1: EMITTER assumption + docs use `FI / deposit-taking /` (no bare `bank` in that list) | CLOSED |
| 2 | SF2: order-invalid appends `SCENARIO_LEVEL_ORDER_INVALID`; no invent dist; unit test pins | CLOSED |
| 3 | Existing midcycle / emitter / Phase5 / scenario-dist / docs-sync tests green | CLOSED (local) |
| 4 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV unchanged | CLOSED |
| 5 | PR against master; merge authority kenshin | CLOSED (PR opened; not merged) |

## Change summary

- **SF1**: `CYCLE-MIDCYCLE-EMITTER-WIRING-v1` wording `FI / bank /` → `FI / deposit-taking /` in `assumptions.py` + regenerated `docs/assumptions.md` (align PR#24 hygiene). No midcycle sector conditionals; sector-lint exclusion rules untouched.
- **SF2**: `attach_scenario_distribution` appends `SCENARIO_LEVEL_ORDER_INVALID` to `diagnostics.reason_codes` when peak/base/trough levels are finite >0 but `peak≥base≥trough` fails; still returns no `scenario_distribution` / no invent reorder. Builder still returns `None`. Unit tests pin order-invalid + nonpos (no false reason).
- **Behavior**: Y/N = **N** for λ / HIGH / Phase5 inject / extrema / shrink / equal_weight math. Observability + docs hygiene only.

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`
- package `0.2.0rc1`
- `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- λ / HIGH gate / Phase5 `HIGH ∧ denom>0` inject
- extrema / sector-prior shrink / equal_weight_v1 = 1/3
- No DCF/RIM/ensemble feed; no invent OEI; no 非银 lift

## Touch list

- `src/vms/assumptions.py` (EMITTER FI/bank → FI/deposit-taking)
- `docs/assumptions.md` (regen)
- `src/vms/methods/multiples/midcycle.py` (`_scenario_levels_order_invalid` + attach reason)
- `tests/unit/test_midcycle_scenario_dist.py` (SF2 pins)
- `PHASE_PR26_SF_HYGIENE_DONE.md`

## Local verification

```text
.venv/bin/python -m pytest \
  tests/unit/test_midcycle_scenario_dist.py \
  tests/unit/test_midcycle_skel.py \
  tests/unit/test_midcycle_emitter_wiring.py \
  tests/unit/test_phase5_acceptance.py \
  tests/unit/test_docs_sync.py \
  tests/unit/test_profiles.py -q
```
