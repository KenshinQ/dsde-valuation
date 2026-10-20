# Phase 9 — Walk-forward evaluation: DONE

Not started: Phase 10 (DSDE adapter / release readiness).

## Decisions recorded
| ID | Decision |
|---|---|
| EVAL-CHRONOLOGICAL-ONLY-v1 | Only chronological origins; random splits raise RandomSplitProhibitedError |
| EVAL-FORECAST-BEFORE-OUTCOME-v1 | Persist forecasts with outcomes=null before realization |
| EVAL-TARGETS-SEPARATE-v1 | CF / intrinsic / price / TSR scored separately; IV not judged by price alone |
| EVAL-INVESTMENT-LABEL-v1 | Synthetic => INVESTMENT_VALUE_NOT_ESTABLISHED always |
| PIT-INCOMPLETE-v1 | Exclude pit_complete=false from unbiased metrics |

## Changed / new files
- `src/vms/evaluation/{protocol,baselines,outcomes,metrics,labels,universe,run,errors}.py`
- `config/universe.synthetic.yaml`
- `ValuationEngine.evaluate`; `vms evaluate --universe --start --end`
- assumptions + docs + CI
- Tests: `test_evaluation.py`, `test_cli_evaluate.py`

## Tests
- **453 passed** (~224 s box). Leakage **6/6 KILLED**; invariant **7/7 KILLED**. Clean-clone in verification commit.

## Acceptance evidence

1. **Random row-level splits prohibited.**
   - `test_refuse_random_splits` / CLI `--split-mode random` => exit 2 / RandomSplitProhibitedError.

2. **Forecasts persisted before outcomes.**
   - `persisted_before_outcomes: true`; first write has `outcomes: null`.

3. **Historical information sets reconstructed.**
   - `reconstruct_pit` / `assess` at each origin_as_of (past-only).

4. **Targets evaluated separately.**
   - `scores_unbiased` has distinct blocks; `intrinsic_value.price_mae_forbidden`.

5. **Baselines side-by-side.**
   - central_dcf, historical_median, no_regime, constant_growth_dcf, exit_multiple, dcf_only, dcf_plus_multiple.

6. **No unsupported alpha claim.**
   - Labels always `INVESTMENT_VALUE_NOT_ESTABLISHED` on SYNTHETIC (even if predeclared_oos_alpha=True).

Also: PIT_INCOMPLETE exclusion; ENGINEERING/DATA_QUALITY/CALIBRATION labels; `vms evaluate` artifacts.

## Limitations
1. Offline synthetic panel is annual (not full quarterly richness of demo SYN000001).
2. Point forecasts dominate; distributional CF quantiles optional/not filled by default.
3. Intrinsic stability vs later-origin VPS not yet backfilled (field reserved).
4. Calibration may be INCONCLUSIVE with few origins.
5. Demo smoke does not auto-run evaluate (use `vms evaluate`).

## New questions
1. Expand demo to call evaluate with a fixed window?
2. Persist distributional return forecasts at each origin (heavier)?
3. Formal CALIBRATION_PASS thresholds for production universes?
