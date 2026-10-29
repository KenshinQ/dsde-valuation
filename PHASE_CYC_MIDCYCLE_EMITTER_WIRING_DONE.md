# Phase cyc-midcycle-emitter-wiring — diagnostics fan-out (slice C): DONE

Date: 2026-10-29 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/cyc-midcycle-emitter-wiring`. Base: master @ `d3d1963` (post PR#23).
SPEC: `/workspace/CYCLICAL_MIDCYCLE_EMITTER_WIRING_SPEC.md`. Pace: **cyc-midcycle-emitter-wiring**.

Status: **AC1–AC7 CLOSED** on branch + PR (merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items (SPEC AC)

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | Shared `resolve_cyclical_midcycle` + `injectable_mid_denominator`; multiples/common refactors with zero behavior delta | CLOSED |
| 2 | Phase5 cyclical writes honest `midcycle_estimate.json`; non-cyclical omits artifact | CLOSED |
| 3 | Phase12 cyclical diagnostics expose `midcycle_estimate` (honest None+LOW ok) | CLOSED |
| 4 | Cash-flow cyclical: diagnostics only via `with_midcycle_diagnostics`; point values unchanged | CLOSED |
| 5 | RIM non-FI cyclical: diagnostics only; FI / value-rim / calibrate-rim: explicit no-op (no invent) | CLOSED |
| 6 | MD passthrough preserves `midcycle_estimate` when present on source | CLOSED |
| 7 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV unchanged; PR vs master | CLOSED (open; not merged) |

## Behavior

- **Valuation inject** of `mid_cycle_denominator` remains **multiples-only** (`HIGH ∧ denom>0` via `injectable_mid_denominator`). Unchanged gate.
- Emitters / DCF / non-FI RIM / MD: **diagnostics provenance only**.
- FI / deposit-taking / value-rim / calibrate-rim PRIOR_ONLY: **explicit no-op** (wrong domain for industrial mid-cycle earnings denom).
- Assumption: `CYCLE-MIDCYCLE-EMITTER-WIRING-v1`.

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`; package `0.2.0rc1`; `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift
- No λ / HIGH gate / Phase5 inject condition change
- Scenario peak/base/trough probabilities: see CYCLE-MIDCYCLE-SCENARIO-DIST-v1 / PHASE_CYC_MIDCYCLE_SCENARIO_DIST_DONE.md (research-only; not valuation inject)

## Non-goals (still backlog #4 later)

- D peak/base/trough scenario probabilities — landed as CYCLE-MIDCYCLE-SCENARIO-DIST-v1 (research-only)

## Touch list

- `src/vms/methods/multiples/midcycle.py` (resolve / inject / passthrough helpers)
- `src/vms/methods/multiples/common.py` (refactor onto helpers; zero delta)
- `src/vms/methods/multiples/__init__.py`
- `src/vms/methods/cash_flow/common.py` + `fcff_plugin.py` / `fcfe_plugin.py` / `ddm_plugin.py`
- `src/vms/methods/rim/plugin.py` (FI skip)
- `src/vms/reporting/phase5_bundle.py` / `phase12_bundle.py`
- `src/vms/ensemble/mixture.py` + `__init__.py` (MD passthrough)
- `src/vms/assumptions.py` + `docs/assumptions.md`
- `tests/unit/test_midcycle_emitter_wiring.py`
- `PHASE_CYC_MIDCYCLE_EMITTER_WIRING_DONE.md`
