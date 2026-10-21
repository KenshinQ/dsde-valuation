# Phase 11 — Sensitivity, calibration and walk-forward evaluation: DONE (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE10_DONE.md](PHASE10_DONE.md).

Status: **all Phase 11 acceptance criteria pass** for PIT-safe chronological walk-forward,
forecast-before-outcome persistence, separate evaluation targets, baselines + subgroup
diagnostics, sensitivity report with §16.2 coverage notes, and release gates including
`CALIBRATION_INSUFFICIENT`. Label: `ENGINEERING_PASS` for Phase 11 engineering only;
**`INVESTMENT_VALUE_NOT_ESTABLISHED`**. **No** `INVESTMENT_VALUE_SUPPORTED`.
**No** `ENSEMBLE_CALIBRATED` on synthetic. This is **not** investment advice.
Phase 12 (docs / end-to-end release polish / five offline examples packaging) is **not**
claimed done.

## Changed / added files (VMS-0.2 Phase 11)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase11, PHASE_11
src/vms/assumptions.py                      EVAL-CALIBRATION-INSUFFICIENT / WEIGHTS-FROZEN /
                                            SUBGROUP-DIAGNOSTICS / IV-NOT-PRICE-TRUTH
src/vms/evaluation/labels.py                §17.4 release_gates + CALIBRATION_INSUFFICIENT
src/vms/evaluation/metrics.py               pinball, CRPS(gaussian), subgroups, baselines vs
src/vms/evaluation/baselines.py             current_multiple_persistence exit-price baseline
src/vms/evaluation/protocol.py              freeze_weights_before_test / assert_weights_unchanged
src/vms/evaluation/run.py                   EVAL-2 report; freeze before outcomes; release_gates
src/vms/evaluation/outcomes.py              Phase 11 override reason
src/vms/evaluation/__init__.py              exports freeze helpers
src/vms/evaluation/errors.py                SPEC §17.1 refs
src/vms/reporting/phase11_bundle.py         NEW: evaluation + sensitivity offline emitter
src/vms/cli/main.py                         `vms phase11`; evaluate metadata → Phase 11
config/*.yaml                               versions → phase11
tests/unit/test_phase11_acceptance.py       NEW (§20 AC1–AC6)
tests/leakage/test_eval_weight_freeze.py    NEW (§21.3 weight freeze / no price-as-IV-truth)
tests/property/test_eval_phase11_properties.py NEW
tests/integration/test_cli_phase11.py       NEW
docs/assumptions.md                         regenerated
PHASE11_DONE.md / README.md / tests/evaluation/README.md
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **661 passed** (Phase 10 was **641**; +20) |
| CLI | `vms phase11 --out /tmp/vms_phase11_smoke --seed 42 --paths 15 --years 3` | `PHASE11_WALK_FORWARD_CALIBRATION_NOT_INVESTMENT_ADVICE`; `CALIBRATION_INSUFFICIENT`; 8 forecasts persisted; both reports written |

## Acceptance criterion → evidence (§20 Phase 11 / §24)

| # | Criterion (SPEC §20 Phase 11) | Evidence |
|---|---|---|
| 1 | Historical forecasts are persisted before outcomes are read | `test_ac1_forecasts_persisted_before_outcomes`; forecast JSON has `persisted_before_outcomes=true` and `outcomes=null` at first write (`_persist_forecast` assert); `EVAL-FORECAST-BEFORE-OUTCOME-v1` |
| 2 | No random row-level time-series split is used | `test_ac2_no_random_row_split` / `test_ac2_run_evaluation_rejects_random`; `RandomSplitProhibitedError`; only `split_mode=chronological` allowed |
| 3 | Evaluation target stated separately for operating outcomes, cash flows, market prices and returns | `test_ac3_separate_evaluation_targets`; `scores_unbiased.evaluation_targets_declared` lists four families; `EVAL-TARGETS-SEPARATE-v1` |
| 4 | Future market price is not treated as ground truth for intrinsic value | `test_ac4_future_price_not_intrinsic_truth`; `price_mae_forbidden=true`; association labeled `MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH`; `EVAL-IV-NOT-PRICE-TRUTH-v1` |
| 5 | Calibration metrics compare against simple baselines and include profile/regime subgroup diagnostics | `test_ac5_baselines_and_subgroups`; baselines include `historical_median`, `central_dcf`, `no_regime`, `exit_multiple`, `current_multiple_persistence`; `scores_unbiased.subgroups.by_profile` / `by_fundamental_regime`; pinball/CRPS helpers |
| 6 | If data are inadequate, status is `CALIBRATION_INSUFFICIENT`, not an inferred success | `test_ac6_calibration_insufficient_not_inferred_success`; synthetic smoke → `CALIBRATION_INSUFFICIENT`; `release_gates` includes all §17.4 statuses; never `ENSEMBLE_CALIBRATED` / never `INVESTMENT_VALUE_SUPPORTED` on synthetic |

## Leakage (§21.3)
- Weights/thresholds frozen before test window: `frozen_weights.json` + `test_frozen_weights_hash_stable_across_scoring` / `test_mutating_weights_after_freeze_detected`.
- Forecast files carry `frozen_weights_hash`; mutation after freeze raises `ENSEMBLE_WEIGHTS_MUTATED_AFTER_FREEZE`.
- Intrinsic outcomes keep `realized_price_not_used_as_truth` (`test_no_future_price_in_forecast_payload`).
- Prior peer/regime PIT leakage suites remain green.

## Example artifact summary
```text
/tmp/vms_phase11_smoke/
  evaluation_report.json      # walk-forward scores + release_gates
  sensitivity_report.json     # OAT/joint + §16.2 coverage (implemented vs deferred)
  frozen_weights.json
  forecasts/...
  phase11_summary.json
  simulation_metadata.json
```

Release gates on synthetic smoke:
`ENGINEERING_PASS=true`, `DATA_QUALITY_PASS=true`, `CALIBRATION_PASS=false`,
`CALIBRATION_INSUFFICIENT=true`, `ENSEMBLE_CALIBRATED=false`,
`INVESTMENT_VALUE_NOT_ESTABLISHED=true`.

## Honest gaps (not claimed)
- Real A-share long-history OOS calibration / walk-forward is **not** claimed.
- `ENSEMBLE_CALIBRATED` is **not** emitted (no production OOS weight protocol).
- `INVESTMENT_VALUE_SUPPORTED` is **not** emitted (no predeclared alpha protocol).
- §16.2 deferred sensitivity dimensions (documented in `sensitivity_report.section_16_2_coverage.deferred`):
  WC detail beyond receivables, normalized-earnings alternate defs, full payout grid,
  debt/cash bridge shocks, dilution beyond share-growth, full profile-posterior resample,
  market-pricing-state transition grid, holding-company discount, NAV haircuts,
  calibrated ensemble-weight shocks.
- Distributional CF quantiles often absent on deterministic baselines → pinball/CRPS `n=0`
  until path distributions are attached at origins (helpers + wiring present).
- Phase 12 model cards / five offline packaged examples / schema migration suite: **pending**.

## §24 mapping
Small commits on `master`; SPEC §16–§17 / §20 Phase 11 / §21.3 / §22.4 authoritative;
engineering success ≠ investment alpha; synthetic label frozen as not established.
