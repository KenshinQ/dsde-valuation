# Phase 8 — Sensitivity & uncertainty attribution: DONE

Not started: Phase 9 (walk-forward historical evaluation).

## Decisions recorded
| ID | Decision |
|---|---|
| SENS-OAT-ISOLATION-v1 | OAT shocks alter only the named input; isolation_check on frozen paths |
| SENS-MC-PERCENTILE-NOT-CI-v1 | MC p05/p95 = percentile intervals, never labeled as CIs |
| SENS-PROCESS-VS-PARAM-v1 | parameter_mode fixed vs resampled comparison |
| SENS-DRIVER-ABLATION-v1 | Pathwise ablation to central year-1 (not Shapley) |

## Changed / new files
- `src/vms/diagnostics/{metrics,perturb,sensitivity}.py` — report orchestration
- `src/vms/sampling/simulate.py` — `parameter_mode` fixed|resampled
- `src/vms/schemas/config.py` + `config/default.yaml` — SensitivityConfig
- `src/vms/engine.py` — `run_diagnostics`
- `src/vms/cli/main.py` — `vms sensitivity --run-dir/--run-id`; demo writes sensitivity_report.json
- assumptions + docs + CI
- Tests: `test_diagnostics.py`, `test_cli_sensitivity.py`

## Tests
- **444 passed** (~223 s box). Leakage 6/6; invariant 7/7. Clean-clone in verification commit.

## Acceptance evidence

1. **OAT alters only intended inputs.**
   - `test_oat_isolation_only_intended_driver`; report `isolation_check.pass` for all pathwise OAT cases.

2. **Dominant valuation assumptions identified.**
   - `dominant_assumptions` ranked by |Δ mean_vps_dcf| (and tracks |Δ p_loss|, Δ CVaR).

3. **Tail-risk sensitivity included.**
   - Each case reports return `p_loss` / `cvar_0.95` deltas; flag `TAIL_RISK_SENSITIVITY_INCLUDED`.

4. **Percentile ranges not mislabeled as CIs.**
   - `interval_labeling.rule = MC_PERCENTILE_NOT_CI`; bands carry `kind=monte_carlo_percentile_interval` + `not_a_confidence_interval`.

5. **Reports reproduce from saved artifacts.**
   - Same seed/config/baseline → same `content_hash` (`test_reproducible_content_hash`, CLI twice).

Also covered: joint scenarios; DCF vs multiple; TV contribution; process vs param; driver ablation; CLI `vms sensitivity`.

## Limitations
1. Sensitivity re-runs use exploratory central-path override; production gates not re-applied per case.
2. Driver attribution is simple ablation (documented), not Shapley.
3. Posterior/transition OATs re-simulate (process noise re-drawn with same seed).
4. Demo/CI sensitivity uses reduced path counts for runtime.
5. Suite ~3.7 min.

## New questions
1. Persist per-case path parquets for audit, or summary-only?
2. Formal bootstrap CIs for selected scalars in Phase 9+?
3. Default sensitivity path count vs valuation path count coupling?
