# Phase R10 — Live sample paths for PRIOR_ONLY FI adapter: DONE

Date: 2026-10-26 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/r10-live-samples`. Prior: [PHASE_R9_LIVE_MD_ADAPTER_DONE.md](PHASE_R9_LIVE_MD_ADAPTER_DONE.md).

Status: **R10 live path samples accepted** for research PRIOR_ONLY ingest only.
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. **Not** investment advice.
**No** `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
SCHEMA stays `vms-0.2.phase12`; package `0.2.0rc1`.

## Scope
Prefer path-level samples persisted by `vms value-rim` over always
`samples_from_point(center)` on the live `--from-value-rim` path.
Legacy out-dirs without sample arrays keep R9 compat stamps.

## Changed / added files
```
src/vms/methods/rim/distribution.py              retain capped vps_samples on primary ke
src/vms/methods/rim/track_b_exit.py              exit_vps_samples on horizon summaries
src/vms/reporting/value_rim_bundle.py            serialize vps_samples into rim_distribution
src/vms/reporting/prior_only_fi_bundle.py        optional live sample overrides + LIVE-SAMPLES cite
src/vms/reporting/fi_method_distribution_adapter.py  prefer live_paths; compat fallback
src/vms/assumptions.py                           ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1
docs/assumptions.md                              regenerated
docs/calibration_protocol.md                     R10 section
tests/unit/test_r10_live_samples.py              NEW: AC1–AC6
PHASE_R10_LIVE_SAMPLES_DONE.md                   this file
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Live arrays → PRIOR_ONLY; `sample_generation=live_paths`; calibrated_claim=false | `test_ac1_*` |
| 2 | Fixture without live arrays → `samples_from_point` compat | `test_ac2_*` |
| 3 | Production intent → mixture null | `test_ac3_*` |
| 4 | Track B hist_n&lt;12 / no PER_SHARE → SKIP unchanged | `test_ac4_*` |
| 5 | Forbidden labels + SCHEMA/package; R8/R9 green | `test_ac5_*` + R8/R9 suite |
| 6 | Persist: rim_distribution / track_b carry capped samples | `test_ac6_*` |

## Hard constraints honored
- Never emit `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`
- Production `intent=production` refuses mixture
- Track B center rules unchanged (exit VPS; `pb_center_used` audit-only)
- No lift of `industry.unsupported` / 非银; MIN=12 unchanged
- calibrate-rim not primary input
- Cap default 96; no uncapped path dumps
- Optional pb_common may stay `samples_from_point` (point-only relative_vps)

## Known gaps (honest)
- pb_common still point-expanded when only `relative_vps` exists (no ROE path bank in R10).
- Production calibrated ensemble still blocked (`CALIBRATION_INSUFFICIENT`).
- Adapter remains read-only over out-dir (does not re-run MC).

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — live PRIOR_ONLY path samples ≠ investment advice.
