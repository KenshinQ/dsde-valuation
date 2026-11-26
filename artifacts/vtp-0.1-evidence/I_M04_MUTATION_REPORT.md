# I-M04 mutation: distribution mixture collapsed to the mean — KILLED

- Date: 2026-11-27 Asia/Shanghai (CST, UTC+8)
- Branch: `cursor/vtp-0.1-evidence-11d5` (evidence only; production file restored)
- This is backlog item 7 only. Items 8+ were not started.
- Repo remains `ENGINEERING_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`. Even 6/6 executed KILLED does not lift Suite G, Suite J, or the production routing matrix.

## Search (why this symbol)

Prior executors recorded I-M04 as `NOT_EXECUTED` against `src/vms/drivers/distributions.py` (“no clear single-line mutation point”). The Suite I harness already named the intended detector:

`tests/unit/test_distributions.py::test_mixture_quantiles_match_t_for_single_component`

Candidates reviewed this round (production code only, no toy router):

| Location | Role | Why chosen / not chosen |
|----------|------|-------------------------|
| `src/vms/drivers/distributions.py` `t_mix_quantiles` (lines 162–173) | Quantiles of a regime-conditional **student-t mixture** `Σ w_s t(loc_s, scale_s)`; used by `fit_specs` for `regime_t`. Replacing the mixture CDF with the weight-averaged location is exactly “mixture → mean”. The named detector calls this function directly. | **Executed.** |
| `src/vms/ensemble/mixture.py` `mix_distributions` | Ensemble `P(V)=Σ w_m P_m`; docstring: never on averaged point estimates alone (SPEC §22.3). | Real production mixture, but existing ensemble tests only check weights / ineligible methods and would not reliably KILL a flatten-to-mean mutant. I-M04’s designated detector is the driver-side test above. Not used as the patch target this round. |
| `src/vms/sampling/simulate.py` `_categorical` | Samples a discrete regime **state** on a path. | Not a distribution-mixture-to-mean collapse. |

No production logic was changed to accommodate tests. No new detector PR was required: the existing named test hits this symbol.

## Mutation

- File: `src/vms/drivers/distributions.py`
- Symbol: `t_mix_quantiles`
- Semantic fault: return the mixture mean of component locations `Σ w_m loc_m` for every requested quantile, ignoring scale and the mixture CDF.
- No inline comments. Single function, one semantic point.
- Full unified diff: `I_M04_unified_diff.patch`

```
-    q = np.asarray(qs, dtype=float)
-    lo = np.full_like(q, min(m - 60 * sc for _, m, sc in comps))
-    hi = np.full_like(q, max(m + 60 * sc for _, m, sc in comps))
-    for _ in range(80):
-        mid = (lo + hi) / 2
-        c = sum(w * stats.t.cdf((mid - m) / sc, df) for w, m, sc in comps)
-        below = c < q
-        lo = np.where(below, mid, lo)
-        hi = np.where(below, hi, mid)
-    return [float(v) for v in (lo + hi) / 2]
+    mu = sum(w * m for w, m, _ in comps)
+    return [float(mu) for _ in qs]
```

## SHA256 (full)

| State | SHA256 of `src/vms/drivers/distributions.py` |
|-------|-----------------------------------------------|
| Baseline / restored | `e8d557dfc26560ff228a993e73d61f29c34a657468389a89f5dcdcc390004dd8` |
| Mutant | `d0a4356244332e50a5064bc2d8b5060ccd9f730df113d42734d882722004ac47` |

## Command

```bash
/workspace/dsde-valuation/.venv/bin/python -m pytest \
  tests/unit/test_distributions.py::test_mixture_quantiles_match_t_for_single_component \
  tests/unit/test_distributions.py::test_regime_conditional_only_with_support \
  tests/unit/test_distributions.py::test_quantiles_within_bounds_and_monotone_for_every_driver \
  -v --tb=short
```

Python 3.13.5 / pytest 9.2.0. The third nodeid is parametrized over 18 drivers, so pytest collected **20** items. Full stdout/stderr are stored separately (not truncated).

## Results

| Run | Exit | Items | Outcome | Time |
|-----|------|-------|---------|------|
| Baseline | 0 | 20 collected, 20 passed | green | 0.40s |
| Mutant | 1 | 20 collected, 1 failed / 19 passed | expected detector assertion | 0.22s |
| After restore | 0 | 20 collected, 20 passed | SHA matches baseline | 0.40s |

**Classification: KILLED**, not ERROR. Collection succeeded; not timeout / import / syntax / collection failure. The failing assertion is a plain `AssertionError` from `pytest.approx`.

Kill (designed detector):

`tests/unit/test_distributions.py::test_mixture_quantiles_match_t_for_single_component`

Obtained `[0.3, 0.3, 0.3]` (the single-component location) instead of the t quantiles `0.3 + 0.2 * t.ppf(p, 4)` for p in (0.1, 0.5, 0.9). The 0.5 quantile happens to match the mean; 0.1 and 0.9 do not.

Honest non-kills under the same mutant (19 passed):

- `test_regime_conditional_only_with_support` only compares the **median** (`quantiles_z["0.5"]`) of `regime_t` vs `pooled_t`. Collapsing all quantiles to the mixture mean of locations can still leave that median below the pooled location when DETERIORATING has more mass. Not claimed as an extra kill.
- `test_quantiles_within_bounds_and_monotone_for_every_driver` (18 cases): equal quantiles remain sorted and inside bounds. Not claimed as extra kills.

## Restoration

The production file was restored immediately after the mutant run. SHA256 equals the baseline. A post-restore rerun of the same command was 20 passed, exit 0. This PR does not contain any `src/vms` change.

## Sidecars

- `I_M04_unified_diff.patch`
- `I_M04_baseline_stdout.txt` / `I_M04_baseline_stderr.txt`
- `I_M04_mutated_stdout.txt` / `I_M04_mutated_stderr.txt`
- `I_M04_restored_stdout.txt` / `I_M04_restored_stderr.txt`
- `I_M04_baseline_sha256.txt`, `I_M04_mutant_sha256.txt`, `I_M04_restored_sha256.txt`

Authoritative machine record: `mutation_results_FINAL.json` (I-M04 entry + summary executed=6, killed=6, not_executed=0). This is now 6/6 executed KILLED. It still does not authorize `ENGINEERING_ACCEPTED` or investment value.
