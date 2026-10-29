# Phase cyc-midcycle-scenario-dist — peak/base/trough scenario dist (slice D): DONE

Date: 2026-10-29 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/cyc-midcycle-scenario-dist`. Base: master @ `41098f5` (post PR#25).
SPEC: `/workspace/CYCLICAL_MIDCYCLE_SCENARIO_DIST_SPEC.md`. Pace: **cyc-midcycle-scenario-dist**.

Status: **AC1–AC6 CLOSED** on branch + PR (merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items (SPEC AC)

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | Builder + types; equal-weight peak/base/trough when extrema+levels valid; else None (no invent) | CLOSED |
| 2 | Eligible estimates attach `diagnostics.scenario_distribution`; ineligible unchanged | CLOSED |
| 3 | Existing midcycle / Phase5 / emitter tests stay green | CLOSED |
| 4 | MD/diagnostics passthrough preserves nested scenario_distribution | CLOSED |
| 5 | Assumption `CYCLE-MIDCYCLE-SCENARIO-DIST-v1` documented; SCHEMA / package / MIN / IV unchanged | CLOSED |
| 6 | PR vs master; merge authority = kenshin | CLOSED (open; not merged) |

## Behavior

- `build_midcycle_scenario_distribution(est)` → `MidCycleScenarioDistribution | None`
- Gates: `peak_detected∧trough_detected`, finite peak/trough > 0, finite base > 0
  (`mid_cycle_denominator` else `median_value`), `peak ≥ base ≥ trough` (no reorder invent)
- Probabilities: `equal_weight_v1` = 1/3 each; always `research_only=True`
- Attach under `MidCycleEstimate.diagnostics["scenario_distribution"]` after estimate build
- **Not** fed into DCF / RIM / multiples valuation or ensemble mixture weights
- **Not** Phase5 inject / λ / HIGH gate change

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`; package `0.2.0rc1`; `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift
- No λ / HIGH gate / Phase5 inject / extrema window / sector-prior shrink math change

## Touch list

- `src/vms/methods/multiples/midcycle.py` (types + builder + attach)
- `src/vms/methods/multiples/__init__.py`
- `src/vms/assumptions.py` + `docs/assumptions.md`
- `tests/unit/test_midcycle_scenario_dist.py`
- `PHASE_CYC_MIDCYCLE_SCENARIO_DIST_DONE.md`
