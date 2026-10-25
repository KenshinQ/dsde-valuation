# R6 — Bank RIM walk-forward calibration: DONE

Date: 2026-10-25 (Asia/Shanghai). Branch: `feat/r6-bank-rim-wf` (from `3d994ab` / R5 merge).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: `PHASE_R5_SUBJECT_HIST_DEPTH_DONE.md`. Pace: **r6-default** (user widget).

Status: **R6 acceptance criteria pass** (chronological WF + Track A forecast/score + Track B skip + CLI).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim `CALIBRATION_PASS`, `ENSEMBLE_CALIBRATED`, `INVESTMENT_VALUE_SUPPORTED`,
gate lift, 非银金融, schema bump, invent OEI, or lower `MIN_HIST_PB_POINTS` (=12).

## Design
- **Reuse Phase 11 protocol**: chronological-only (`RandomSplitProhibitedError`), freeze-before-test,
  forecast-before-outcome (`persisted_before_outcomes=true`, outcomes=null at first write),
  `CALIBRATION_INSUFFICIENT` on thin / no-predeclared-OOS path.
- **New path** (does not replace synthetic `vms phase11`):
  - Universe: `config/universe.fi_deposit_lean.yaml` (lean curated subset incl. **000001.SZ**)
  - Offline `bank_synthetic` panel (`evaluation/bank_panel.py`); 000001 short OEI → Track B SKIP
  - Track A adapter (`evaluation/rim_forecast.py`): driver ROE + RIM VPS + FI baselines
  - Outcomes (`evaluation/rim_outcomes.py`): realized ROE + later-origin VPS stability + market association
  - Scorer (`evaluation/rim_metrics.py`): separate targets; `price_mae_forbidden`
  - Orchestrator (`evaluation/rim_run.py`) + bundle (`reporting/calibrate_rim_bundle.py`)
  - CLI: `vms calibrate-rim`
- **Assumption**: `EVAL-RIM-BANK-WF-v1`
- Legacy `industry.unsupported` / `vms value|project` gate **untouched**. SCHEMA remains `vms-0.2.phase12`.

## Changed / added files
```
src/vms/evaluation/bank_panel.py              NEW synthetic FI panel (short OEI for 000001)
src/vms/evaluation/rim_forecast.py            NEW Track A + FI baselines + Track B eligibility
src/vms/evaluation/rim_outcomes.py            NEW driver/intrinsic/market outcomes
src/vms/evaluation/rim_metrics.py             NEW separate-target scores + Track B skip ledger
src/vms/evaluation/rim_run.py                 NEW walk-forward orchestrator
src/vms/evaluation/universe.py                bank_synthetic materialize
src/vms/evaluation/__init__.py                export run_rim_calibration
src/vms/reporting/calibrate_rim_bundle.py     NEW offline emitter
src/vms/cli/main.py                           `vms calibrate-rim`
src/vms/assumptions.py / docs/assumptions.md  EVAL-RIM-BANK-WF-v1
docs/calibration_protocol.md                  Bank RIM R6 section
config/universe.fi_deposit_lean.yaml          NEW lean curated universe
tests/unit/test_r6_rim_calibration.py         NEW AC1–AC12
tests/integration/test_cli_calibrate_rim.py   NEW CLI smoke
PHASE_R6_BANK_RIM_WF_DONE.md
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Chronological only; random → RandomSplitProhibitedError | `test_ac1_chronological_only_rejects_random` |
| 2 | Forecast persisted_before_outcomes=true, outcomes=null at first write | `test_ac2_*`; `_persist_forecast` assert |
| 3 | evaluation_targets_declared = driver_roe / intrinsic_value / market_price | `test_ac3_separate_evaluation_targets` |
| 4 | No price_mae as IV truth (EVAL-IV-NOT-PRICE-TRUTH-v1) | `test_ac4_future_price_not_intrinsic_truth` |
| 5 | Freeze before test; mutation fails closed | `test_ac5_freeze_before_test_mutation_fails` |
| 6 | Insufficient → CALIBRATION_INSUFFICIENT; no silent PASS | `test_ac6_*`; bundle guard |
| 7 | INVESTMENT_VALUE_NOT_ESTABLISHED | `test_ac7_*`; summary |
| 8 | MIN=12; no invent OEI; Track B&lt;12 skip | `test_ac8_*`; `MIN_HIST_PB_POINTS` |
| 9 | Legacy unsupported / 非银金融 unchanged | `test_ac9_legacy_unsupported_profile_config_untouched` |
| 10 | Declared universe incl. 000001; Track B skip visible | `test_ac10_*`; CLI smoke |
| 11 | pit_complete=false excluded from scores_unbiased | `test_ac11_*` |
| 12 | Tests green + PHASE_R6 + SCHEMA not claiming PASS | this file; `test_ac12_*` |

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `python -m pytest tests/unit/test_r6_rim_calibration.py tests/integration/test_cli_calibrate_rim.py` | **16 passed** |
| CLI | `vms calibrate-rim --out /tmp/vms_r6 --universe config/universe.fi_deposit_lean.yaml` | `CALIBRATION_INSUFFICIENT`; Track B skips; `INVESTMENT_VALUE_NOT_ESTABLISHED` |

## Known gaps (honest)
- Real A-share long-history OOS on live HiThink panel is **not** claimed (offline `bank_synthetic` proves protocol).
- `CALIBRATION_PASS` / `ENSEMBLE_CALIBRATED` intentionally **not** emitted on R6-default.
- SCHEMA_VERSION remains `vms-0.2.phase12` (no bump to claim PASS).
- Banks with OEI &lt; 12 FY cannot open Track B without inventing OEI (forbidden) or lowering MIN (forbidden).
- Non-bank / 非银金融 still out of scope.

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — engineering walk-forward ≠ investment advice.
