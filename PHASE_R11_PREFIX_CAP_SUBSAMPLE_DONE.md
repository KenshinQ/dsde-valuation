# Phase R11 — Prefix-cap → deterministic stride subsample: DONE

Date: 2026-10-26 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/prefix-cap-subsample`. Prior: [PHASE_R10_LIVE_SAMPLES_DONE.md](PHASE_R10_LIVE_SAMPLES_DONE.md).
Spec: in-repo — this PHASE + `docs/calibration_protocol.md` R11 section + assumption `ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1` (deterministic stride subsample; replaces path-order prefix).

Status: **R10 Prefix-cap known gap CLOSED** by deterministic stride subsample.
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. **Not** investment advice.
**No** `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
SCHEMA stays `vms-0.2.phase12`; package `0.2.0rc1`.
SF4 CLOSED-by-replacement (path-order prefix → stride index formula).

## Scope
Replace path-order prefix `[:LIVE_SAMPLE_CAP]` on persisted live samples with
deterministic systematic stride indices. Full-set percentiles unchanged.
Track A and Track B share one policy; Track B collects all finite-positive
before cap (no early-break prefix).

## Changed / added files
```
src/vms/methods/rim/distribution.py     subsample_cap / stride_cap_indices; cite STRIDE-CAP
src/vms/methods/rim/track_b_exit.py     collect-all then subsample_cap; cite STRIDE-CAP
src/vms/assumptions.py                  ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1
docs/assumptions.md                     regenerated
docs/calibration_protocol.md            R10 gap CLOSED + R11 section
tests/unit/test_prefix_cap_subsample.py NEW: AC1–AC4 pure + integration
tests/unit/test_r10_live_samples.py     SF4 → AC2 stride; producer cite STRIDE-CAP
PHASE_R10_LIVE_SAMPLES_DONE.md          Prefix-cap → CLOSED pointer
PHASE_R11_PREFIX_CAP_SUBSAMPLE_DONE.md  this file
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | n_valid ≤ CAP → all finite-positive retained | `test_ac1_*` / pure subsample |
| 2 | n_valid > CAP → len==CAP; indices = stride formula (+fill) | `test_ac2_*` (SF4 replacement) |
| 3 | Full-set percentiles unchanged | `test_ac3_*` |
| 4 | Deterministic (no RNG drift) | `test_ac4_*` |
| 5 | PRIOR_ONLY live_paths / R9 compat / no calibrated labels | R10 `test_ac1/ac2/ac5` |
| 6 | Track B hist_n&lt;12 / no PER_SHARE SKIP | R10 `test_ac4_*` |
| 7 | Docs/assumption STRIDE-CAP; prefix-cap CLOSED; ≠ coverage | this file + protocol + cite tests |

## Hard constraints honored
- Never emit `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`
- Cap default 96; no uncapped dumps; no percentile overwrite
- No pb_common ROE bank; no MIN=12 change; no 非银 lift
- Adapter read semantics unchanged
- pit_complete not forced

## Known gaps (honest)
- pb_common still point-expanded when only `relative_vps` exists
- Production calibrated ensemble still blocked (`CALIBRATION_INSUFFICIENT`)
- Adapter remains read-only over out-dir
- Subsample ≠ calibration coverage / investment advice

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — stride-capped live samples ≠ investment advice ≠ calibration coverage.
