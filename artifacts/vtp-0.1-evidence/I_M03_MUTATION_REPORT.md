# VTP-0.1 I-M03 Mutation Execution Report

**Date**: 2026-11-27 Asia/Shanghai (CST, UTC+8)  
**Machine**: local Linux box (`/workspace/dsde-valuation`)  
**Branch / PR**: `cursor/vtp-0.1-evidence-11d5` / [#33](https://github.com/KenshinQ/dsde-valuation/pull/33)  
**Parent evidence head at execution**: `86d32fdfb6817d7c6b73cf97a556ab02458b5334`  
**Evidence commit (evidence_head)**: `b4b3ec54e7d2ef5afc592ee839d7f33a97e7cd7d`  
**Result**: **KILLED**  
**Release**: still `ENGINEERING_BLOCKED` / `RELEASE_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`  
**Counts after this run**: executed=4, killed=4, survived=0, not_executed=2 (I-M04, I-M06). Not 6/6.

This report does not change production logic. The temporary patch was restored before this file was written.

---

## 1. Symbol location

I-M03 asks whether the production PIT cutoff can include observations after as-of. Default as-of availability time is announcement / NOTICE_DATE, not `period_end`.

Search scope (production `src/vms`, plus existing leakage tests):

- `src/vms/pit/snapshot.py` — `build_snapshot()` is the production snapshot builder. `vms.quality.report.assess()` calls it.
- Financial known-at filter, line 391:
  `fin_k = [o for o in fin_i if o.published_at <= as_of]`
- Adjacent (not mutated, single-point discipline): market `timestamp <= as_of` (line 392), corporate actions `announced_at <= as_of` (line 393), peers `peer_known_at` (line 394, also `published_at > as_of` at line 339), classifications `published_at <= as_of` (line 401).
- `src/vms/pit/asof.py` — date-only as-of is 15:00:00 Asia/Shanghai (`ASOF-DATE-CLOSE-v1`). Not the cutoff predicate itself.
- Ingest path (not mutated): `src/vms/providers/hithink/pit.py` and `notice_to_published_at()` map Eastmoney `NOTICE_DATE` onto `FinancialObservation.published_at` (`HITHINK-PIT-NOTICE-v1`). Forbidden: using HiThink `period_end_ms` as `published_at`. Once loaded, the snapshot cutoff reads `published_at`.

Leakage detectors already hit this symbol via `assess()` → `build_snapshot()`:

- `tests/leakage/test_leakage.py::test_snapshot_invariant_to_information_after_as_of`
- `tests/leakage/test_leakage.py::test_every_snapshot_input_known_at_as_of` (`assert f.published_at <= as_of`)
- `tests/leakage/test_leakage.py::test_future_publication_excluded_late_annual_report` (`LATE_PERIOD=2023-12-31` is published `2024-06-20 18:00`, so a 2024-05-15 as-of must exclude it; a `period_end` cutoff would have leaked it)
- `tests/leakage/test_leakage.py::test_date_only_as_of_excludes_evening_publication_same_day`
- `tests/leakage/test_leakage.py::test_future_restatement_excluded`
- `tests/leakage/test_leakage.py::test_injected_future_restatement_of_old_period_does_not_change_old_snapshot`

Earlier executor status `NOT_EXECUTED` / “PIT cutoff complex; risk breaking leakage tests” is superseded. The leakage tests are the detectors.

## 2. Single-point mutation (no inline comments, no toy runner)

```
--- a/src/vms/pit/snapshot.py
+++ b/src/vms/pit/snapshot.py
@@ -388,7 +388,7 @@
     mkt_i = [o for o in market if o.instrument_id == instrument_id]
     ca_i = [e for e in corporate_actions if e.instrument_id == instrument_id]
     peer_i = [p for p in (peers or []) if p.subject_instrument_id == instrument_id]
-    fin_k = [o for o in fin_i if o.published_at <= as_of]
+    fin_k = list(fin_i)
     mkt_k = [o for o in mkt_i if o.timestamp <= as_of]
     ca_k = [e for e in ca_i if e.announced_at <= as_of]
     peer_k = [p for p in peer_i if peer_known_at(p, as_of)]
```

Meaning: financial observations for the instrument are kept even when `published_at` (NOTICE_DATE) is after as-of. Market / CA / peer cutoffs were left unchanged.

## 3. Commands and results

```bash
pytest tests/leakage/test_leakage.py -v --tb=short
```

Python 3.13.5, pytest 9.2.0, hypothesis 6.170.17. Command was identical for baseline and mutant.

| Stage | SHA256 of `src/vms/pit/snapshot.py` | Exit | Result |
|-------|--------------------------------------|------|--------|
| Baseline (pre-patch) | `4d15a203af621ab5572a8d2b6fd73c8f7aeb5893182bffb5ba2dbf69afb3c534` | 0 | 12 passed in 0.79s |
| Mutant | `1a0030bbd2d45709a5188af657ae209480aa4d69a85cb8e57b3db0255e72063b` | 1 | 6 failed, 6 passed, 2 warnings in 4.63s |
| Restored | `4d15a203af621ab5572a8d2b6fd73c8f7aeb5893182bffb5ba2dbf69afb3c534` | — | `git status` clean for this file; leakage re-run after restore: 12 passed |

Classification: **KILLED**, not ERROR. Collection succeeded (12 items). Failures are `AssertionError` on the expected leakage assertions. Not import / syntax / collection failure or timeout.

Failed under mutant (all `AssertionError`):

1. `test_snapshot_invariant_to_information_after_as_of` — full-dataset snapshot ≠ known-at-as-of subset.
2. `test_every_snapshot_input_known_at_as_of` — smoking gun: `published_at=2021-04-28 18:00+08:00` was not `<= as_of=2021-01-01 00:00+08:00`.
3. `test_future_publication_excluded_late_annual_report` — `LATE_PERIOD` (2023-12-31, published 2024-06-20 18:00) appeared in the 2024-05-15 snapshot.
4. `test_date_only_as_of_excludes_evening_publication_same_day` — 2023-04-28 18:00 revenue was visible at date-only as-of 2023-04-28 (interpreted as 15:00 close).
5. `test_future_restatement_excluded` — revision `r1` was visible before its publication (`r1 == r0` failed).
6. `test_injected_future_restatement_of_old_period_does_not_change_old_snapshot` — a 2025-01-01 restatement changed a 2023-01-15 snapshot.

The six passing tests under the mutant are market-price and corporate-action detectors. They do not exercise the financial `published_at` line that was patched. That is expected for a single-point mutation, not a sign of SURVIVED.

## 4. Restoration

The patch was applied only in a `try`/`finally` that wrote the original bytes back. Post-restore SHA256 matches the pre-patch digest above. `git status --short src/vms/pit/snapshot.py` was empty. Leakage tests were run again on the restored tree and passed. This evidence commit does not include any `src/vms` change.

## 5. Evidence paths

| Item | Path |
|------|------|
| Full baseline stdout | `artifacts/vtp-0.1-evidence/I_M03_baseline_stdout.txt` |
| Full mutant stdout | `artifacts/vtp-0.1-evidence/I_M03_mutated_stdout.txt` (complete; large because Hypothesis printed oversized reprs) |
| Unified diff | `artifacts/vtp-0.1-evidence/I_M03_unified_diff.patch` |
| Structured record | `artifacts/vtp-0.1-evidence/mutation_results_FINAL.json` (I-M03 object also embeds full stdout / stderr / SHA256 / diff) |
| Fail-closed verdicts | `artifacts/vtp-0.1-evidence/verdicts_final_failclosed.json` |

I-M02 full pytest stdout remains missing (previously recorded `evidence_gap`) and was not reconstructed in this round.

## 6. What this does not close

I-M04 and I-M06 remain `NOT_EXECUTED`. Suites E-01, G, J, and A-02 (PARTIAL) still block release. This run does not authorize `ENGINEERING_ACCEPTED`, `PASS`, or investment value.
