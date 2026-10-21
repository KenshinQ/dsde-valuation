# Calibration protocol (VMS-0.2)

Implements SPEC §17. Engineering metrics ≠ investment alpha.

## Walk-forward (required)

At each historical decision timestamp:

1. Reconstruct the PIT information set and contemporaneous peer universe.
2. Fit/update drivers, states, peers and parameters **only** on permitted past data.
3. **Persist forecasts before reading outcomes** (`persisted_before_outcomes=true`).
4. Evaluate only after the target horizon / accounting period matures.
5. Repeat chronologically. **No** random row-level time-series splits.

CLI: `vms evaluate` / `vms phase11`.

## Separate evaluation targets

Score independently (never conflate):

- operating / cash-flow forecasts;
- relative / peer multiple behavior;
- asset NAV inputs where later observable;
- **future market prices** (not intrinsic ground truth);
- total-return distributions and loss probabilities;
- ensemble calibration **only** for its predeclared target.

Future market price **must not** be treated as intrinsic-value ground truth (`EVAL-IV-NOT-PRICE-TRUTH-v1`).

## Baselines

Include where data allow: historical driver median; central-case DCF (eligible profiles); simple multiple; no-regime; current-multiple persistence (exit); profile-appropriate benchmarks. Document unavailable baselines.

## Release gates (SPEC §17.4)

A calibration method or ensemble is production-eligible only when:

- target predeclared;
- sufficient OOS data (or justified hierarchical pooling);
- metrics vs baselines with subgroup diagnostics;
- no material leakage;
- weights/hyperparameters frozen before the test window;
- subgroup instability reported.

Otherwise mark `CALIBRATION_INSUFFICIENT` and keep method-specific distributions.

| Status | Synthetic `0.2.0rc1` |
|---|---|
| `ENGINEERING_PASS` | Yes |
| `CALIBRATION_PASS` | No → `CALIBRATION_INSUFFICIENT` |
| `ENSEMBLE_CALIBRATED` | No |
| `INVESTMENT_VALUE_NOT_ESTABLISHED` | Yes |
| `INVESTMENT_VALUE_SUPPORTED` | **Forbidden** without separate OOS research protocol |

## Weight freeze

`freeze_weights_before_test` / `assert_weights_unchanged` — mutation after freeze fails closed (`ENSEMBLE_WEIGHTS_MUTATED_AFTER_FREEZE`).
