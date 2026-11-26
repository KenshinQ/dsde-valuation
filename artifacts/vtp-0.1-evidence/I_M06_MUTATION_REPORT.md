# VTP-0.1 I-M06 Mutation Execution Report

**Date**: 2026-11-27 Asia/Shanghai (CST, UTC+8)  
**Machine**: local Linux box (`/workspace/dsde-valuation`)  
**Branch / PR**: `cursor/vtp-0.1-evidence-11d5` / [#33](https://github.com/KenshinQ/dsde-valuation/pull/33)  
**Parent evidence head at execution**: `c686ae6fa03c05388486c56c7044fc7db479560b`  
**Result**: **KILLED**  
**Release**: still `ENGINEERING_BLOCKED` / `RELEASE_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`  
**Counts after this run**: executed=5, killed=5, survived=0, not_executed=1 (I-M04). Not 6/6.

This report does not change production logic. The temporary patch was restored before this file was written. No new detector tests were added; existing tests already hit the symbol.

---

## 1. Symbol location

I-M06 asks whether failed Monte Carlo paths can be silently discarded: they must be recorded, must not shrink the sample without a trace, and must not be treated as valid paths in statistics.

Search scope (production `src/vms` and existing detectors):

- `src/vms/sampling/simulate.py` — `simulate_paths()` is the production MC sampler. Each draw goes through `_one_path`. An `InvalidPathSummary` is appended to `invalid`; a valid `PathRecord` is appended to `valid`. Diagnostics use `n_paths_requested`, `n_paths_valid`, `n_paths_invalid`, and `invalid_fraction = len(invalid) / n_paths`. The production gate `INVALID-PATH-FRACTION-GATE-v1` (`max_invalid_path_fraction`, default 0.05 in `config/default.yaml`) raises `SamplingGateError` when the fraction is exceeded.
- The record site, lines 312–315:
  ```
  if isinstance(r, InvalidPathSummary):
      invalid.append(r)
  else:
      valid.append(r)
  ```
  Skipping `invalid.append` is a silent discard: the failed path is neither in `paths` nor in `invalid`, `n_paths_invalid` stays 0, and the fraction gate never fires.
- `_one_path` (`simulate.py:234–236`): `except Exception` already returns `InvalidPathSummary(reason="DEPENDENCE_DRAW_FAILED")`. It does not `continue` without a record. Not the silent-drop symbol.
- `src/vms/statements/paths.py` — earlier executor target (`NOT_EXECUTED`, “MC path error handling not located”). `project_financial_paths` already records failed *projection* paths in `failed` / `n_failed`, keeps them in `paths`, and excludes them from aggregates (`FAILED-PATHS-EXCLUDED-v1`). That is recorded exclusion, not silent discard. Sampling-layer invalids never enter this function because `SimulationBundle.paths` is already the valid list (invalids live in `bundle.invalid`).
- Framework note (`tests/vtp_0_1/suite_i/test_i_mutation_framework.py`) already pointed I-M06 at a silent filter of failed MC paths and named `tests/unit/test_phase4_followups.py::test_invalid_path_fraction_blocks_production` as the expected detector. File paths in that placeholder are stale; the live production symbol is `simulate.py`.

Detectors used:

- `tests/unit/test_phase4_followups.py::test_invalid_path_fraction_blocks_production` — monkeypatches `_one_path` so every path is `InvalidPathSummary`; production mode must raise `SamplingGateError`.
- `tests/unit/test_sampling.py::test_invalid_path_reasons_reported` — asserts `n_paths_valid + n_paths_invalid == 50` (may be vacuous if the seed yields zero invalids).
- `tests/unit/test_path_statements.py::test_failed_paths_never_enter_aggregates` — statement-layer aggregates; does not force sampling-layer invalids.

---

## 2. Single-point mutation (no inline comments, no toy runner)

```
--- a/src/vms/sampling/simulate.py
+++ b/src/vms/sampling/simulate.py
@@ -310,7 +310,7 @@
         r = _one_path(i, regimes=regimes, dist=distributions, years=years, states=states, chol=chol,
                       names=names, df=df, seed=seed, parameter_mode=parameter_mode)
         if isinstance(r, InvalidPathSummary):
-            invalid.append(r)
+            pass
         else:
             valid.append(r)
```

Meaning: a failed MC path is dropped without being recorded in `invalid`. Valid paths are unchanged.

---

## 3. Commands and results

```bash
pytest tests/unit/test_phase4_followups.py::test_invalid_path_fraction_blocks_production \
       tests/unit/test_sampling.py::test_invalid_path_reasons_reported \
       tests/unit/test_path_statements.py::test_failed_paths_never_enter_aggregates \
       -v --tb=short
```

Python 3.13.5, pytest 9.2.0. Command was identical for baseline and mutant.

| Stage | SHA256 of `src/vms/sampling/simulate.py` | Exit | Result |
|-------|-------------------------------------------|------|--------|
| Baseline (pre-patch) | `57bd06f4febfec6b762efea890cc65450ad6dbcd11ee7af563ceeca9d43cb40d` | 0 | 3 passed in 11.79s |
| Mutant | `fc0a0dd08bfea23ee1d083f2ef6aaf8beabedf7ebc0aa6ef1aecd838674d0a01` | 1 | 1 failed, 2 passed in 8.79s |
| Restored | `57bd06f4febfec6b762efea890cc65450ad6dbcd11ee7af563ceeca9d43cb40d` | — | `git status` clean for this file; detectors re-run after restore: 3 passed |

Classification: **KILLED**, not ERROR. Collection succeeded (3 items). The failing test is the designed detector: `pytest.raises(SamplingGateError, match="invalid path fraction")` reported `Failed: DID NOT RAISE SamplingGateError`. That is the test's intended assertion (a fail-closed gate that must fire when every path is invalid). It is not an import / syntax / collection failure or timeout. The exception class is pytest `Failed` from `pytest.raises`, not a raw `AssertionError`; it is still recorded as KILLED under the “expected detector assertion failed” rule, with this distinction stated explicitly.

Failed under mutant:

1. `test_invalid_path_fraction_blocks_production` — with all 20 paths forced invalid, `invalid` stayed empty, `invalid_fraction` was 0, and production mode did not raise `SamplingGateError`.

Passed under mutant (honest, not claimed as extra kills):

- `test_invalid_path_reasons_reported` — the equality `n_valid + n_invalid == 50` still holds when there are no invalids (50 + 0). Silent drop of an empty list is invisible.
- `test_failed_paths_never_enter_aggregates` — exercises `src/vms/statements/paths.py` aggregates, not `invalid.append`.

---

## 4. Restoration

The patch was applied only in a `try`/`finally` that wrote the original bytes back. Post-restore SHA256 matches the pre-patch digest above. `git status --short src/vms/sampling/simulate.py` was empty. The same detector command was run again on the restored tree and passed. This evidence commit does not include any `src/vms` change.

---

## 5. Evidence paths

| Item | Path |
|------|------|
| Full baseline stdout | `artifacts/vtp-0.1-evidence/I_M06_baseline_stdout.txt` |
| Full mutant stdout | `artifacts/vtp-0.1-evidence/I_M06_mutated_stdout.txt` |
| Unified diff | `artifacts/vtp-0.1-evidence/I_M06_unified_diff.patch` |
| Structured record | `artifacts/vtp-0.1-evidence/mutation_results_FINAL.json` (I-M06 object also embeds full stdout / stderr / SHA256 / diff) |
| Fail-closed verdicts | `artifacts/vtp-0.1-evidence/verdicts_final_failclosed.json` |

I-M02 full pytest stdout remains missing (previously recorded `evidence_gap`) and was not reconstructed in this round.

---

## 6. What this does not close

I-M04 remains `NOT_EXECUTED`. Suites E-01, G, J, and A-02 (PARTIAL) still block release. This run does not authorize `ENGINEERING_ACCEPTED`, `PASS`, or investment value.
